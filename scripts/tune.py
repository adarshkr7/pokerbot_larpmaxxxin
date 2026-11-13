"""SPSA tuning of bot/params.py constants by engine matches (dev tool; nothing here ships).

    python scripts/tune.py --iters 300 --jobs 14 --run spsa1          # tune, logging to logs/tune/spsa1/
    python scripts/tune.py --resume --run spsa1 --iters 400           # continue from the last saved theta
    python scripts/tune.py --show --run spsa1                         # print the current theta as overrides

The run tunes a snapshot of bot/ (logs/tune/<run>/bot/, copied on the first start). Each candidate is a generated wrapper (logs/tune/<run>/cand_*.py) that patches bot.params with overrides
before running bot/bot.py's main(), so bot/ itself is never touched. An SPSA iteration perturbs theta (every
parameter scaled to [0, 1] over its range) by +/- c_k * delta (delta = random signs) and scores theta+ against
theta- with common random numbers: head-to-head duplicate matches between them, plus both against the same
opponents on the same seeds. Per-match chip differences are clipped so one wild match does not dominate.

Apply the result by copying the printed overrides into bot/params.py, then verify with scripts/promote.py.
"""
import argparse
import json
import math
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arena  # noqa: E402

ROOT = arena.ROOT
BOT_DIR = ROOT / "bot"

# name: (default, lo, hi). "A.key" = a dict entry; "*_SCALE" / "*_OFF" are derived (see overrides()).
SPACE = {
    "PF_OPEN_PCT": (0.78, 0.50, 0.95),
    "PF_THREEBET_PCT": (0.15, 0.05, 0.30),
    "PF_OPEN_BB": (3.0, 2.0, 4.5),
    "PF_ISO_PCT": (0.30, 0.10, 0.55),
    "PF_DEFEND_SCALE": (1.0, 0.70, 1.15),
    "PF_CONT3_SCALE": (1.0, 0.60, 1.40),
    "PF_CALL_MARGIN": (0.0, -0.04, 0.06),
    "BET_R_IP": (1.08, 0.95, 1.20),
    "BET_R_OOP": (0.92, 0.80, 1.05),
    "BET_MARGIN.flop": (0.03, -0.03, 0.09),
    "BET_MARGIN.turn": (0.03, -0.03, 0.09),
    "BET_MARGIN.river": (0.0, -0.04, 0.06),
    "BET_VALUE_TH.flop": (0.60, 0.50, 0.70),
    "BET_VALUE_TH.turn": (0.58, 0.50, 0.68),
    "BET_VALUE_TH.river": (0.56, 0.48, 0.66),
    "BET_RAISE_OFF": (0.0, -0.06, 0.08),
    "BET_THIN_TH": (0.66, 0.58, 0.76),
    "BET_AIR_TH": (0.22, 0.10, 0.35),
    "BET_BLUFF_V": (0.25, 0.08, 0.45),
    "BET_SEMI_P_BASE": (0.20, 0.0, 0.50),
    "BET_TILT_RAISE": (1.1, 0.5, 1.8),
    "BET_PRIOR_FLOOR": (0.03, 0.005, 0.10),
}
NAMES = list(SPACE)


def to_values(theta):
    return {n: SPACE[n][1] + t * (SPACE[n][2] - SPACE[n][1]) for n, t in zip(NAMES, theta)}


def default_theta():
    return [(SPACE[n][0] - SPACE[n][1]) / (SPACE[n][2] - SPACE[n][1]) for n in NAMES]


def overrides(values):
    """Concrete params assignments (python literals) for a value dict."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("params_src", BOT_DIR / "params.py")
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    out = {}
    for n, v in values.items():
        if n == "PF_DEFEND_SCALE":
            out["PF_DEFEND_CURVE"] = tuple((p, min(0.99, s * v)) for p, s in base.PF_DEFEND_CURVE)
        elif n == "PF_CONT3_SCALE":
            out["PF_CONT3_CURVE"] = tuple((p, min(0.99, s * v)) for p, s in base.PF_CONT3_CURVE)
        elif n == "BET_RAISE_OFF":
            out["BET_RAISE_TH"] = {k: round(x + v, 4) for k, x in base.BET_RAISE_TH.items()}
        elif "." in n:
            name, key = n.split(".")
            d = out.setdefault(name, dict(getattr(base, name)))
            d[key] = round(v, 4)
        else:
            out[n] = round(v, 4)
    return out


WRAPPER = '''import os, sys
sys.path.insert(0, {bot_dir!r})
import params
for _k, _v in {ovr!r}.items():
    setattr(params, _k, _v)
import bot
bot.main()
'''


def write_candidate(path, values):
    path.write_text(WRAPPER.format(bot_dir=str(BOT_DIR), ovr=overrides(values)))
    return path


class Args:
    def __init__(self, hands, stage=1):
        self.hands, self.stage, self.python, self.no_time_limits = hands, stage, str(arena.BOT_PY), False


def match(a, b, seed, hands):
    """Net chips per hand of bot a against bot b (both legs), or None on a failed run."""
    r = arena.play(a, f"tune/{Path(a).stem}_vs_{Path(b).stem}", b, seed, Args(hands))
    if "A" not in r or r["forfeit_A"] or r["forfeit_B"]:
        return None
    return r["A"]["net"] / max(r["hands"], 1)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", default="spsa")
    p.add_argument("--iters", type=int, default=300)
    p.add_argument("--jobs", type=int, default=14)
    p.add_argument("--hands", type=int, default=400)
    p.add_argument("--h2h", type=int, default=4, help="theta+ vs theta- matches per iteration")
    p.add_argument("--opps", nargs="*", default=["champion", "tests/potodds_bot.py", "tests/station_bot.py",
                                                  "tests/nit_bot.py", "tests/maniac_bot.py", "starter"])
    p.add_argument("--opp-sample", type=int, default=4, help="opponents drawn per iteration")
    p.add_argument("--clip", type=float, default=4.0, help="clip per-match chips/hand differences")
    p.add_argument("--a", type=float, default=0.012)
    p.add_argument("--c", type=float, default=0.12)
    p.add_argument("--A", type=float, default=30.0)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--show", action="store_true")
    args = p.parse_args()

    out = ROOT / "logs" / "tune" / args.run
    out.mkdir(parents=True, exist_ok=True)
    global BOT_DIR
    snap = out / "bot"                      # tune a frozen copy, so edits to bot/ during a run do not leak in
    if not snap.exists():
        import shutil
        shutil.copytree(BOT_DIR, snap, ignore=shutil.ignore_patterns("__pycache__"))
    BOT_DIR = snap
    state_f = out / "state.json"
    state = json.loads(state_f.read_text()) if (args.resume or args.show) and state_f.exists() else \
        {"k": 0, "theta": default_theta(), "history": []}
    if args.show:
        vals = to_values(state["theta"])
        for n in NAMES:
            print(f"{n:<22} {SPACE[n][0]:>8.4f} -> {vals[n]:>8.4f}")
        print(json.dumps(overrides(vals), indent=1))
        return
    opps = [arena.resolve(o) for o in args.opps]
    rng = random.Random(12345 + state["k"])
    theta = state["theta"]
    while state["k"] < args.iters:
        k = state["k"]
        ck = args.c / (k + 1) ** 0.101
        ak = args.a / (k + 1 + args.A) ** 0.602
        delta = [rng.choice((-1, 1)) for _ in NAMES]
        tp = [min(1.0, max(0.0, t + ck * d)) for t, d in zip(theta, delta)]
        tm = [min(1.0, max(0.0, t - ck * d)) for t, d in zip(theta, delta)]
        bp = write_candidate(out / "cand_plus.py", to_values(tp))
        bm = write_candidate(out / "cand_minus.py", to_values(tm))
        seed0 = 100000 + 100 * k
        jobs = [("h2h", bp, bm, seed0 + i, 1.0) for i in range(args.h2h)]
        for j, o in enumerate(rng.sample(opps, min(args.opp_sample, len(opps)))):
            jobs.append(("opp+", bp, o, seed0 + 50 + j, 1.0))
            jobs.append(("opp-", bm, o, seed0 + 50 + j, 1.0))
        with ThreadPoolExecutor(args.jobs) as ex:
            res = list(ex.map(lambda jb: match(jb[1], jb[2], jb[3], args.hands), jobs))
        diffs = []
        for i in range(args.h2h):
            if res[i] is not None:
                diffs.append(max(-args.clip, min(args.clip, res[i])))    # zero-sum: + gains what - loses
        for i in range(args.h2h, len(jobs), 2):
            if res[i] is not None and res[i + 1] is not None:
                diffs.append(max(-args.clip, min(args.clip, res[i] - res[i + 1])))
        if not diffs:
            print(f"iter {k}: no valid matches", flush=True)
            state["k"] += 1
            continue
        y = sum(diffs) / len(diffs)                       # estimate of f(theta+) - f(theta-)
        theta = [min(1.0, max(0.0, t + ak * y / (2 * ck * d))) for t, d in zip(theta, delta)]
        state.update(k=k + 1, theta=theta)
        state["history"].append({"k": k, "y": round(y, 4), "n": len(diffs)})
        state_f.write_text(json.dumps(state))
        moved = sorted(((abs(t - d0), n) for t, d0, n in zip(theta, default_theta(), NAMES)), reverse=True)[:3]
        print(f"iter {k}: y={y:+.3f} n={len(diffs)} top moves: "
              + ", ".join(f"{n}={to_values(theta)[n]:.3f}" for _, n in moved), flush=True)


if __name__ == "__main__":
    main()
