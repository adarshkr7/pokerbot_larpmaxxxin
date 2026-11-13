"""The discard (strategies/03_discard.md D1, D3, D5; W3). Every random draw is seeded."""
import math
import os
import random
import time
from itertools import combinations

import numpy as np
import pytest

import discard as D
import equity as Q
import params
from brain import Brain
from cards import PAIRS, dead_mask, fmt, pair_index, parse
from engine_util import BOT, RANDOM_BOT, STARTER, TESTS, assert_clean, engine, run_match
from evaluator import eval7

INF = float("inf")


def ids(s):
    return [parse(x) for x in s.split()]


def base(pair, flop):
    """category + kicker fraction: S without any bonus."""
    v = eval7(tuple(pair) + tuple(flop))
    return (v >> 20) + (v & 0xFFFFF) / 2 ** 20


def bonus(pair, flop):
    return D.flop_score(ids(pair) if isinstance(pair, str) else pair, ids(flop)) - base(
        ids(pair) if isinstance(pair, str) else pair, ids(flop))


def toss_lowest(hole3):
    return min(hole3)            # id order = rank, then s < h < d < c = engine.default_discard


# ----------------------------------------------------------------------------------------------- flop_score S
def test_flop_score_orders_categories():
    flop = ids("Kd 7c 2h")
    trips, two_pair, pair, high = ids("Ks Kh"), ids("Ks 7s"), ids("Ks 4h"), ids("Qs 9h")
    assert D.flop_score(trips, flop) > D.flop_score(two_pair, flop) > D.flop_score(pair, flop) > D.flop_score(high, flop)
    assert 3 <= D.flop_score(trips, flop) < 4 and 2 <= D.flop_score(two_pair, flop) < 3
    assert D.flop_score(ids("Ks As"), flop) > D.flop_score(ids("Ks 4h"), flop)     # kicker counts


@pytest.mark.parametrize("pair, flop, want", [
    ("As Ks", "9s 4s 2d", params.S_FLUSH_DRAW + 2 * params.S_OVERCARD),       # nut flush draw + 2 overcards
    ("6h 5d", "8c 7s Kh", params.S_OPEN_ENDED),                                # 4 or 9
    ("9h 5d", "8c 7s Kh", params.S_GUTSHOT),                                   # only a 6
    ("Ah Kd", "9c 5s 2h", 2 * params.S_OVERCARD),                              # two overcards, no draw
    ("Ah 2d", "3c 4s 9h", params.S_GUTSHOT + params.S_OVERCARD),               # wheel draw: only a 5
    ("Jh Qd", "Kc As 9h", params.S_GUTSHOT),                                   # Broadway needs a T: one-ended
    ("9h 7d", "6c 5s 3h", params.S_OPEN_ENDED + 2 * params.S_OVERCARD),        # double gutshot (8 or 4) counts
    ("Th 9h", "8h 7h 2c", params.S_FLUSH_DRAW + params.S_OPEN_ENDED + 2 * params.S_OVERCARD),
    ("Ah Kc", "Kd 7c 2h", params.S_OVERCARD),                                  # made pair keeps its bonuses
    ("3s 2h", "Kd 7c 9h", 0.0),
])
def test_flop_score_draw_bonuses(pair, flop, want):
    assert bonus(pair, flop) == pytest.approx(want)


@pytest.mark.parametrize("pair, flop", [
    ("9h 8d", "7c 6s 5h"),        # straight (no OESD bonus on a made straight)
    ("9h 8h", "7h 6h 5c"),        # straight + 4 hearts: still no flush-draw bonus
    ("Ah Kh", "9h 4h 2h"),        # flush
    ("7s 7h", "7d 2c 2h"),        # full house
])
def test_no_draw_bonus_at_straight_or_better(pair, flop):
    assert D.flop_score(ids(pair), ids(flop)) >= 4
    assert bonus(pair, flop) == 0.0
    assert D.draw_potential(ids(pair), ids(flop)) == 0.0


def test_flop_score_total_on_all_pairs_of_a_flop():
    flop = ids("Jd Tc 2s")
    for a, b in combinations([c for c in range(52) if c not in flop], 2):
        s = D.flop_score((a, b), flop)
        assert math.isfinite(s) and 0.0 <= s < 9.0
        assert D.flop_score((b, a), flop) == s


# ----------------------------------------------------------------------------------------------- opponent policy
def test_opp_policy_keeps_max_s_pair_and_ignores_card_order():
    rng = random.Random(3)
    for _ in range(300):
        cards = rng.sample(range(52), 6)
        tri, flop = cards[:3], cards[3:]
        d = D.opp_discard_policy(tri, flop)
        assert d in tri
        kept = [c for c in tri if c != d]
        s_kept = D.flop_score(kept, flop)
        for x in tri:
            assert s_kept >= D.flop_score([c for c in tri if c != x], flop)
        for perm in ([tri[2], tri[0], tri[1]], [tri[1], tri[2], tri[0]], tuple(reversed(tri))):
            assert D.opp_discard_policy(perm, flop) == d


def test_opp_policy_uses_only_its_cards_and_the_flop():
    import inspect
    assert list(inspect.signature(D.opp_discard_policy).parameters) == ["triple3", "flop"]
    # Pure: the same (triple, flop) gives the same discard whatever else was evaluated in between.
    tri, flop = ids("As Ks Qd"), ids("Jd Tc 2s")
    first = D.opp_discard_policy(tri, flop)
    D.choose_discard(ids("9c 9d 3h"), flop, None, None, INF, random.Random(1), max_samples=200)
    assert D.opp_discard_policy(tri, flop) == first == parse("As")


def test_inline_policy_in_the_sampler_matches_opp_discard_policy():
    """The sampler's cached inline policy and the public function give identical results on the same samples."""
    hole, flop = ids("As Ks Qd"), ids("9s 4s 2d")
    D.choose_discard(hole, flop, None, None, INF, random.Random(7), max_samples=1500)
    inline = D.last_info["eq"]
    D.choose_discard(hole, flop, {"discard_policy": D.opp_discard_policy}, None, INF, random.Random(7),
                     max_samples=1500)
    assert D.last_info["eq"] == inline


# ----------------------------------------------------------------------------------------------- D1 worked examples
@pytest.mark.parametrize("hole, flop, toss, n", [
    ("As Ks Qd", "Jd Tc 2s", "As", 8000),     # KQ 53.0 / AK 50.3 / AQ 47.3: needs >= 4,000 samples
    ("As Ks Qd", "9s 4s 2d", "Qd", 600),      # keep the nut flush draw
    ("Ad Qd 9c", "As 9h 4c", "Qd", 600),      # keep two pair
])
@pytest.mark.parametrize("betting", [True, False])
def test_worked_examples(hole, flop, toss, n, betting):
    h, f = ids(hole), ids(flop)
    dead = dead_mask(h + f)
    got = D.choose_discard(h, f, None, dead, INF, random.Random(11), betting_possible=betting, max_samples=n)
    assert fmt(got) == toss, D.last_info
    assert D.last_info["path"] == "mc" and D.last_info["n"] == n


def test_worked_examples_equities_match_the_strategy_file():
    """Our numbers vs the file's (40k samples, best-made-hand opponent); our opponent also values draws, which
    costs us about a point, so the tolerance is 2.5 points."""
    cases = [("As Ks Qd", "Jd Tc 2s", {"Qd": 0.503, "As": 0.530, "Ks": 0.473}),
             ("As Ks Qd", "9s 4s 2d", {"Qd": 0.644, "As": 0.389, "Ks": 0.432}),
             ("Ad Qd 9c", "As 9h 4c", {"Qd": 0.925, "Ad": 0.686, "9c": 0.847})]
    for hole, flop, want in cases:
        D.choose_discard(ids(hole), ids(flop), None, None, INF, random.Random(5), max_samples=8000)
        got = {fmt(d): e for d, e in zip(D.last_info["discards"], D.last_info["eq"])}
        for card, eq in want.items():
            assert abs(got[card] - eq) < 0.025, (hole, flop, got)


# ----------------------------------------------------------------------------------------------- D1 vs exact
def _exact_keep_equities(hole, flop, dead):
    """Exact enumeration with the ENGINE's evaluator: every opponent triple from the live cards (discarding by
    opp_discard_policy), every 2-card runout of the rest."""
    s = lambda cs: [fmt(c) for c in cs]
    live = [c for c in range(52) if c not in dead and c not in hole and c not in flop]
    keeps = {d: [c for c in hole if c != d] for d in hole}
    acc = {d: 0.0 for d in hole}
    n = 0
    hero_cache = {}
    for tri in combinations(live, 3):
        dv = D.opp_discard_policy(tri, flop)
        opp = [c for c in tri if c != dv]
        rest = [c for c in live if c not in tri]
        for run in combinations(rest, 2):
            board = s(list(flop) + list(run))
            ov = engine.best_hand(s(opp), board)
            for d, k in keeps.items():
                key = (d, run)
                hv = hero_cache.get(key)
                if hv is None:
                    hv = hero_cache[key] = engine.best_hand(s(k), board)
                acc[d] += 1.0 if hv > ov else (0.5 if hv == ov else 0.0)
            n += 1
    return {d: a / n for d, a in acc.items()}


@pytest.mark.parametrize("hole, flop, live", [
    ("As Ks Qd", "9s 4s 2d", "5s 7s Jh Jc Th 8d 3c 2h 6h 4d"),
    ("Ad Qd 9c", "As 9h 4c", "Kh Qs Qc 9s 5d 6c 7h 8s 2c 3d"),
    ("Th 9h 3c", "8h 7d 2s", "Ah Jh 6c 6d 3s 2d Kc Qc 4h 5s"),
])
def test_choose_discard_matches_exact_enumeration(hole, flop, live):
    h, f, lv = ids(hole), ids(flop), ids(live)
    dead = [c for c in range(52) if c not in lv]                    # a 10-card deck makes enumeration cheap
    exact = _exact_keep_equities(h, f, set(dead) - set(h) - set(f))
    got = D.choose_discard(h, f, None, dead_mask(dead), INF, random.Random(2), betting_possible=False,
                           max_samples=20000)
    mc = dict(zip(D.last_info["discards"], D.last_info["eq"]))
    for d in h:
        assert abs(mc[d] - exact[d]) < 0.015, (fmt(d), mc, exact)
    ranked = sorted(exact.values(), reverse=True)
    if ranked[0] - ranked[1] > 0.03:
        assert exact[got] == ranked[0], (fmt(got), exact)


def test_beats_toss_lowest_on_random_spots():
    """Average equity (judged on independent samples through equity.deal_triple_samples) of our keep vs the
    toss-lowest keep, against the same simulated opponents, over 100 random (hole3, flop) spots."""
    rng = random.Random(2026)
    judge_rng = random.Random(99)
    memo = {}

    def keep_fn(tri, bd):
        key = (tuple(sorted(tri)), tuple(bd))
        if key not in memo:
            memo[key] = tuple(c for c in tri if c != D.opp_discard_policy(tri, bd))
        return memo[key]
    diffs, best_possible = [], []
    for _ in range(100):
        cards = rng.sample(range(52), 6)
        hole, flop = cards[:3], cards[3:]
        dead = dead_mask(hole + flop)
        ours = D.choose_discard(hole, flop, None, dead, INF, rng, betting_possible=False, max_samples=500)
        samples = Q.deal_triple_samples(flop, dead, 1000, judge_rng, keep_fn)
        eq = {d: Q.equity_vs_samples([c for c in hole if c != d], flop, samples) for d in hole}
        diffs.append(eq[ours] - eq[toss_lowest(hole)])
        best_possible.append(max(eq.values()) - eq[toss_lowest(hole)])
    mean = sum(diffs) / len(diffs)
    se = (sum((x - mean) ** 2 for x in diffs) / (len(diffs) - 1) / len(diffs)) ** 0.5
    assert mean > 0.02 and mean > 5 * se, (mean, se)
    assert mean > 0.8 * (sum(best_possible) / len(best_possible))    # we capture most of the available edge


# ----------------------------------------------------------------------------------------------- budget / fallbacks
def static_discard(hole, flop):
    s = {d: D.flop_score([c for c in hole if c != d], flop) for d in hole}
    top = max(s.values())
    return min(d for d in hole if s[d] == top)


@pytest.mark.parametrize("budget", [0, 0.0, -5, float("nan"), None, "abc", True])
def test_zero_budget_is_the_max_s_keep(budget):
    rng = random.Random(4)
    for _ in range(100):
        cards = rng.sample(range(52), 6)
        hole, flop = cards[:3], cards[3:]
        assert D.choose_discard(hole, flop, None, None, budget, rng) == static_discard(hole, flop)
        assert D.last_info["path"] == "static" and D.last_info["n"] == 0


def test_static_choice_on_worked_examples_beats_toss_lowest():
    assert fmt(static_discard(ids("As Ks Qd"), ids("Jd Tc 2s"))) == "As"
    assert fmt(static_discard(ids("As Ks Qd"), ids("9s 4s 2d"))) == "Qd"
    assert fmt(static_discard(ids("Ad Qd 9c"), ids("As 9h 4c"))) == "Qd"


def test_expired_clock_returns_max_s_keep_after_one_block(monkeypatch):
    t = [0.0]

    def fake_now():
        t[0] += 0.010                     # every clock read: +10 ms
        return t[0]
    monkeypatch.setattr(D, "_now", fake_now)
    hole, flop = ids("As Ks Qd"), ids("Jd Tc 2s")
    got = D.choose_discard(hole, flop, None, None, 5.0, random.Random(1))
    assert got == static_discard(hole, flop)
    assert D.last_info["path"] == "static" and D.last_info["n"] == params.DISCARD_CHECK_EVERY


def test_respects_a_real_budget():
    hole, flop = ids("As Ks Qd"), ids("Jd Tc 2s")
    for budget in (3.0, 15.0, 40.0):
        t = time.perf_counter()
        D.choose_discard(hole, flop, None, None, budget, random.Random(1), max_samples=10 ** 6)
        ms = (time.perf_counter() - t) * 1000
        assert ms < budget + 10.0, (budget, ms)
        assert D.last_info["n"] < 10 ** 6


def test_sample_cap_and_all_in_cap():
    hole, flop = ids("As Ks Qd"), ids("Jd Tc 2s")
    D.choose_discard(hole, flop, None, None, INF, random.Random(1))
    assert D.last_info["n"] == params.DISCARD_MAX_SAMPLES
    D.choose_discard(hole, flop, None, None, INF, random.Random(1), betting_possible=False)
    assert D.last_info["n"] == params.DISCARD_ALLIN_MAX_SAMPLES


@pytest.mark.parametrize("hole, flop", [
    ([1, 2], [3, 4, 5]), ([1, 2, 2], [3, 4, 5]), ([1, 2, 3], [3, 4, 5]), ([1, 2, 60], [3, 4, 5]),
    (["As", "Kd", "7c"], [3, 4, 5]), (None, None), ([1, 2, 3], None), ([1, 2, 3], [4, 5]),
])
def test_invalid_input_never_raises(hole, flop):
    got = D.choose_discard(hole, flop, None, None, 10.0, random.Random(1))
    assert isinstance(got, int)


def test_failing_opponent_model_and_internal_error_fall_back(monkeypatch):
    hole, flop = ids("As Ks Qd"), ids("9s 4s 2d")
    bad = {"triple_weight": lambda t, f: float("nan"), "discard_policy": lambda t, f: 1 / 0}
    assert D.choose_discard(hole, flop, bad, None, INF, random.Random(1), max_samples=300) == static_discard(hole,
                                                                                                           flop)
    monkeypatch.setattr(D, "_simulate", lambda *a, **k: 1 / 0)
    assert D.choose_discard(hole, flop, None, None, 50.0, random.Random(1)) == static_discard(hole, flop)
    assert D.last_info["path"] == "error"


def test_opponent_weights_reweight_the_samples():
    """A D2 plug-in: an opponent range of only triples holding a nine (top pair on 9-4-2) hurts our unpaired
    flush-draw keep; a constant weight changes nothing (same samples)."""
    hole, flop = ids("As Ks Qd"), ids("9s 4s 2d")
    D.choose_discard(hole, flop, None, None, INF, random.Random(3), max_samples=3000)
    uniform = D.last_info["eq"]
    D.choose_discard(hole, flop, {"triple_weight": lambda t, f: 2.5}, None, INF, random.Random(3), max_samples=3000)
    assert D.last_info["eq"] == pytest.approx(uniform)
    nines = {"triple_weight": lambda t, f: 1.0 if any(c >> 2 == 7 for c in t) else 0.0}
    D.choose_discard(hole, flop, nines, None, INF, random.Random(3), max_samples=3000)
    weighted = dict(zip(D.last_info["discards"], D.last_info["eq"]))
    assert weighted[parse("Qd")] < dict(zip(D.last_info["discards"], uniform))[parse("Qd")] - 0.05


def test_tie_break_prefers_draw_only_when_betting(monkeypatch):
    """Keeps within the margin: with betting the drawier keep wins; all-in the plain max."""
    hole, flop = ids("As Ks Qd"), ids("Jd Tc 2s")     # discards in id order: Qd, Ks, As
    keeps = {d: [c for c in hole if c != d] for d in hole}
    pots = {d: D.draw_potential(keeps[d], flop) for d in hole}
    assert pots[parse("As")] > pots[parse("Qd")]       # KQ (open-ended) is drawier than AK (gutshot)
    fake = (0.505, 0.40, 0.500)                          # keep AK (discard Qd) 0.5 pt above KQ (discard As)
    monkeypatch.setattr(D, "_simulate", lambda *a, **k: (fake, 500))
    assert fmt(D.choose_discard(hole, flop, None, None, 50.0, random.Random(1), betting_possible=True)) == "As"
    assert fmt(D.choose_discard(hole, flop, None, None, 50.0, random.Random(1), betting_possible=False)) == "Qd"
    monkeypatch.setattr(D, "_simulate", lambda *a, **k: ((0.53, 0.40, 0.500), 500))     # 3 points apart
    assert fmt(D.choose_discard(hole, flop, None, None, 50.0, random.Random(1), betting_possible=True)) == "Qd"


# ----------------------------------------------------------------------------------------------- Brain wiring
def _brain_discard(hole, board, time_left, my_stack=180, opp_stack=180):
    b = Brain()
    b.on_init({"total_hands": 200, "time_bank_ms": 30000, "per_response_ms": 5000})
    b.on_new_hand({"hand_id": 5, "seat": "button", "hole_cards": hole})
    return b.discard({"type": "discard_request", "hand_id": 5, "hole_cards": hole, "board": board, "pot": 40,
                      "my_stack": my_stack, "opp_stack": opp_stack, "time_left_ms": time_left})


def test_brain_uses_equity_discard():
    assert _brain_discard(["As", "Ks", "Qd"], ["9s", "4s", "2d"], 30000) == {"type": "discard", "card": "Qd"}
    assert _brain_discard(["Ad", "Qd", "9c"], ["As", "9h", "4c"], 30000, 0, 0) == {"type": "discard", "card": "Qd"}


def test_brain_panic_tier_uses_static_keep():
    reply = _brain_discard(["As", "Ks", "Qd"], ["Jd", "Tc", "2s"], 0)
    assert reply == {"type": "discard", "card": "As"} and D.last_info["path"] == "static"


def test_brain_malformed_requests_fall_back_to_v0():
    assert _brain_discard(["As", "Ks"], ["Jd", "Tc", "2s"], 30000)["card"] in ("As", "Ks")
    assert _brain_discard(["As", "Ks", "Qd"], ["Jd", "Tc"], 30000)["card"] == "Qd"        # v0: lowest rank
    assert _brain_discard(["As", "Ks", "Qd"], ["As", "Tc", "2s"], 30000)["card"] in ("As", "Ks", "Qd")


# ----------------------------------------------------------------------------------------------- D3 posterior
HOLE3 = ids("9c 9d 3h")
FLOP = ids("Ks 7d 2c")


def post(d_v, **kw):
    dead = dead_mask(HOLE3 + FLOP + [parse(d_v)])
    return D.posterior_after_discard(parse(d_v), FLOP, dead=dead, **kw)


def valid_idx(d_v):
    dead = set(HOLE3 + FLOP + [parse(d_v)])
    return [i for i, (a, b) in enumerate(PAIRS) if a not in dead and b not in dead]


def check_distribution(w, d_v):
    w = np.asarray(w)
    assert w.shape == (1326,) and np.all(np.isfinite(w)) and np.all(w >= 0)
    v = valid_idx(d_v)
    assert len(v) == 990
    assert w[v].sum() == pytest.approx(1.0)
    mask = np.ones(1326, bool)
    mask[v] = False
    assert np.all(w[mask] == 0.0)                     # every pair touching a dead card / the board / d_v
    assert w[v].min() >= params.POSTERIOR_SMOOTH / 990 * (1 - 1e-9)


@pytest.mark.parametrize("kw", [{}, {"beta": 0}, {"beta": 12.0}, {"toss_lowest": True}])
def test_posterior_is_a_distribution_over_valid_pairs(kw):
    check_distribution(post("As", **kw), "As")


def test_posterior_uniform_with_beta_zero_and_no_prior():
    w = post("Qh", beta=0)
    assert np.allclose(w[valid_idx("Qh")], 1 / 990)


def test_posterior_shifts_toward_kept_strength():
    """They tossed an ace on K-7-2: keeping two cards over the ace is rational with trips, irrational with 6-5
    (A-high beats K-high). Within one category the kicker term of S is small, so beta 4 gives a factor of ~4."""
    w = post("As", beta=4.0)
    kk = w[pair_index(parse("Kh"), parse("Kd"))]
    assert kk > 3 * w[pair_index(parse("6d"), parse("5h"))]
    pairs_kept = [i for i in valid_idx("As") if eval7(PAIRS[i] + tuple(FLOP)) >> 20 >= 1]
    assert w[pairs_kept].sum() > 0.55 > len(pairs_kept) / 990
    assert w[pairs_kept].sum() > post("As", beta=0)[pairs_kept].sum() + 0.15


def test_posterior_toss_lowest_ace_means_two_aces():
    """Toss-lowest opponent who tossed the A-spade (the lowest-id ace) can only have kept two other aces."""
    w = post("As", toss_lowest=True, eta=0.1)
    aa = [pair_index(a, b) for a, b in combinations(ids("Ah Ad Ac"), 2)]
    others = [i for i in valid_idx("As") if i not in aa]
    assert min(w[aa]) > 20 * max(w[others])
    noise = 0.1 / 3
    q_aa = (0.9 + noise) / (3 * (0.9 + noise) + 987 * noise)
    assert w[aa[0]] == pytest.approx(0.98 * q_aa + 0.02 / 990)
    # A low card tossed under toss-lowest: every pair with a card ranked below it (or equal, lower suit) is noise.
    w5 = post("5h", toss_lowest=True, eta=0.1)
    hi = [i for i in valid_idx("5h") if min(PAIRS[i]) > parse("5h")]
    assert w5[hi].sum() > 0.9


@pytest.mark.parametrize("beta", [1e9, -1e9, INF, -INF, float("nan"), 1e308, "x", None])
def test_posterior_extreme_beta_never_nan(beta):
    check_distribution(post("As", beta=beta), "As")


def test_posterior_zero_or_garbage_priors():
    z = post("As", prior=np.zeros(1755), beta=4.0)
    check_distribution(z, "As")
    assert np.allclose(z[valid_idx("As")], 1 / 990)          # raw products all 0 -> uniform q (D3 smoothing rule)
    check_distribution(post("As", prior=[float("nan")] * 1755), "As")
    check_distribution(post("As", prior=[1.0] * 7), "As")    # wrong length: ignored
    check_distribution(post("As", prior=lambda t: -1.0), "As")
    check_distribution(post("As", flop_action=lambda s: 0.0), "As")
    w = post("As", flop_action=lambda s: 1 / 0)               # a raising plug-in: uniform fallback, still valid
    check_distribution(w, "As")


def test_class_multiplicities():
    """MULT from the class keys vs a count of all C(52, 3) physical triples by canon3."""
    counts = [0] * 1755
    for t in combinations(range(52), 3):
        counts[Q.canon3(t)] += 1
    assert counts == [int(m) for m in D.MULT]
    assert sum(counts) == 22100 and set(counts) == {4, 12, 24}


def test_prior_class_mass_is_divided_by_multiplicity():
    """Equal mass per class (beta 0): a physical triple of a 24-triple class weighs 1/6 of one of a 4-triple class."""
    w = post("As", prior=np.ones(1755), beta=0.0)
    mono = pair_index(parse("Qs"), parse("Js"))       # Qs Js As: monotone, m = 4
    rainbow = pair_index(parse("Qh"), parse("Jd"))    # Qh Jd As: rainbow, m = 24
    raw_ratio = (w[mono] - 0.02 / 990) / (w[rainbow] - 0.02 / 990)
    assert raw_ratio == pytest.approx(6.0)
    # The callable form gets per-physical-triple weights directly.
    w2 = post("As", prior=lambda t: 1.0 / D.MULT[Q.canon3(t)], beta=0.0)
    assert np.allclose(w, w2)


def test_flop_action_term_uses_s_best_of_the_triple():
    """A bettor model that needs at least a pair in the triple: pairs whose whole triple is unpaired get only
    the smoothing mass."""
    w = post("As", beta=0.0, flop_action=lambda s: 1.0 if s >= 1.0 else 0.0)
    for i in valid_idx("As"):
        a, b = PAIRS[i]
        s_best = max(D.flop_score((a, b), FLOP), D.flop_score((a, parse("As")), FLOP),
                     D.flop_score((b, parse("As")), FLOP))
        if s_best < 1.0:
            assert w[i] == pytest.approx(0.02 / 990)


def test_posterior_feeds_equity():
    w = post("As")
    eq, n = Q.equity(ids("9c 9d"), FLOP, opp_weights=w, dead=dead_mask(HOLE3 + FLOP + ids("As")), budget_ms=0,
                     rng=random.Random(1))
    assert 0.0 <= eq <= 1.0 and n == params.MIN_SAMPLES


def test_posterior_on_the_river_excludes_turn_and_river():
    board = FLOP + ids("5h 6h")
    dead = dead_mask(HOLE3 + board + ids("As"))
    w = D.posterior_after_discard(parse("As"), board, dead=dead)
    live = [c for c in range(52) if not dead[c]]
    assert len(live) == 43
    assert np.count_nonzero(w) == 43 * 42 // 2 and w.sum() == pytest.approx(1.0)


@pytest.mark.parametrize("d_v", [None, -1, 52, "As", True])
def test_posterior_bad_discard_is_uniform(d_v):
    w = D.posterior_after_discard(d_v, FLOP, dead=dead_mask(HOLE3 + FLOP))
    assert np.all(np.isfinite(w)) and w.sum() == pytest.approx(1.0)
    nz = w[w > 0]
    assert np.allclose(nz, nz[0])


# ----------------------------------------------------------------------------------------------- engine
@pytest.mark.parametrize("opp", ["random", "starter", "shove"])
def test_engine_match_has_no_notices(tmp_path, opp):
    path = {"random": RANDOM_BOT, "starter": STARTER, "shove": TESTS / "shove_bot.py"}[opp]
    if opp == "shove":
        # Our preflop (W4) folds most hands to a shove; to exercise the all-in discard on most hands, preflop is
        # swapped back to v0's call-everything here (tests/patched_bot.py, mode v0_preflop). The discard is ours.
        env = dict(os.environ, PATCH_MODE="v0_preflop")
        out, res = run_match(TESTS / "patched_bot.py", path, seed=21, log_dir=tmp_path, hands=100, env=env)
    else:
        out, res = run_match(BOT, path, seed=21, log_dir=tmp_path, hands=100)
    assert_clean(out, res)
    log = (tmp_path / "match.log").read_text(encoding="utf-8")
    assert "discards" in log
    if opp == "shove":
        # The shover goes all-in preflop and we call: every discard happens with both players all-in.
        hands = [line for line in log.splitlines() if " discards " in line]
        assert len(hands) >= 75, log[:2000]
