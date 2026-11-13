"""Benchmarks for the F02 evaluator and equity (not shipped: lives outside bot/).

    python scripts/bench_equity.py            # eval7 evals/s, equity samples/ms, river enumeration time
"""
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

t0 = time.perf_counter()
import equity as Q             # noqa: E402
import evaluator               # noqa: E402
IMPORT_MS = (time.perf_counter() - t0) * 1000
from cards import dead_mask, parse   # noqa: E402


def ids(s):
    return [parse(x) for x in s.split()]


def bench_eval7():
    rng = random.Random(1)
    hands = [tuple(rng.sample(range(52), 7)) for _ in range(200000)]
    t = time.perf_counter()
    for h in hands:
        evaluator.eval7(h)
    cold = len(hands) / (time.perf_counter() - t)
    t = time.perf_counter()
    for h in hands:
        evaluator.eval7(h)
    warm = len(hands) / (time.perf_counter() - t)
    t = time.perf_counter()
    evaluator.warm()
    warm_ms = (time.perf_counter() - t) * 1000
    print(f"import equity (+evaluator, cards): {IMPORT_MS:.1f} ms")
    print(f"eval7, 7 cards: first pass (memo filling) {cold:,.0f} evals/s | memo warm {warm:,.0f} evals/s")
    print(f"evaluator.warm() fills all tables in {warm_ms:.0f} ms")


def spots():
    rng = random.Random(2)
    out = []
    for _ in range(20):
        c = rng.sample(range(52), 9)
        out.append((c[:3], c[3:8], c[8]))     # hero3, 5 board cards, opponent discard
    return out


def bench_equity():
    for name, nb in (("flop", 3), ("turn", 4)):
        n_tot = t_tot = 0.0
        for hero3, board5, od in spots():
            board = board5[:nb]
            dead = dead_mask(hero3 + board + [od])
            t = time.perf_counter()
            _, n = Q.equity(hero3[:2], board, None, dead, math.inf, random.Random(3))
            t_tot += time.perf_counter() - t
            n_tot += n
        print(f"equity {name}: {n_tot / (t_tot * 1000):.0f} samples/ms (uniform range, {int(n_tot)} samples)")
        for b in (5, 20):
            hero3, board5, od = spots()[0]
            board = board5[:nb]
            _, n = Q.equity(hero3[:2], board, None, dead_mask(hero3 + board + [od]), b, random.Random(4))
            print(f"    budget {b} ms -> {int(n)} samples")
    ts = []
    for hero3, board5, od in spots():
        dead = dead_mask(hero3 + board5 + [od])
        t = time.perf_counter()
        _, n_eff = Q.equity(hero3[:2], board5, None, dead, math.inf, None)
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    print(f"equity river exact enumeration (903 pairs): median {ts[len(ts) // 2]:.2f} ms, max {ts[-1]:.2f} ms")
    for b in (1, 3, 5, 10):
        hero3, board5, od = spots()[1]
        Q.equity(hero3[:2], board5, None, dead_mask(hero3 + board5 + [od]), b, random.Random(5))
        print(f"    river budget {b} ms -> path {Q.last_path}")


def bench_cost_correlation():
    """Informational (plan 6F): eval7 cost for opponent hands that beat hero vs that lose, memo warm."""
    rng = random.Random(6)
    win = lose = 0.0
    nw = nl = 0
    for _ in range(20000):
        c = rng.sample(range(52), 9)
        h, o, b = c[:2], c[2:4], c[4:]
        hv = evaluator.eval7(h + b)
        hand = o + b
        t = time.perf_counter()
        ov = evaluator.eval7(hand)
        dt = time.perf_counter() - t
        if ov > hv:
            win += dt
            nw += 1
        else:
            lose += dt
            nl += 1
    print(f"eval7 cost: opponent ahead {win / nw * 1e6:.2f} us, behind/tied {lose / nl * 1e6:.2f} us")


if __name__ == "__main__":
    bench_eval7()
    bench_equity()
    bench_cost_correlation()
