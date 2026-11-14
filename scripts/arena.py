"""Play our bot against a pool of opponents over many seeds and summarise the results.

    python scripts/arena.py                                  # bot/bot.py vs the default pool, 4 seeds
    python scripts/arena.py --opps random tests/nit_bot.py --seeds 10
    python scripts/arena.py --bot champion/bot/bot.py --opps random starter
    python scripts/arena.py --hands 100 --seeds 2 --jobs 6   # quick smoke run

Opponents are the built-ins `random` and `starter` (organiser kit), `champion` (the frozen champion), or any
path to a bot file, e.g. our own sparring bots in tests/. The default pool is DEFAULT_OPPS. Each (opponent, seed) is one full
duplicate match through starter_kit/engine.py, logged to logs/arena/<opponent>/seed<S>/.

Timing numbers are only meaningful with --jobs 1 (parallel matches compete for the CPU).
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "starter_kit" / "engine.py"
BUILTIN = {"random": ROOT / "starter_kit" / "example_bots" / "random_bot.py",
           "starter": ROOT / "starter_kit" / "bot.py",
           "champion": ROOT / "champion" / "bot" / "bot.py"}
DEFAULT_OPPS = ["random", "starter", "champion", "tests/shove_bot.py", "tests/station_bot.py",
                "tests/nit_bot.py", "tests/maniac_bot.py", "tests/potodds_bot.py", "tests/tag_bot.py",
                "tests/minraise_bot.py", "tests/checkraise_bot.py", "tests/sizetell_bot.py", "tests/overbet_bot.py"]
BOT_PY = ROOT / ".venv" / "Scripts" / "python.exe"      # the venv with numpy/scipy
if not BOT_PY.exists():
    BOT_PY = ROOT / ".venv" / "bin" / "python"
if not BOT_PY.exists():
    BOT_PY = Path(sys.executable)

LINE = re.compile(r"^\s+([AB])\s+.*?net\s+([+-]?\d+)\s+time used\s+([\d.]+) s.*notices (\d+)", re.M)


def resolve(name):
    if name in BUILTIN:
        return BUILTIN[name]
    p = Path(name)
    if not p.is_absolute():
        p = ROOT / p
    if p.is_file():
        return p.resolve()
    raise SystemExit(f"unknown opponent '{name}' (not a builtin or a path to a bot file)")


def play(bot, opp_name, opp_path, seed, args):
    log_dir = ROOT / "logs" / "arena" / opp_name.replace("/", "_").replace("\\", "_") / f"seed{seed}"
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ENGINE), str(bot), str(opp_path), "--seed", str(seed),
           "--python", args.python, "--log-dir", str(log_dir), "--stage", str(args.stage)]
    if args.hands:
        cmd += ["--hands", str(args.hands)]
    if args.no_time_limits:
        cmd.append("--no-time-limits")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout + proc.stderr
    r = {"seed": seed, "ok": proc.returncode == 0, "out": out}
    m = re.search(r"(\d+) of (\d+) hands played", out)
    r["played"], r["hands"] = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    for side, net, used, notices in LINE.findall(out):
        r[side] = {"net": int(net), "time": float(used), "notices": int(notices)}
    r["forfeit_A"] = bool(re.search(r"^A forfeited", out, re.M))
    r["forfeit_B"] = bool(re.search(r"^B forfeited", out, re.M))
    return r


def summarise(opp, results):
    rs = [r for r in results if "A" in r]
    if not rs:
        return f"{opp:<24} FAILED: " + (results[0]["out"].strip().splitlines() or ["?"])[-1]
    nets = [r["A"]["net"] for r in rs]
    hands = sum(r["hands"] for r in rs) or 1
    w = sum(n > 0 for n in nets); l = sum(n < 0 for n in nets); d = len(nets) - w - l
    per_match = [r["A"]["net"] / max(r["hands"], 1) for r in rs]
    mean = sum(nets) / hands
    sd = (sum((x - sum(per_match) / len(per_match)) ** 2 for x in per_match)
          / max(len(per_match) - 1, 1)) ** 0.5
    se = sd / math.sqrt(len(per_match)) if len(per_match) > 1 else float("nan")
    notices = sum(r["A"]["notices"] for r in rs)
    t_max = max(r["A"]["time"] for r in rs)
    t_opp = max(r["B"]["time"] for r in rs)
    ff = f"{sum(r['forfeit_A'] for r in rs)}/{sum(r['forfeit_B'] for r in rs)}"
    return (f"{opp:<24} {w:>2}-{d}-{l:<2} {mean:>+8.3f} +/-{se:>6.3f}  {notices:>7}  "
            f"{t_max:>7.2f}  {t_opp:>7.2f}  {ff:>5}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bot", default=str(ROOT / "bot" / "bot.py"))
    p.add_argument("--opps", "--rivals", dest="opps", nargs="*", default=None,
                   help="opponents: random, starter, champion or bot paths (default: DEFAULT_OPPS)")
    p.add_argument("--seeds", type=int, default=4, help="matches per opponent")
    p.add_argument("--seed-base", type=int, default=1000)
    p.add_argument("--hands", type=int, default=None, help="hands per match (default: stage's)")
    p.add_argument("--stage", type=int, choices=(1, 2), default=1)
    p.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 3))
    p.add_argument("--python", default=str(BOT_PY), help="interpreter for both bots (default: .venv)")
    p.add_argument("--no-time-limits", action="store_true",
                   help="disable clocks (debugging only); timing columns meaningless")
    args = p.parse_args()

    opps = args.opps if args.opps else list(DEFAULT_OPPS)
    bot = Path(args.bot).resolve()
    jobs = [(o, resolve(o), args.seed_base + i) for o in opps for i in range(args.seeds)]
    print(f"{bot.relative_to(ROOT) if bot.is_relative_to(ROOT) else bot} vs {len(opps)} opponents "
          f"x {args.seeds} seeds, {args.jobs} parallel"
          + (" [NO TIME LIMITS]" if args.no_time_limits else ""), flush=True)
    results = {o: [] for o in opps}
    with ThreadPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(play, bot, o, path, s, args): o for o, path, s in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            results[futs[f]].append(f.result())
            print(f"\r  {i}/{len(jobs)} matches done", end="", flush=True)
    print("\n")
    print(f"{'opponent':<24} {'W-D-L':<6} {'chips/hand':>9} {'+/-SE':>9}  notices  ourTmax  oppTmax  "
          f"ff us/opp")
    for o in opps:
        print(summarise(o, results[o]))
    print("\nchips/hand = our net chips per hand (both legs); ourTmax/oppTmax = max time-bank "
          "seconds used in a match.")


if __name__ == "__main__":
    main()
