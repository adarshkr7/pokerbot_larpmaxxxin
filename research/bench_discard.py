"""Research measurements for Discard Hold'em (scratch, not part of the bot)."""
import random, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "starter_kit"))
import engine as E

RANKS = "23456789TJQKA"
DECK = [r + s for r in RANKS for s in "shdc"]
CID = {c: i for i, c in enumerate(DECK)}          # id = rank*4 + suit
STRAIGHTS = [(0x1F << i, i + 4) for i in range(8, -1, -1)] + [(0x100F, 3)]  # A-5 wheel


def straight_hi(mask):
    for m, hi in STRAIGHTS:
        if mask & m == m:
            return hi
    return -1


def eval7(ids):
    """Fast 5-7 card evaluator. Returns an int; higher is better."""
    cnt = [0] * 13
    smask = [0, 0, 0, 0]
    for c in ids:
        r = c >> 2
        cnt[r] += 1
        smask[c & 3] |= 1 << r
    for m in smask:
        if bin(m).count("1") >= 5:
            sh = straight_hi(m)
            if sh >= 0:
                return (8 << 20) | sh
            top = [r for r in range(12, -1, -1) if m >> r & 1][:5]
            flush = (5 << 20) | sum(r << (4 * (4 - i)) for i, r in enumerate(top))
            break
    else:
        flush = None
    quads = trips = None
    pairs = []
    singles = []
    for r in range(12, -1, -1):
        n = cnt[r]
        if n == 4: quads = r
        elif n == 3:
            if trips is None: trips = r
            else: pairs.append(r)
        elif n == 2: pairs.append(r)
        elif n == 1: singles.append(r)
    if quads is not None:
        k = max([r for r in range(13) if cnt[r] and r != quads])
        return (7 << 20) | (quads << 4) | k
    if trips is not None and pairs:
        return (6 << 20) | (trips << 4) | max(pairs)
    if flush is not None:
        return flush
    rmask = sum(1 << r for r in range(13) if cnt[r])
    sh = straight_hi(rmask)
    if sh >= 0:
        return (4 << 20) | sh
    if trips is not None:
        k = sorted(singles, reverse=True)[:2]
        return (3 << 20) | (trips << 8) | (k[0] << 4) | k[1]
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        k = max([r for r in range(13) if cnt[r] and r not in (p1, p2)])
        return (2 << 20) | (p1 << 8) | (p2 << 4) | k
    if pairs:
        k = singles[:3]
        return (1 << 20) | (pairs[0] << 12) | (k[0] << 8) | (k[1] << 4) | k[2]
    k = singles[:5]
    return sum(r << (4 * (4 - i)) for i, r in enumerate(k))


def check_eval(n=20000, rng=random.Random(0)):
    for _ in range(n):
        a = rng.sample(DECK, 9)
        h1, h2, b = a[:2], a[2:4], a[4:]
        e1 = E.best_hand(h1, b); e2 = E.best_hand(h2, b)
        f1 = eval7([CID[c] for c in h1 + b]); f2 = eval7([CID[c] for c in h2 + b])
        assert (e1 > e2) == (f1 > f2) and (e1 == e2) == (f1 == f2), (h1, h2, b, e1, e2, f1, f2)
    print(f"evaluator agrees with engine on {n} random head-to-head showdowns")


def bench():
    rng = random.Random(1)
    hands = [rng.sample(DECK, 7) for _ in range(5000)]
    t = time.perf_counter()
    for h in hands: E.best_hand(h[:2], h[2:])
    te = time.perf_counter() - t
    ids = [[CID[c] for c in h] for h in hands]
    t = time.perf_counter()
    for _ in range(4):
        for h in ids: eval7(h)
    tf = time.perf_counter() - t
    print(f"engine best_hand: {5000/te:,.0f} evals/s | fast eval7: {20000/tf:,.0f} evals/s")


def equity_keep(keep, board3, dead, n, rng):
    """Equity of 2-card keep on a flop vs a random 2-card opp hand, MC over turn/river."""
    rest = [c for c in range(52) if c not in dead]
    win = 0.0
    for _ in range(n):
        s = rng.sample(rest, 4)
        board = board3 + s[2:]
        a = eval7(keep + board); b = eval7(s[:2] + board)
        win += 1.0 if a > b else 0.5 if a == b else 0.0
    return win / n


def discard_study(deals=1500, n=300):
    rng = random.Random(2)
    agree = 0; loss_lowest = 0.0; spread = []; big = 0
    for _ in range(deals):
        cards = rng.sample(range(52), 6)
        hole, flop = cards[:3], cards[3:]
        eqs = {}
        for drop in hole:
            keep = [c for c in hole if c != drop]
            eqs[drop] = equity_keep(keep, flop, set(cards), n, rng)
        best = max(eqs, key=eqs.get)
        lowest = min(hole, key=lambda c: (c >> 2, c & 3))
        agree += best == lowest
        loss_lowest += eqs[best] - eqs[lowest]
        sp = max(eqs.values()) - min(eqs.values())
        spread.append(sp); big += sp > 0.15
    spread.sort()
    print(f"discard study ({deals} flops, {n} MC samples per keep, opp = random 2 cards):")
    print(f"  'toss lowest rank' == max-equity discard: {agree/deals:.1%}")
    print(f"  mean equity lost by 'toss lowest': {loss_lowest/deals:.2%}")
    print(f"  equity spread best-vs-worst discard: median {spread[len(spread)//2]:.1%}, "
          f"p90 {spread[int(len(spread)*.9)]:.1%}; spread > 15% in {big/deals:.1%} of flops")


def flop_hit_study(n=200000):
    rng = random.Random(3)
    res = {2: [0, 0, 0], 3: [0, 0, 0]}   # pair+ on flop, flush draw+, (pair+ or 4-flush or OESD-ish)
    for _ in range(n):
        cards = rng.sample(range(52), 6)
        flop = cards[3:]
        for k in (2, 3):
            hole = cards[:k]
            fr = [c >> 2 for c in flop]
            hit = any((c >> 2) in fr for c in hole) or len(set(fr)) < 3 or \
                  len({c >> 2 for c in hole}) < k
            fd = any(sum(1 for c in hole + flop if c & 3 == s) >= 4 for s in range(4))
            res[k][0] += hit; res[k][1] += fd; res[k][2] += hit or fd
    for k in (2, 3):
        a, b, c = (x / n for x in res[k])
        print(f"  {k} hole cards: pair-or-better on flop {a:.1%} | 4+ to a flush {b:.1%} | either {c:.1%}")


if __name__ == "__main__":
    check_eval()
    bench()
    print("flop connection (incl. board pairs):"); flop_hit_study()
    discard_study()
