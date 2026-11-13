"""Equity of two hole cards against a weighted opponent range (F02 plan 3.3) and canon3 (3.4).

Public:
  equity(hero2, board, opp_weights, dead, budget_ms, rng) -> (eq, n_eff)
  deal_samples(board, opp_weights, dead, n, rng) -> [((a, b), runout), ...]     post-discard states
  deal_triple_samples(board, dead, n, rng, keep_fn) -> [((a, b), runout), ...] pre-discard states
  equity_vs_samples(hero2, board, samples) -> float                            common random numbers
  canon3(cards3) -> int in 0..1754                                             suit-isomorphism class

Conventions: card ids 0..51 (rank * 4 + suit). `dead` is a length-52 flag sequence (HandState.dead: our three
dealt cards, the board, the opponent's exposed discard), or a set / list of card ids, or None. The cards that can
never be dealt to the opponent or the runout are dead | hero2 | board (the union is taken defensively).
`opp_weights`: None (uniform), a length-1326 sequence indexed by cards.pair_index (list, tuple, numpy array) or a
dict {(a, b): w}. Non-numeric, NaN, infinite or negative weights count as 0; if nothing positive is left on the
live pairs, the range falls back to uniform over them (warned once).

Pure functions apart from the module rng used when rng is None, the evaluator's memo tables and the `last_path`
diagnostic. `_now` and `_eval` are module attributes so tests can substitute a fake clock and evaluator.
"""
import bisect
import itertools
import math
import numbers
import random
import time

import params
from cards import PAIRS, pair_index, parse
from evaluator import eval7
from log import warn

_now = time.perf_counter
_eval = eval7
_RNG = random.Random()
_warned = False
last_path = ""        # diagnostic: "exact", "iid", "fallback", "mc" or "none" for the last equity() call
_INF = math.inf


# ----------------------------------------------------------------------------------------------- helpers
def _norm_budget(b):
    """Real number -> itself; NaN, <= 0, bool, non-numeric -> 0.0; +inf stays +inf."""
    if isinstance(b, bool) or not isinstance(b, numbers.Real):
        return 0.0
    b = float(b)
    if b != b or b <= 0.0:
        return 0.0
    return b


def _excluded(dead, cards):
    """bytearray(52): dead (flags or ids) plus `cards`."""
    x = bytearray(52)
    if dead is not None:
        if isinstance(dead, (set, frozenset, dict)):
            ids, flags = dead, None
        else:
            try:
                flags = dead if len(dead) == 52 else None
            except TypeError:
                flags = None
            ids = None if flags is not None else dead
        if flags is not None:
            for i in range(52):
                if flags[i]:
                    x[i] = 1
        else:
            for c in ids:
                if isinstance(c, numbers.Integral) and not isinstance(c, bool) and 0 <= c < 52:
                    x[int(c)] = 1
    for c in cards:
        x[c] = 1
    return x


def _weight(w):
    try:
        f = float(w)
    except Exception:
        return 0.0
    if f != f or f <= 0.0 or f == _INF:
        return 0.0
    return f


def _range(opp_weights, x):
    """(pairs, ws, cum, total) over the pairs with no card in x; ws rescaled so that max(ws) == 1."""
    global _warned
    live = [i for i, (a, b) in enumerate(PAIRS) if not x[a] and not x[b]]
    pairs, ws = [], []
    if opp_weights is not None:
        if isinstance(opp_weights, dict):
            raw = {}
            for k, w in opp_weights.items():
                try:
                    a, b = int(k[0]), int(k[1])
                except Exception:
                    continue
                if a != b and 0 <= a < 52 and 0 <= b < 52:
                    raw[pair_index(a, b)] = w
            get = raw.get
        else:
            seq = opp_weights.tolist() if hasattr(opp_weights, "tolist") else opp_weights
            try:
                ok = len(seq) == 1326
            except TypeError:
                ok = False
            get = seq.__getitem__ if ok else (lambda i: 0.0)
        for i in live:
            w = _weight(get(i))
            if w > 0.0:
                pairs.append(PAIRS[i])
                ws.append(w)
        if pairs:
            m = max(ws)
            ws = [w / m for w in ws]
        elif live and not _warned:
            _warned = True
            warn("equity: opponent range empty after dead cards / invalid weights; using uniform")
    if not pairs:
        pairs = [PAIRS[i] for i in live]
        ws = [1.0] * len(pairs)
    cum = list(itertools.accumulate(ws))
    total = cum[-1] if cum else 0.0
    return pairs, ws, cum, total


def _drawer(pairs, cum, total, rest, k, rng):
    """Return draw() -> ((a, b), runout): pair drawn proportional to weight, runout uniform from rest minus the
    pair, sorted. Rejection on a collision with the pair keeps the runout uniform."""
    rnd = rng.random
    last = len(pairs) - 1
    m = len(rest)
    br = bisect.bisect_right

    def pick():
        i = br(cum, rnd() * total)
        return pairs[i if i <= last else last]

    if k == 0:
        return lambda: (pick(), ())
    if k == 1:
        def draw1():
            p = pick()
            a, b = p
            while True:
                r = rest[int(rnd() * m)]
                if r != a and r != b:
                    return p, (r,)
        return draw1
    if k == 2:
        def draw2():
            p = pick()
            a, b = p
            while True:
                i1 = int(rnd() * m)
                i2 = int(rnd() * (m - 1))
                if i2 >= i1:
                    i2 += 1
                r1 = rest[i1]
                r2 = rest[i2]
                if r1 != a and r1 != b and r2 != a and r2 != b:
                    return p, ((r1, r2) if r1 < r2 else (r2, r1))
        return draw2

    def drawk():
        p = pick()
        while True:
            run = rng.sample(rest, k)
            if p[0] not in run and p[1] not in run:
                return p, tuple(sorted(run))
    return drawk


# ----------------------------------------------------------------------------------------------- equity
def equity(hero2, board, opp_weights=None, dead=None, budget_ms=0.0, rng=None):
    """Equity (win + tie/2) of `hero2` (2 ids) on `board` (3-5 ids) against `opp_weights`, within `budget_ms`.

    Returns (eq, n_eff): eq in [0, 1]; n_eff = number of i.i.d. samples, or (sum w)^2 / sum w^2 for an exact
    river enumeration. Budget: 0 / negative / NaN / non-numeric -> exactly MIN_SAMPLES samples (river: i.i.d.);
    +inf -> exactly MAX_SAMPLES (turn/flop) or exact enumeration (river). The deadline is set at entry.
    No live opponent pair at all -> (0.5, 0.0).
    """
    global last_path
    t0 = _now()
    b = _norm_budget(budget_ms)
    deadline = _INF if b == _INF else t0 + b / 1000.0
    if rng is None:
        rng = _RNG
    hero = tuple(int(c) for c in hero2)
    bd = tuple(int(c) for c in board)
    x = _excluded(dead, hero + bd)
    pairs, ws, cum, total = _range(opp_weights, x)
    if not pairs:
        last_path = "none"
        return 0.5, 0.0
    if len(bd) == 5:
        return _river(hero, bd, pairs, ws, cum, total, b, deadline, rng)
    last_path = "mc"
    rest = [c for c in range(52) if not x[c]]
    return _mc(hero, bd, _drawer(pairs, cum, total, rest, 5 - len(bd), rng), deadline)


def _mc(hero, bd, draw, deadline):
    """Monte Carlo over (pair, runout) to the deadline: checkpoints MIN, MIN+CHECK, ..., capped at MAX."""
    ev = _eval
    now = _now
    hb = hero + bd
    hcache = {}
    mx = params.MAX_SAMPLES
    chk = max(1, params.CHECK_EVERY)
    block = max(1, min(params.MIN_SAMPLES, mx))
    n = 0
    acc = 0.0
    while True:
        for _ in range(block):
            p, run = draw()
            hv = hcache.get(run)
            if hv is None:
                hv = hcache[run] = ev(hb + run)
            ov = ev(p + bd + run)
            if hv > ov:
                acc += 1.0
            elif hv == ov:
                acc += 0.5
        n += block
        if n >= mx or now() >= deadline:
            break
        block = min(chk, mx - n)
    return acc / n, float(n)


def _river(hero, bd, pairs, ws, cum, total, b, deadline, rng):
    """River: rng-free calibration on the enumeration prefix, then exact enumeration or i.i.d. (plan 3.3)."""
    global last_path
    ev = _eval
    now = _now
    hv = ev(hero + bd)
    P = len(pairs)
    mn = max(1, params.MIN_SAMPLES)
    chk = max(1, params.CHECK_EVERY)
    vals = [0.0] * P                   # value of each enumerated pair (filled in order)

    def enum(j, stop):
        """Enumerate pairs j..stop-1 with a clock check every chk pairs. Returns the index reached."""
        while j < stop:
            e = min(stop, j + chk)
            for i in range(j, e):
                ov = ev(pairs[i] + bd)
                vals[i] = 1.0 if hv > ov else (0.5 if hv == ov else 0.0)
            j = e
            if j < P and now() >= deadline:
                return j
        return j

    def exact():
        global last_path
        last_path = "exact"
        sw = swv = sww = 0.0
        for w, v in zip(ws, vals):
            sw += w
            swv += w * v
            sww += w * w
        return min(1.0, max(0.0, swv / sw)), sw * sw / sww

    def iid(fixed):
        global last_path
        last_path = "fallback" if fixed else "iid"
        rnd = rng.random
        br = bisect.bisect_right
        last = P - 1
        mx = params.MAX_SAMPLES
        block = mn if fixed else max(1, min(mn, mx))
        n = 0
        acc = 0.0
        while True:
            for _ in range(block):
                i = br(cum, rnd() * total)
                ov = ev(pairs[i if i <= last else last] + bd)
                if hv > ov:
                    acc += 1.0
                elif hv == ov:
                    acc += 0.5
            n += block
            if fixed or n >= mx or now() >= deadline:
                break
            block = min(chk, mx - n)
        return acc / n, float(n)

    if b == _INF or P <= mn:
        # inf: deadline never interrupts. P <= MIN_SAMPLES: the whole range costs no more than the i.i.d.
        # minimum, so it is enumerated without clock checks (rng-free, exact).
        for i in range(P):
            ov = ev(pairs[i] + bd)
            vals[i] = 1.0 if hv > ov else (0.5 if hv == ov else 0.0)
        return exact()
    if b == 0.0:
        return iid(False)              # stops at the first checkpoint: exactly MIN_SAMPLES
    cal = min(mn, P)
    t_start = now()
    j = enum(0, cal)
    if j == P:
        return exact()
    if j < cal or now() >= deadline:   # deadline passed during calibration
        return iid(True)
    t_cal = now()
    t_pair = (t_cal - t_start) / cal
    if deadline - t_cal >= params.RIVER_SAFETY * (P - cal) * t_pair:
        if enum(cal, P) == P:
            return exact()
        return iid(True)               # slowed down after calibration: discard the partial enumeration
    return iid(False)


# ----------------------------------------------------------------------------------------------- common random numbers
def deal_samples(board, opp_weights, dead, n, rng):
    """n post-discard samples ((a, b), runout): pair drawn proportional to weight (cards not in dead | board),
    runout = the 5 - len(board) missing board cards, uniform from the rest. Our hole cards must be in dead."""
    bd = tuple(int(c) for c in board)
    x = _excluded(dead, bd)
    pairs, ws, cum, total = _range(opp_weights, x)
    if not pairs or n <= 0:
        return []
    draw = _drawer(pairs, cum, total, [c for c in range(52) if not x[c]], 5 - len(bd), rng)
    return [draw() for _ in range(int(n))]


def _keep(keep_fn, tri, bd):
    try:
        res = keep_fn(tri, bd)
        a, b = res
        a, b = a.__index__(), b.__index__()
        if a != b and a in tri and b in tri:
            return (a, b) if a < b else (b, a)
    except Exception:
        pass
    lo = min(tri)                      # the engine's default discard: lowest rank, then s < h < d < c (= min id)
    a, b = [c for c in tri if c != lo]
    return (a, b) if a < b else (b, a)


def deal_triple_samples(board, dead, n, rng, keep_fn):
    """n pre-discard samples ((a, b), runout): the opponent's triple is uniform over cards not in dead | board,
    keep_fn(triple, board) -> the 2 cards they keep (a failure keeps the two highest), and the runout avoids all
    three of their cards (the discarded one included)."""
    bd = tuple(int(c) for c in board)
    x = _excluded(dead, bd)
    rest = [c for c in range(52) if not x[c]]
    k = 5 - len(bd)
    if n <= 0 or len(rest) < 3 + k:
        return []
    out = []
    sample = rng.sample
    for _ in range(int(n)):
        tri = tuple(sample(rest, 3))
        pair = _keep(keep_fn, tri, bd)
        if k:
            while True:
                run = sample(rest, k)
                if tri[0] not in run and tri[1] not in run and tri[2] not in run:
                    break
            run = tuple(sorted(run))
        else:
            run = ()
        out.append((pair, run))
    return out


def equity_vs_samples(hero2, board, samples):
    """Mean showdown value (win 1, tie 0.5) of hero2 over the samples; 0.5 for no samples.
    Contract: no sample card overlaps hero2 or board."""
    if not samples:
        return 0.5
    ev = _eval
    hb = tuple(int(c) for c in hero2) + tuple(int(c) for c in board)
    bd = hb[2:]
    hcache = {}
    acc = 0.0
    for p, run in samples:
        hv = hcache.get(run)
        if hv is None:
            hv = hcache[run] = ev(hb + run)
        ov = ev(tuple(p) + bd + run)
        if hv > ov:
            acc += 1.0
        elif hv == ov:
            acc += 0.5
    return acc / len(samples)


# ----------------------------------------------------------------------------------------------- canon3
def _canon_key(cards3):
    a, b, c = sorted(cards3, key=lambda x: x >> 2, reverse=True)
    ra, rb, rc = a >> 2, b >> 2, c >> 2
    sa, sb, sc = a & 3, b & 3, c & 3
    if ra == rc:
        return (2, ra)
    if ra == rb:
        return (1, ra, rc, int(sc == sa or sc == sb))
    if rb == rc:
        return (1, rb, ra, int(sa == sb or sa == sc))
    if sa == sb == sc:
        pat = 0
    elif sa == sb:
        pat = 1
    elif sa == sc:
        pat = 2
    elif sb == sc:
        pat = 3
    else:
        pat = 4
    return (0, ra, rb, rc, pat)


def _all_keys():
    keys = [(2, r) for r in range(13)]
    keys += [(1, p, k, s) for p in range(13) for k in range(13) if k != p for s in (0, 1)]
    keys += [(0, r1, r2, r3, pat) for r1 in range(13) for r2 in range(r1) for r3 in range(r2) for pat in range(5)]
    return sorted(keys)


_CANON = {k: i for i, k in enumerate(_all_keys())}     # 1,755 keys; the sorted order is the index (F07 contract)


def canon3(cards3):
    """Suit-isomorphism class (0..1754) of 3 distinct cards (ids or strings like "As"), invariant under card order
    and all 24 suit permutations. Key: ranks plus which cards share a suit; index = position in the sorted keys."""
    ids = [parse(c) if isinstance(c, str) else int(c) for c in cards3]
    return _CANON[_canon_key(ids)]
