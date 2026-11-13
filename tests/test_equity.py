"""equity / sampling / canon3 (F02 plan 6B and 6D). Every random draw is seeded."""
import bisect
import itertools
import math
import random
from fractions import Fraction
from itertools import combinations

import numpy as np
import pytest
from scipy.stats import chisquare

import equity as Q
import params
from cards import PAIRS, dead_mask, fmt, pair_index, parse
from engine_util import engine
from evaluator import eval7

MIN, MAX, CHK = params.MIN_SAMPLES, params.MAX_SAMPLES, params.CHECK_EVERY


def ids(s):
    return [parse(x) for x in s.split()]


def strs(cards):
    return [fmt(c) for c in cards]


def val(h, o):
    return 1.0 if h > o else (0.5 if h == o else 0.0)


# Spots. Our hole cards are 3 (the discarded one stays dead), plus the opponent's exposed discard.
HERO3 = ids("9c 9d 3h")
HERO = HERO3[:2]
OPP_DISCARD = ids("5s")
FLOP = ids("Js 8h 4d")
TURN = FLOP + ids("2c")
RIVER = TURN + ids("Kh")


def dead_for(board):
    return dead_mask(HERO3 + board + OPP_DISCARD)


def live_pairs(dead, board):
    x = set(i for i in range(52) if dead[i]) | set(board) | set(HERO)
    return [p for p in PAIRS if p[0] not in x and p[1] not in x]


def weights_list(wmap):
    w = [0.0] * 1326
    for p, v in wmap.items():
        w[pair_index(*p)] = v
    return w


# ------------------------------------------------------------------------- exact references
def exact_river_engine(hero, board, dead, wfn):
    """Independent brute force: engine.best_hand on strings, plain loop over the live pairs."""
    hv = engine.best_hand(strs(hero), strs(board))
    sw = swv = 0.0
    for p in live_pairs(dead, board):
        w = wfn(p)
        if w > 0:
            ov = engine.best_hand(strs(p), strs(board))
            sw += w
            swv += w * val(hv, ov)
    return swv / sw


def exact_runouts(hero, board, dead, wmap=None):
    """Exact equity over all (pair, runout): pair weight w, runout uniform over cards not dead/board/hero/pair."""
    x = set(i for i in range(52) if dead[i]) | set(board) | set(hero)
    rest = [c for c in range(52) if c not in x]
    k = 5 - len(board)
    pairs = wmap.items() if wmap is not None else [(p, 1.0) for p in live_pairs(dead, board)]
    sw = swv = 0.0
    for p, w in pairs:
        tot = cnt = 0.0
        for run in combinations([c for c in rest if c not in p], k):
            b = list(board) + list(run)
            tot += val(eval7(list(hero) + b), eval7(list(p) + b))
            cnt += 1
        sw += w
        swv += w * tot / cnt
    return swv / sw


def within_4se(est, exact, n):
    se = math.sqrt(max(exact * (1 - exact), 1e-4) / n)
    return abs(est - exact) <= 4 * se


# ------------------------------------------------------------------------- B1: river exact
def test_river_exact_matches_engine_brute_force():
    dead = dead_for(RIVER)
    eq, n_eff = Q.equity(HERO, RIVER, None, dead, math.inf, random.Random(1))
    assert Q.last_path == "exact"
    assert len(live_pairs(dead, RIVER)) == 903 and n_eff == pytest.approx(903)
    assert abs(eq - exact_river_engine(HERO, RIVER, dead, lambda p: 1.0)) < 1e-12
    rng = random.Random(2)
    w = [rng.random() ** 3 for _ in range(1326)]
    eq, n_eff = Q.equity(HERO, RIVER, w, dead, math.inf, random.Random(1))
    ref = exact_river_engine(HERO, RIVER, dead, lambda p: w[pair_index(*p)])
    assert abs(eq - ref) < 1e-12
    lw = [w[pair_index(*p)] for p in live_pairs(dead, RIVER)]
    assert n_eff == pytest.approx(sum(lw) ** 2 / sum(v * v for v in lw))


def split_river(dead, board):
    hv = eval7(HERO + board)
    win, lose = [], []
    for p in live_pairs(dead, board):
        ov = eval7(list(p) + board)
        (win if hv > ov else lose if hv < ov else []).append(p)
    return win, lose


def test_river_zero_budget_concentrated_range_is_unbiased():
    dead = dead_for(RIVER)
    win, lose = split_river(dead, RIVER)
    wmap = {win[0]: 1e6}
    wmap.update({p: 1.0 for p in lose[:127]})
    exact = 1e6 / (1e6 + 127)
    assert Q.equity(HERO, RIVER, wmap, dead, math.inf, None)[0] == pytest.approx(exact, abs=1e-12)
    ests = []
    for seed in range(200):
        eq, n = Q.equity(HERO, RIVER, wmap, dead, 0, random.Random(seed))
        assert n == MIN and Q.last_path == "iid"
        ests.append(eq)
    assert abs(sum(ests) / len(ests) - exact) < 0.005


def test_river_zero_budget_uniform_within_4se():
    dead = dead_for(RIVER)
    exact = Q.equity(HERO, RIVER, None, dead, math.inf, None)[0]
    ests = [Q.equity(HERO, RIVER, None, dead, 0, random.Random(s))[0] for s in range(200)]
    assert within_4se(sum(ests) / 200, exact, 200 * MIN)


# ------------------------------------------------------------------------- B2/B3: turn and flop MC vs exact
def test_turn_mc_vs_exact_uniform():
    dead = dead_for(TURN)
    exact = exact_runouts(HERO, TURN, dead)
    eq, n = Q.equity(HERO, TURN, None, dead, math.inf, random.Random(3))
    assert n == MAX and Q.last_path == "mc"
    assert within_4se(eq, exact, n)


def three_pair_range(board):
    dead = dead_for(board)
    lp = live_pairs(dead, board)
    return {lp[0]: 1.0, lp[400]: 2.0, lp[-1]: 5.0}


def test_turn_mc_vs_exact_three_pairs():
    dead = dead_for(TURN)
    wmap = three_pair_range(TURN)
    exact = exact_runouts(HERO, TURN, dead, wmap)
    eq, n = Q.equity(HERO, TURN, wmap, dead, math.inf, random.Random(4))
    assert n == MAX and within_4se(eq, exact, n)


def test_flop_mc_vs_exact_three_pairs():
    dead = dead_for(FLOP)
    wmap = three_pair_range(FLOP)
    exact = exact_runouts(HERO, FLOP, dead, wmap)
    eq, n = Q.equity(HERO, FLOP, wmap, dead, math.inf, random.Random(5))
    assert n == MAX and within_4se(eq, exact, n)


# ------------------------------------------------------------------------- B4: sampling hygiene
def test_deal_samples_hygiene_and_frequencies():
    dead = dead_for(FLOP)
    lp = live_pairs(dead, FLOP)
    chosen = lp[::90][:10]
    wmap = {p: float(i + 1) for i, p in enumerate(chosen)}
    n = 20000
    samples = Q.deal_samples(FLOP, wmap, dead, n, random.Random(6))
    assert len(samples) == n
    blocked = set(i for i in range(52) if dead[i]) | set(FLOP)
    counts = {p: 0 for p in chosen}
    for p, run in samples:
        cards = list(p) + list(run)
        assert len(run) == 2 and len(set(cards)) == 4 and not blocked & set(cards)
        counts[p] += 1
    tot = sum(wmap.values())
    _, pval = chisquare([counts[p] for p in chosen], [n * wmap[p] / tot for p in chosen])
    assert pval > 0.001
    # uniform turn runout card frequencies
    samples = Q.deal_samples(TURN, None, dead_for(TURN), n, random.Random(7))
    rc = {}
    for p, run in samples:
        assert len(run) == 1 and run[0] not in p and not dead_for(TURN)[run[0]]
        rc[run[0]] = rc.get(run[0], 0) + 1
    assert len(rc) == 52 - 8 and chisquare(list(rc.values()))[1] > 0.001


# ------------------------------------------------------------------------- B5: weight formats and scales
def test_weight_formats_identical():
    for board in (TURN, RIVER):
        dead = dead_for(board)
        rng = random.Random(8)
        w = [rng.random() for _ in range(1326)]
        forms = [w, tuple(w), np.array(w), {PAIRS[i]: w[i] for i in range(1326)},
                 {(PAIRS[i][1], PAIRS[i][0]): w[i] for i in range(1326)}]
        ds = [Q.deal_samples(board, f, dead, 300, random.Random(9)) for f in forms]
        eqs = [Q.equity(HERO, board, f, dead, math.inf, random.Random(9)) for f in forms]
        assert all(d == ds[0] for d in ds) and all(e == eqs[0] for e in eqs)
        ones = [1.0] * 1326
        assert Q.deal_samples(board, None, dead, 300, random.Random(9)) == \
            Q.deal_samples(board, ones, dead, 300, random.Random(9))
        assert Q.equity(HERO, board, None, dead, math.inf, random.Random(9)) == \
            Q.equity(HERO, board, ones, dead, math.inf, random.Random(9))


def test_weight_scales():
    rng = random.Random(10)
    w = [rng.random() for _ in range(1326)]
    dead = dead_for(RIVER)
    base = Q.equity(HERO, RIVER, w, dead, math.inf, None)
    for s in (1e300, 1e-300):
        e = Q.equity(HERO, RIVER, [v * s for v in w], dead, math.inf, None)
        assert math.isfinite(e[0]) and math.isfinite(e[1])
        assert math.isclose(e[0], base[0], rel_tol=1e-12) and math.isclose(e[1], base[1], rel_tol=1e-12)
    dead = dead_for(TURN)
    wmap = three_pair_range(TURN)
    exact = exact_runouts(HERO, TURN, dead, wmap)
    for s in (1.0, 1e300, 1e-300):
        e, n = Q.equity(HERO, TURN, {p: v * s for p, v in wmap.items()}, dead, math.inf, random.Random(11))
        assert math.isfinite(e) and within_4se(e, exact, n)
    big = {p: 1e308 for p in list(wmap)[:2]}                      # the sum would overflow without rescaling
    e = Q.equity(HERO, RIVER, big, dead_for(RIVER), math.inf, None)
    assert all(math.isfinite(v) for v in e)


def test_bad_or_blocked_weights_fall_back_to_uniform():
    for board in (TURN, RIVER):
        dead = dead_for(board)
        ref = Q.equity(HERO, board, None, dead, math.inf, random.Random(12))
        ref_d = Q.deal_samples(board, None, dead, 200, random.Random(12))
        blocked = {(HERO3[2], c): 5.0 for c in range(52) if c != HERO3[2]}   # every pair holds a dead card
        for bad in ([float("nan")] * 1326, [-1.0] * 1326, [0.0] * 1326, ["x"] * 1326, [1.0] * 10,
                    blocked, {}, {"junk": 3}):
            assert Q.equity(HERO, board, bad, dead, math.inf, random.Random(12)) == ref
            assert Q.deal_samples(board, bad, dead, 200, random.Random(12)) == ref_d
    # NaN / inf / negative entries are ignored, the rest is kept
    dead = dead_for(RIVER)
    wmap = three_pair_range(RIVER)
    noisy = dict(wmap)
    lp = live_pairs(dead, RIVER)
    noisy.update({lp[10]: float("nan"), lp[11]: -3.0, lp[12]: float("inf")})
    assert Q.equity(HERO, RIVER, noisy, dead, math.inf, None) == Q.equity(HERO, RIVER, wmap, dead, math.inf, None)


def test_dead_formats_and_hero_board_always_excluded():
    dead = dead_for(TURN)
    ref = Q.deal_samples(TURN, None, dead, 200, random.Random(13))
    as_ids = [i for i in range(52) if dead[i]]
    assert Q.deal_samples(TURN, None, as_ids, 200, random.Random(13)) == ref
    assert Q.deal_samples(TURN, None, set(as_ids), 200, random.Random(13)) == ref
    assert Q.deal_samples(TURN, None, [bool(v) for v in dead], 200, random.Random(13)) == ref
    # equity adds hero2 and the board even when the caller forgets them
    e1 = Q.equity(HERO, RIVER, None, dead_mask(HERO3 + OPP_DISCARD), math.inf, None)
    assert e1 == Q.equity(HERO, RIVER, None, dead_for(RIVER), math.inf, None)


# ------------------------------------------------------------------------- B6: common random numbers
def test_crn_equity_vs_samples():
    hole3 = ids("As Ah 7d")
    board = ids("Kc 9s 4h")
    dead = dead_mask(hole3 + board)
    samples = Q.deal_triple_samples(board, dead, 3000, random.Random(14), lambda t, b: sorted(t)[1:])
    aa = Q.equity_vs_samples(hole3[:2], board, samples)
    assert aa == Q.equity_vs_samples(hole3[:2], board, samples)
    a7 = Q.equity_vs_samples([hole3[0], hole3[2]], board, samples)
    assert aa > a7 + 0.1
    post = Q.deal_samples(board, None, dead, 3000, random.Random(15))
    assert Q.equity_vs_samples(hole3[:2], board, post) > Q.equity_vs_samples(hole3[1:], board, post)
    assert Q.equity_vs_samples(hole3[:2], board, []) == 0.5


# ------------------------------------------------------------------------- B7: simulated machine
TICK = 2e-6          # fake seconds per tick


class Machine:
    """Fake clock + evaluator: each eval7 call advances fake time by cost(cards) ticks."""

    def __init__(self, cost):
        self.cost = cost
        self.t = 0
        self.calls = []

    def now(self):
        return self.t * TICK

    def ev(self, cards):
        self.t += self.cost(cards, len(self.calls))
        self.calls.append(tuple(cards))
        return eval7(cards)


@pytest.fixture
def machine(monkeypatch):
    def make(cost):
        m = Machine(cost)
        monkeypatch.setattr(Q, "_now", m.now)
        monkeypatch.setattr(Q, "_eval", m.ev)
        return m
    return make


def ms(ticks):
    return ticks * TICK * 1000


@pytest.mark.parametrize("board", [FLOP, TURN, RIVER])
@pytest.mark.parametrize("budget", [0, -5, float("nan"), "x", None, True])
def test_degenerate_budgets_give_min_samples(machine, board, budget):
    machine(lambda c, i: 1)
    eq, n = Q.equity(HERO, board, None, dead_for(board), budget, random.Random(16))
    assert n == MIN and Q.last_path in ("mc", "iid")


@pytest.mark.parametrize("board", [FLOP, TURN])
def test_inf_budget_gives_max_samples(machine, board):
    machine(lambda c, i: 1)
    assert Q.equity(HERO, board, None, dead_for(board), math.inf, random.Random(17))[1] == MAX


def test_inf_budget_river_enumerates(machine):
    m = machine(lambda c, i: 1)
    eq, n = Q.equity(HERO, RIVER, None, dead_for(RIVER), math.inf, random.Random(17))
    assert Q.last_path == "exact" and len(m.calls) == 1 + 903


@pytest.mark.parametrize("board", [FLOP, TURN])
def test_finite_budget_stops_at_first_checkpoint_past_deadline(machine, board):
    hero = tuple(HERO)
    machine(lambda c, i: 0 if tuple(c[:2]) == hero else 5)    # 5 ticks per opponent eval, hero free
    for samples in (64, 100, 500, 1000):
        budget_ticks = samples * 5 + 0.5
        eq, n = Q.equity(HERO, board, None, dead_for(board), ms(budget_ticks), random.Random(18))
        expected = MIN
        while expected * 5 < budget_ticks:
            expected += CHK
        assert n == expected


def river_exact():
    return Q.equity(HERO, RIVER, None, dead_for(RIVER), math.inf, None)


def test_river_fast_machine_is_exact_and_rng_untouched(machine):
    ref = river_exact()
    m = machine(lambda c, i: 1.5)              # 3 us per eval
    rng = random.Random(19)
    state = rng.getstate()
    assert Q.equity(HERO, RIVER, None, dead_for(RIVER), 10.0, rng) == ref
    assert Q.last_path == "exact" and rng.getstate() == state and len(m.calls) == 904


def test_river_slow_machine_samples_within_deadline(machine):
    m = machine(lambda c, i: 10)               # 20 us per eval
    eq, n = Q.equity(HERO, RIVER, None, dead_for(RIVER), 6.0, random.Random(20))
    assert Q.last_path == "iid" and n >= MIN
    assert m.t * TICK * 1000 <= 6.0 + CHK * 0.02 + 1e-9


def iid_mean(seed, pairs, n):
    """Recompute the module's weighted i.i.d. draw for uniform weights."""
    rng = random.Random(seed)
    cum = list(itertools.accumulate([1.0] * len(pairs)))
    hv = eval7(HERO + RIVER)
    acc = 0.0
    for _ in range(n):
        i = min(bisect.bisect_right(cum, rng.random() * cum[-1]), len(pairs) - 1)
        acc += val(hv, eval7(list(pairs[i]) + RIVER))
    return acc / n


def test_river_slowdown_after_calibration_falls_back(machine):
    m = machine(lambda c, i: 1.5 if i <= MIN else 10)   # 3 us for hero + the calibration prefix, then 20 us
    eq, n = Q.equity(HERO, RIVER, None, dead_for(RIVER), 10.0, random.Random(21))
    assert Q.last_path == "fallback" and n == MIN
    assert eq == iid_mean(21, live_pairs(dead_for(RIVER), RIVER), MIN)
    assert m.t * TICK * 1000 <= 10.0 + CHK * 0.02 + MIN * 0.02 + 1e-9


def test_river_deadline_during_calibration_falls_back(machine):
    m = machine(lambda c, i: 10)
    eq, n = Q.equity(HERO, RIVER, None, dead_for(RIVER), 0.5, random.Random(22))
    assert Q.last_path == "fallback" and n == MIN
    assert eq == iid_mean(22, live_pairs(dead_for(RIVER), RIVER), MIN)
    assert m.t * TICK * 1000 <= 0.5 + CHK * 0.02 + MIN * 0.02 + 0.02 + 1e-9


def test_river_small_range_is_exact(machine):
    machine(lambda c, i: 10)
    dead = dead_for(RIVER)
    wmap = {p: 1.0 + (k % 3) for k, p in enumerate(live_pairs(dead, RIVER)[:40])}
    ref = Q.equity(HERO, RIVER, wmap, dead, math.inf, None)
    for budget in (0, 0.01, 10.0):                    # P <= MIN_SAMPLES: always enumerated exactly
        assert Q.equity(HERO, RIVER, wmap, dead, budget, random.Random(23)) == ref and Q.last_path == "exact"


@pytest.mark.parametrize("board", [FLOP, TURN, RIVER])
def test_real_time_budget(board):
    dead = dead_for(board)
    Q.equity(HERO, board, None, dead, 5.0, random.Random(24))          # warm the evaluator memo
    import time
    for seed in range(3):
        t = time.perf_counter()
        Q.equity(HERO, board, None, dead, 5.0, random.Random(seed))
        assert (time.perf_counter() - t) * 1000 <= 5.0 + 3.0


# ------------------------------------------------------------------------- B8: triple samples
def test_triple_samples_exclusion_and_policy_failures():
    dead = dead_mask(HERO3)
    seen = []

    def keep(tri, board):
        seen.append(tuple(tri))
        return tri[1], tri[2]

    samples = Q.deal_triple_samples(FLOP, dead, 5000, random.Random(25), keep)
    blocked = set(HERO3) | set(FLOP)
    for (p, run), tri in zip(samples, seen):
        assert len(set(tri)) == 3 and not blocked & set(tri)
        assert set(p) == {tri[1], tri[2]}
        assert len(run) == 2 and len(set(run)) == 2 and not set(run) & (set(tri) | blocked)

    def boom(tri, board):
        raise RuntimeError

    bad_fns = [boom, lambda t, b: (t[0], t[0]), lambda t, b: (t[0], HERO3[0]), lambda t, b: None,
               lambda t, b: ("As", "Kd")]
    for fn in bad_fns:
        rec = []
        for p, run in Q.deal_triple_samples(FLOP, dead, 300, random.Random(26), lambda t, b: rec.append(t) or fn(t, b)):
            tri = rec.pop(0)
            assert list(p) == sorted(c for c in tri if c != min(tri))     # keeps the two highest


def test_triple_samples_exact_on_river():
    hero = ids("Qs Jd")
    board = ids("Th 9h 2c 7s Kd")
    dead = dead_mask(hero + ids("4c") + board)
    n = 20000

    def keep_top(tri, b):
        return sorted(tri)[1:]

    est = Q.equity_vs_samples(hero, board, Q.deal_triple_samples(board, dead, n, random.Random(27), keep_top))
    rest = [c for c in range(52) if not dead[c]]
    hv = engine.best_hand(strs(hero), strs(board))
    tot = cnt = 0.0
    memo = {}
    for tri in combinations(rest, 3):
        kept = tuple(sorted(tri)[1:])
        if kept not in memo:
            memo[kept] = val(hv, engine.best_hand(strs(kept), strs(board)))
        tot += memo[kept]
        cnt += 1
    assert within_4se(est, tot / cnt, n)


# ------------------------------------------------------------------------- B9: cost-dependent evaluator
def cost_by_value(hero, r_ticks, below_ticks=5):
    """Opponent eval costs `below_ticks` if their hand is below hero's on the same board, else r_ticks."""
    hero = tuple(hero)
    memo = {}

    def cost(cards, i):
        cards = tuple(cards)
        if cards[:2] == hero:
            return 0
        c = memo.get(cards)
        if c is None:
            c = memo[cards] = below_ticks if eval7(cards) < eval7(hero + cards[2:]) else r_ticks
        return c
    return cost


def test_codex_two_pair_case_is_exact_for_every_seed(machine):
    dead = dead_for(RIVER)
    win, lose = split_river(dead, RIVER)
    wmap = {win[0]: 1.0, lose[0]: 1.0}
    for seed in range(500):
        machine(cost_by_value(HERO, 10))
        assert Q.equity(HERO, RIVER, wmap, dead, ms(96 * 5 + 0.5), random.Random(seed)) == (0.5, 2.0)


def range_400():
    dead = dead_for(RIVER)
    win, lose = split_river(dead, RIVER)
    return dead, {p: 1.0 for p in win[:200] + lose[:200]}


def calibration_ticks(wmap, r_ticks):
    pairs = [p for p in PAIRS if p in wmap][:MIN]
    hv = eval7(HERO + RIVER)
    return sum(5 if eval7(list(p) + RIVER) < hv else r_ticks for p in pairs)


def test_river_selection_is_rng_free(machine):
    dead, wmap = range_400()
    cal = calibration_ticks(wmap, 10)
    first = None
    for seed in range(40):
        m = machine(cost_by_value(HERO, 10))
        Q.equity(HERO, RIVER, wmap, dead, ms(cal + 300 * 5 + 0.5), random.Random(seed))
        assert Q.last_path == "iid"
        prefix = m.calls[:1 + MIN]
        assert sum(m.cost(c, 0) for c in prefix) == cal
        first = first or prefix
        assert prefix == first
    for seed in range(40):
        machine(cost_by_value(HERO, 10))
        assert Q.equity(HERO, RIVER, wmap, dead, 1000.0, random.Random(seed))[0] == 0.5
        assert Q.last_path == "exact"


# ---- analytic predictor for the deadline-stopped mean (plan 3.3 Bias)
def _checkpoints():
    n = MIN
    while n < MAX:
        yield n
        n += CHK


def _cont_set(n, c1, c0, B):
    """Range (lo, hi) of K (value-1 count among n samples) for which K*c1 + (n-K)*c0 < B, or None."""
    if c1 == c0:
        return (0, n) if n * c0 < B else None
    if c1 < c0:
        q = (n * c0 - B) / (c0 - c1)                  # continue iff K > q
        lo = max(0, math.floor(q) + 1)
        return (lo, n) if lo <= n else None
    q = (B - n * c0) / (c1 - c0)                      # continue iff K < q
    hi = min(n, math.ceil(q) - 1)
    return (0, hi) if hi >= 0 else None


def _logpmf(n, k, p):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p)


def stopping_mean(c1, c0, p, B):
    """Exact expected value of the deadline-stopped i.i.d. mean (Bernoulli(p) values, value-1 costs c1, value-0 c0)."""
    c1, c0, B = Fraction(c1), Fraction(c0), Fraction(B)
    pf = float(p)
    total = pf
    for n in _checkpoints():
        rng_ = _cont_set(n, c1, c0, B)
        if rng_ is None or rng_ == (0, n):
            continue                                   # P(N > n) is 0 or 1: the term vanishes
        lo, hi = rng_
        sd = math.sqrt(n * pf * (1 - pf))
        w0, w1 = max(lo, int(n * pf - 40 * sd) - 1), min(hi, int(n * pf + 40 * sd) + 1)
        term = sum(math.exp(_logpmf(n, k, pf)) * (pf - k / n) for k in range(w0, w1 + 1))
        total += CHK / (n + CHK) * term
    return total


def stopping_mean_dp(c1, c0, p, B):
    """Brute-force dynamic program over (n, k) (small n only)."""
    c1, c0, B = Fraction(c1), Fraction(c0), Fraction(B)
    dist = {k: math.comb(MIN, k) * p ** k * (1 - p) ** (MIN - k) for k in range(MIN + 1)}
    n, out = MIN, 0.0
    while dist:
        nxt = {}
        for k, pr in dist.items():
            if n >= MAX or k * c1 + (n - k) * c0 >= B:
                out += pr * k / n
            else:
                for j in range(CHK + 1):
                    q = pr * math.comb(CHK, j) * p ** j * (1 - p) ** (CHK - j)
                    nxt[k + j] = nxt.get(k + j, 0.0) + q
        dist, n = nxt, n + CHK
    return out


def support(c1, c0, B):
    c1, c0, B = Fraction(c1), Fraction(c0), Fraction(B)
    lo, hi = min(c1, c0), max(c1, c0)
    return [n for n in _checkpoints() if n * lo < B <= n * hi]


def support_bound(c1, c0, B):
    return sum(8 / ((n + CHK) * math.sqrt(n)) for n in support(c1, c0, B))


def telescoped(c1, c0, B):
    s = support(c1, c0, B)
    return 0.5 * (1 / math.sqrt(s[0]) - 1 / math.sqrt(s[-1] + CHK)) if s else 0.0


def test_stopping_mean_analytic_cases():
    assert MIN == 64 and CHK == 32 and MAX == 20000
    assert abs(stopping_mean(1, Fraction(6, 5), 0.5, Fraction(352, 5)) - 0.4917211038543361) < 1e-12
    assert abs(stopping_mean_dp(1, Fraction(6, 5), 0.5, Fraction(352, 5)) - 0.4917211038543361) < 1e-12
    bias = stopping_mean(1, 3, 0.5, 20000) - 0.5
    assert abs(bias - (-2.4921495e-5)) < 1e-11
    s = support(1, 3, 20000)
    assert s == list(range(6688, 19969, 32)) and len(s) == 416
    assert abs(bias) > 8 / ((6688 + 32) * math.sqrt(6688))       # the per-term cap alone is not a bound
    assert abs(bias) <= support_bound(1, 3, 20000) <= telescoped(1, 3, 20000) + 1e-15
    assert telescoped(1, 3, 20000) == pytest.approx(0.002578415944623744, abs=1e-15)


TRANSITIONS = [(6, 64), (6, 160), (10, 64), (10, 160)]   # (r in ticks: 1.2 or 2 units, checkpoint)


@pytest.mark.parametrize("r_ticks, n", TRANSITIONS)
def test_stopping_mean_vs_dp_at_transitions(r_ticks, n):
    c1, c0 = Fraction(1), Fraction(r_ticks, 5)
    B = n * (c1 + c0) / 2 + Fraction(1, 10)            # half a tick (1 unit = 5 ticks)
    sm = stopping_mean(c1, c0, 0.5, B)
    assert abs(sm - stopping_mean_dp(c1, c0, 0.5, B)) < 1e-12
    assert abs(sm - 0.5) <= support_bound(c1, c0, B) <= telescoped(c1, c0, B) + 1e-15


@pytest.mark.parametrize("r_ticks, n", TRANSITIONS)
def test_river_deadline_bias_matches_prediction(machine, r_ticks, n):
    dead, wmap = range_400()
    w = weights_list(wmap)
    cal = calibration_ticks(wmap, r_ticks)
    B_units = n * (1 + Fraction(r_ticks, 5)) / 2 + Fraction(1, 10)
    budget = ms(cal + float(B_units * 5))
    ests = []
    for seed in range(3000):
        machine(cost_by_value(HERO, r_ticks))
        e, cnt = Q.equity(HERO, RIVER, w, dead, budget, random.Random(seed))
        assert Q.last_path == "iid"
        ests.append(e)
    mean = sum(ests) / len(ests)
    sd = math.sqrt(sum((e - mean) ** 2 for e in ests) / (len(ests) - 1))
    assert abs(mean - stopping_mean(1, Fraction(r_ticks, 5), 0.5, B_units)) <= 4 * sd / math.sqrt(len(ests))


@pytest.mark.parametrize("n", [64, 160])
def test_turn_deadline_bias_within_bound(machine, n):
    dead = dead_for(TURN)
    wmap = three_pair_range(TURN)
    w = weights_list(wmap)
    exact = exact_runouts(HERO, TURN, dead, wmap)
    B_units = n * Fraction(3, 2) + Fraction(1, 10)      # costs 1 and 2 units
    ests = []
    for seed in range(3000):
        machine(cost_by_value(HERO, 10))
        ests.append(Q.equity(HERO, TURN, w, dead, ms(float(B_units * 5)), random.Random(seed))[0])
    mean = sum(ests) / len(ests)
    sd = math.sqrt(sum((e - mean) ** 2 for e in ests) / (len(ests) - 1))
    assert abs(mean - exact) <= 4 * sd / math.sqrt(len(ests)) + telescoped(1, 2, B_units)


# ------------------------------------------------------------------------- D: canon3
def min_perm_key(tri):
    return min(tuple(sorted((c >> 2) * 4 + perm[c & 3] for c in tri)) for perm in itertools.permutations(range(4)))


def test_canon3_classes():
    classes = {}
    by_key = {}
    for tri in combinations(range(52), 3):
        k = Q.canon3(tri)
        classes[k] = classes.get(k, 0) + 1
        mk = min_perm_key(tri)
        assert by_key.setdefault(mk, k) == k          # same orbit -> same index
    assert sorted(classes) == list(range(1755)) and sum(classes.values()) == 22100
    assert len(by_key) == 1755 and len(set(by_key.values())) == 1755   # bijection with the 24-permutation orbits
    keys = Q._all_keys()
    assert sum(1 for k in keys if k[0] == 0) == 1430 and sum(1 for k in keys if k[0] == 1) == 312 \
        and sum(1 for k in keys if k[0] == 2) == 13


def test_canon3_invariance_and_pins():
    rng = random.Random(28)
    for _ in range(2000):
        tri = rng.sample(range(52), 3)
        k = Q.canon3(tri)
        for perm in itertools.permutations(range(4)):
            moved = [(c >> 2) * 4 + perm[c & 3] for c in tri]
            for order in itertools.permutations(moved):
                assert Q.canon3(order) == k
    assert Q.canon3(["2s", "3s", "4s"]) == PIN_234S
    assert Q.canon3(["As", "Ah", "Ad"]) == PIN_AAA
    assert Q.canon3(["Ks", "Kh", "2s"]) == PIN_KK2S
    assert Q.canon3(["As", "Ah", "Ks"]) == Q.canon3(["Ah", "As", "Kh"]) != Q.canon3(["As", "Ah", "Kd"])


PIN_234S = 0        # (0, 2, 1, 0, all suited): the smallest key
PIN_AAA = 1754      # (2, A): the largest key
PIN_KK2S = 1695     # (1, K, 2, kicker suited with a pair card)
