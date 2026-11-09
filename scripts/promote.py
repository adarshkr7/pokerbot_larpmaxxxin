"""Promote a candidate bot to champion only if it beats the current champion.

The "raise BEST only by winning" step of the development flow (DEVELOPMENT.md): there is one
champion (champion/bot/), and it only ever changes through this script, after the candidate passes:

  1. submission checks (scripts/build.py: allowed imports, no stray stdout prints, <= 5 MB);
  2. hard gates on the gauntlet: 0 engine notices, 0 forfeits, time used within budget;
  3. head-to-head vs the champion on paired seeds: mean chips/hand > 0 with z >= min_z;
  4. gauntlet match points >= the champion's on the same opponents and seeds.

On promotion it atomically replaces champion/bot/, writes champion/BEST.json, appends
champion/history.jsonl and rebuilds dist/submission.zip from the champion (so the zip on disk
always matches BEST). Upload only that zip.

    python scripts/promote.py                       # candidate = bot/
    python scripts/promote.py --candidate path/to/botdir --note "range-aware discard"
    python scripts/promote.py --quick               # fewer seeds/hands, for smoke tests (never promotes)
    python scripts/promote.py --dry-run             # evaluate and report, don't promote

The gauntlet (opponents, seeds, hands, thresholds) lives in champion/gauntlet.json.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def main_checkout(start):
    """The main working tree, even when run from a `git worktree` (agents work in worktrees).
    There is exactly ONE champion, and it lives in the main checkout."""
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=start, capture_output=True, text=True, check=True).stdout.strip()
        return Path(common).resolve().parent
    except (OSError, subprocess.CalledProcessError):
        return start


MAIN = main_checkout(ROOT)
CHAMP = MAIN / "champion"
CHAMP_BOT = CHAMP / "bot"
BEST = CHAMP / "BEST.json"
HISTORY = CHAMP / "history.jsonl"
GAUNTLET = CHAMP / "gauntlet.json"
LOCK = CHAMP / ".lock"
CAPS = {1: 400, 2: 1000}
BANK_S = {1: 30.0, 2: 75.0}
DEFAULT_GAUNTLET = {
    "_comment": "Promotion gauntlet. Add sparring bots (scripts/sparring/*.py paths) and rivals as they exist. "
                "Changing this file invalidates the champion's cached gauntlet score (it is re-measured).",
    "stage": 1,
    "hands": 400,
    "seeds": list(range(101, 113)),
    "opponents": ["random", "starter"],
    "h2h_seeds": list(range(201, 221)),
    "min_z": 2.0,
    "max_bank_share": 0.6,
    "jobs": max(1, (os.cpu_count() or 2) // 3),
}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = load_module("build", ROOT / "scripts" / "build.py")
arena = load_module("arena", ROOT / "scripts" / "arena.py")


# ------------------------------------------------------------------ lock (Windows-safe)
class Lock:
    def __init__(self, path, stale_s=4 * 3600):
        self.path, self.stale_s = path, stale_s

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {dt.datetime.now().isoformat()}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                age = time.time() - self.path.stat().st_mtime
                if age > self.stale_s:
                    self.path.unlink(missing_ok=True)
                    continue
                raise SystemExit(f"another promotion is running ({self.path} exists, {age:.0f}s old)")
        raise SystemExit("could not take the promotion lock")

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


# ------------------------------------------------------------------ evaluation
def gauntlet_config(quick):
    if not GAUNTLET.exists():
        CHAMP.mkdir(exist_ok=True)
        GAUNTLET.write_text(json.dumps(DEFAULT_GAUNTLET, indent=2) + "\n")
    g = json.loads(GAUNTLET.read_text())
    if quick:
        g = dict(g, hands=40, seeds=g["seeds"][:2], h2h_seeds=g["h2h_seeds"][:4])
    return g


def gauntlet_hash(g):
    keys = ("stage", "hands", "seeds", "opponents")
    return hashlib.sha1(json.dumps({k: g[k] for k in keys}, sort_keys=True).encode()).hexdigest()[:12]


def run_matches(bot_py, pairs, g):
    """pairs: list of (opp_name, opp_path, seed). Returns list of result dicts."""
    args = SimpleNamespace(python=str(arena.RIVALS_PY if arena.RIVALS_PY.exists() else sys.executable),
                           hands=g["hands"], stage=g["stage"], no_time_limits=False)
    with ThreadPoolExecutor(g["jobs"]) as ex:
        futs = [ex.submit(arena.play, bot_py, n, p, s, args) for n, p, s in pairs]
        return [f.result() for f in futs]


def score(results, g):
    cap = CAPS[g["stage"]]
    pts = capped = hands = notices = forfeits = 0
    t_max = 0.0
    failed = []
    for r in results:
        if "A" not in r:
            failed.append(r["out"].strip().splitlines()[-1:] or ["?"])
            forfeits += 1
            continue
        net = r["A"]["net"]
        if r["forfeit_A"]:
            forfeits += 1
            pts += 0
            capped += -cap
        else:
            pts += 1.0 if net > 0 else 0.5 if net == 0 else 0.0
            capped += max(-cap, min(cap, net))
        hands += r["hands"] or g["hands"]
        notices += r["A"]["notices"]
        t_max = max(t_max, r["A"]["time"])
    return {"points": pts, "matches": len(results), "capped_per_hand": capped / max(hands, 1),
            "notices": notices, "forfeits": forfeits, "max_time_s": round(t_max, 2), "failed": failed}


def h2h(results):
    per = [r["A"]["net"] / max(r["hands"], 1) for r in results if "A" in r]
    n = len(per)
    if n < 2:
        return {"n": n, "mean": float("nan"), "se": float("nan"), "z": float("-inf")}
    m = sum(per) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in per) / (n - 1))
    se = sd / math.sqrt(n)
    z = m / se if se > 0 else (float("inf") if m > 0 else float("-inf"))
    forfeits = sum(1 for r in results if r.get("forfeit_A"))
    return {"n": n, "mean": m, "se": se, "z": z, "forfeits": forfeits}


def gates(sc, g):
    problems = []
    if sc["notices"]:
        problems.append(f"{sc['notices']} engine notices (illegal/malformed replies)")
    if sc["forfeits"]:
        problems.append(f"{sc['forfeits']} forfeits/failed matches")
    limit = g["max_bank_share"] * BANK_S[g["stage"]] * 2   # engine reports time over both legs
    if sc["max_time_s"] > limit:
        problems.append(f"time used {sc['max_time_s']}s > {limit:.1f}s ({g['max_bank_share']:.0%} of bank)")
    return problems


# ------------------------------------------------------------------ promotion (atomic swap)
def copy_bot(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))


def promote(cand_dir, record):
    tmp, old = CHAMP / "bot.tmp", CHAMP / "bot.old"
    for d in (tmp, old):
        if d.exists():
            shutil.rmtree(d)
    copy_bot(cand_dir, tmp)
    if CHAMP_BOT.exists():
        CHAMP_BOT.rename(old)
    tmp.rename(CHAMP_BOT)
    if old.exists():
        shutil.rmtree(old)
    tmp_best = BEST.with_suffix(".json.tmp")
    tmp_best.write_text(json.dumps(record, indent=2) + "\n")
    os.replace(tmp_best, BEST)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps({k: record[k] for k in ("version", "date", "commit", "note", "gauntlet", "h2h")}) + "\n")
    build.build((MAIN / "dist" / "submission.zip").resolve(), CHAMP_BOT)


def promotable_source(cand):
    """Real promotions only from committed code on `main` (in the main checkout), so the champion
    always equals a commit on main. Workstream agents use --dry-run; the coordinator merges and promotes."""
    def git(*a):
        return subprocess.run(["git", *a], cwd=cand, capture_output=True, text=True).stdout.strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = git("status", "--porcelain", "--", ".")
    problems = []
    if branch != "main":
        problems.append(f"candidate is on branch '{branch}', not main (merge first, or use --dry-run)")
    if dirty:
        problems.append("candidate has uncommitted changes (commit first, so BEST records a real commit)")
    return problems


def git_commit():
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except OSError:
        return "unknown"


def fmt(sc):
    return (f"points {sc['points']}/{sc['matches']}  capped/hand {sc['capped_per_hand']:+.3f}  "
            f"notices {sc['notices']}  forfeits {sc['forfeits']}  max time {sc['max_time_s']}s")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", type=Path, default=ROOT / "bot")
    p.add_argument("--note", default="")
    p.add_argument("--quick", action="store_true", help="tiny smoke run; never promotes")
    p.add_argument("--dry-run", action="store_true", help="evaluate only")
    p.add_argument("--allow-uncommitted", action="store_true",
                   help="skip the main-branch/clean-tree requirement (bootstrap only)")
    args = p.parse_args()

    cand = args.candidate.resolve()
    if not (args.dry_run or args.quick or args.allow_uncommitted):
        src_problems = promotable_source(cand)
        if src_problems:
            print("REFUSED (real promotion):")
            for pr in src_problems:
                print(f"  - {pr}")
            raise SystemExit(1)
    errors = build.validate(cand)
    if errors:
        print("REJECTED: submission checks failed")
        for e in errors:
            print(f"  {e}")
        raise SystemExit(1)
    print(f"candidate {cand}: submission checks passed")

    g = gauntlet_config(args.quick)
    ghash = gauntlet_hash(g)
    opps = [(o, arena.resolve(o)) for o in g["opponents"]]
    pairs = [(o, path, s) for o, path in opps for s in g["seeds"]]

    with Lock(LOCK):
        best = json.loads(BEST.read_text()) if BEST.exists() and CHAMP_BOT.exists() else None
        print(f"gauntlet {ghash}: {len(opps)} opponents x {len(g['seeds'])} seeds, {g['hands']} hands, "
              f"{g['jobs']} parallel")
        cand_sc = score(run_matches(cand / "bot.py", pairs, g), g)
        print(f"  candidate : {fmt(cand_sc)}")
        problems = gates(cand_sc, g)

        champ_sc, hh = None, None
        if best:
            if best.get("gauntlet_hash") == ghash and not args.quick:
                champ_sc = best["gauntlet"]
            else:
                champ_sc = score(run_matches(CHAMP_BOT / "bot.py", pairs, g), g)
            print(f"  champion  : {fmt(champ_sc)}  ({best['version']})")
            h_pairs = [("champion", CHAMP_BOT / "bot.py", s) for s in g["h2h_seeds"]]
            hh = h2h(run_matches(cand / "bot.py", h_pairs, g))
            print(f"  head-to-head vs champion: {hh['mean']:+.3f} chips/hand +/- {hh['se']:.3f} "
                  f"(z = {hh['z']:.2f}, {hh['n']} matches)")
            if hh.get("forfeits"):
                problems.append(f"{hh['forfeits']} forfeits in head-to-head")
            if hh["z"] < g["min_z"]:
                problems.append(f"head-to-head z {hh['z']:.2f} < {g['min_z']}")
            if cand_sc["points"] < champ_sc["points"]:
                problems.append(f"gauntlet points {cand_sc['points']} < champion {champ_sc['points']}")

        if problems:
            print("NOT PROMOTED:")
            for pr in problems:
                print(f"  - {pr}")
            raise SystemExit(2)
        if args.quick or args.dry_run:
            print("PASSED (quick/dry run: champion unchanged)")
            return
        version = f"v{len(HISTORY.read_text().splitlines()) if HISTORY.exists() else 0}"
        record = {"version": version, "date": dt.datetime.now().isoformat(timespec="seconds"),
                  "commit": git_commit(), "note": args.note, "source": str(cand),
                  "gauntlet_hash": ghash, "gauntlet": cand_sc, "h2h": hh,
                  "previous": best["version"] if best else None}
        promote(cand, record)
        print(f"PROMOTED {version}: champion/bot updated, dist/submission.zip rebuilt from it")


if __name__ == "__main__":
    main()
