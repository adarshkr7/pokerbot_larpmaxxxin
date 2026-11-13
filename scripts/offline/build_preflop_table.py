"""Build bot/data/preflop.json: the equity of every canon3 preflop class vs a random 3-card hand (04/P2, 02-E4).

    .venv/Scripts/python.exe scripts/offline/build_preflop_table.py                                   # full build
    .venv/Scripts/python.exe scripts/offline/build_preflop_table.py --samples 2000 --range-samples 500 # quick look
    .venv/Scripts/python.exe scripts/offline/build_preflop_table.py --main-from bot/data/preflop.json  # ranges only

Model (recorded in the file's header):
  * opponent: a uniformly random 3-card hand from the 49 unseen cards;
  * board: flop, turn and river uniform from the rest;
  * discard: after the flop BOTH players keep their max-flop-score pair (discard.opp_discard_policy, the static
    D3 score S), with no betting;
  * equity = P(win) + P(tie) / 2 at showdown.
  * vs_top: the same, with the opponent's triple drawn uniformly from the physical hands in the top X% of all
    22,100 (ranked by the vs-random equity, combination weighted) that miss our cards, for X in WIDTHS. Used to
    price calls against an estimated raising / shoving range (04/P2, P4).

Each class is simulated from one representative triple (equity vs a suit-symmetric opponent range is invariant
under suit permutation) with its own RNG seeded from (seed, class, width), so the result does not depend on the
worker count. Offline tool: multiprocessing is fine here (this file is not part of the submission).
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOT = ROOT / "bot"
sys.path.insert(0, str(BOT))

import discard  # noqa: E402
import evaluator  # noqa: E402
from equity import canon3  # noqa: E402

OUT = BOT / "data" / "preflop.json"
WIDTHS = (0.05, 0.10, 0.20, 0.35, 0.50, 0.75)


def representatives():
    """[class] -> one physical triple (sorted card ids) of that class, and the class multiplicities."""
    rep = [None] * 1755
    mult = [0] * 1755
    for tri in combinations(range(52), 3):
        k = canon3(tri)
        mult[k] += 1
        if rep[k] is None:
            rep[k] = tri
    return rep, mult


_RANGES = {}           # width -> list of physical triples in the opponent's top-width range (set per worker)


def _init_worker(ranges):
    evaluator.warm()
    _RANGES.clear()
    _RANGES.update(ranges)


def simulate(job):
    """(cls, triple, n, seed, width) -> (cls, width, mean, se). The opponent's triple is uniform over the 49 unseen
    cards (width None) or over the physical triples of its top-`width` range that miss our cards (rejection).
    Both sides discard by the static max-S policy."""
    cls, hero, n, seed, width = job
    ev = evaluator.eval7
    pol = discard.opp_discard_policy
    rng = random.Random(seed * 1_000_003 + cls * 101 + (0 if width is None else int(round(width * 1000))))
    rest = [c for c in range(52) if c not in hero]
    sample = rng.sample
    rnd = rng.random
    rng_list = _RANGES.get(width) if width is not None else None
    hs = set(hero)
    acc = 0.0
    acc2 = 0.0
    for _ in range(n):
        if rng_list is None:
            o0, o1, o2, f0, f1, f2, t, r = sample(rest, 8)
        else:
            m = len(rng_list)
            while True:
                o0, o1, o2 = rng_list[int(rnd() * m)]
                if o0 not in hs and o1 not in hs and o2 not in hs:
                    break
            left = [c for c in rest if c != o0 and c != o1 and c != o2]
            f0, f1, f2, t, r = sample(left, 5)
        flop = (f0, f1, f2)
        hd = pol(hero, flop)
        od = pol((o0, o1, o2), flop)
        hk = tuple(c for c in hero if c != hd)
        ok = tuple(c for c in (o0, o1, o2) if c != od)
        hv = ev(hk + flop + (t, r))
        ov = ev(ok + flop + (t, r))
        if hv > ov:
            acc += 1.0
            acc2 += 1.0
        elif hv == ov:
            acc += 0.5
            acc2 += 0.25
    mean = acc / n
    var = max(0.0, acc2 / n - mean * mean)
    return cls, width, mean, math.sqrt(var / n)


def percentiles(eq, mult):
    """pct[k] = share of the 22,100 physical hands in classes ranked below k by (equity, class index); the same
    rule as bot/preflop.py, so "top X%" means the same thing in the table and in the bot."""
    pct = [0.0] * 1755
    below = 0
    for k in sorted(range(1755), key=lambda k: (eq[k], k)):
        pct[k] = below / 22100
        below += mult[k]
    return pct


def run(jobs, ranges, njobs, label):
    t0 = time.time()
    out = []
    with mp.Pool(njobs, initializer=_init_worker, initargs=(ranges,)) as pool:
        for i, res in enumerate(pool.imap_unordered(simulate, jobs, chunksize=4), 1):
            out.append(res)
            if i % 250 == 0:
                print(f"{label}: {i}/{len(jobs)} jobs, {time.time() - t0:.0f} s", file=sys.stderr, flush=True)
    return out, time.time() - t0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--samples", type=int, default=120000, help="samples per class vs a random hand")
    p.add_argument("--range-samples", type=int, default=6000, help="samples per class per range width")
    p.add_argument("--seed", type=int, default=20261113)
    p.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    p.add_argument("--main-from", type=Path, default=None,
                   help="reuse the vs-random equity (and its header) from an earlier build instead of recomputing")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()

    rep, mult = representatives()
    assert sum(mult) == 22100
    if args.main_from:
        old = json.loads(args.main_from.read_text(encoding="utf-8"))
        eq = [float(x) for x in old["equity"]]
        h = old["header"]
        main_info = {k: h[k] for k in ("samples_per_class", "seed", "max_se", "mean_se", "build_seconds")}
    else:
        res, secs = run([(k, rep[k], args.samples, args.seed, None) for k in range(1755)], {}, args.jobs, "random")
        eq = [0.0] * 1755
        se = [0.0] * 1755
        for k, _, m, s in res:
            eq[k], se[k] = round(m, 4), s
        main_info = {"samples_per_class": args.samples, "seed": args.seed, "max_se": round(max(se), 5),
                     "mean_se": round(sum(se) / len(se), 5), "build_seconds": round(secs, 1)}
        print(f"vs random: {secs:.0f} s, SE max {max(se):.4f} mean {sum(se) / len(se):.4f}", flush=True)

    pct = percentiles(eq, mult)
    by_class = {}
    for tri in combinations(range(52), 3):
        by_class.setdefault(canon3(tri), []).append(tri)
    ranges = {w: [t for k in range(1755) if pct[k] >= 1.0 - w - 1e-12 for t in by_class[k]] for w in WIDTHS}
    for w in WIDTHS:
        print(f"top {w:.0%}: {len(ranges[w])} physical triples ({len(ranges[w]) / 22100:.3f})", flush=True)
    jobs = [(k, rep[k], args.range_samples, args.seed, w) for w in WIDTHS for k in range(1755)]
    res, rsecs = run(jobs, ranges, args.jobs, "ranges")
    vs = {w: [0.0] * 1755 for w in WIDTHS}
    rse = []
    for k, w, m, s in res:
        vs[w][k] = round(m, 3)
        rse.append(s)
    print(f"vs ranges: {rsecs:.0f} s, SE max {max(rse):.4f} mean {sum(rse) / len(rse):.4f}", flush=True)

    header = {
        "what": "equity (win + tie/2) of each canon3 class vs a 3-card opponent hand, at showdown",
        "index": "equity.canon3 (0..1754)",
        "opponent_range": "equity: uniform random 3 cards from the 49 unseen; vs_top[i]: uniform over the physical "
                          "triples of the top range_widths[i] of all 22,100 hands (ranked by `equity`, combination "
                          "weighted) that miss our cards",
        "discard_policy": "both players: discard.opp_discard_policy (keep max static flop score S), no betting",
        **main_info,
        "range_widths": list(WIDTHS),
        "range_samples_per_class": args.range_samples,
        "range_max_se": round(max(rse), 5),
        "range_build_seconds": round(rsecs, 1),
        "generator": "scripts/offline/build_preflop_table.py",
    }
    data = {"header": header, "equity": eq, "vs_top": [vs[w] for w in WIDTHS]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
