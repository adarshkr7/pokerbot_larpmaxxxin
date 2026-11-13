"""Postflop betting (strategies/05_postflop_betting.md B1-B7, B8b hooks; W5). Every random draw is seeded."""
import math
import random
import re

import numpy as np
import pytest

import betting as B
import discard as D
import equity as EQ
import legal
import params
import preflop as P
from brain import Brain
from cards import PAIRS, dead_mask, fmt, parse
from engine_util import BOT, RANDOM_BOT, STARTER, TESTS, assert_clean, run_match
from evaluator import eval7
from opponent import OppModel
from state import HandState

INF = float("inf")


def ids(s):
    return [parse(x) for x in s.split()]


class Clock:
    def __init__(self, budget=5.0, tier="normal"):
        self.b, self.t = budget, tier

    def budget_ms(self, kind):
        return self.b

    def tier(self):
        return self.t


class Opp(OppModel):
    """The neutral stub with chosen stats / archetype weights."""

    def __init__(self, arch=None, **st):
        self.arch = arch or {"neutral": 1.0}
        self.st = st

    def stat(self, name):
        return self.st.get(name, super().stat(name))

    def archetype_weights(self):
        return dict(self.arch)


PRE = [{"street": "preflop", "actor": "me", "action": "raise", "amount": 6},
       {"street": "preflop", "actor": "opp", "action": "call", "amount": 6}]


def req_(street, board, pot, my_bet=0, opp_bet=0, my_stack=None, opp_stack=None, raises_left=4, history=None,
         last_raise=None, legal_actions=None):
    """An action_request built by the rules of starter_kit/engine.py::Hand.betting_round."""
    to_call = opp_bet - my_bet
    committed = (pot - my_bet - opp_bet) // 2
    my_stack = 200 - committed - my_bet if my_stack is None else my_stack
    opp_stack = 200 - committed - opp_bet if opp_stack is None else opp_stack
    max_raise = min(my_bet + my_stack, opp_bet + opp_stack)
    legal_ = ["fold", "call"] if to_call > 0 else ["check"]
    can_raise = raises_left > 0 and max_raise > opp_bet
    if can_raise:
        legal_.append("raise")
    r = {"type": "action_request", "hand_id": 1, "street": street, "board": board, "pot": pot, "my_bet": my_bet,
         "opp_bet": opp_bet, "to_call": to_call, "my_stack": my_stack, "opp_stack": opp_stack,
         "legal_actions": legal_actions if legal_actions is not None else legal_, "raises_left": raises_left,
         "history": list(PRE) + list(history or [])}
    if can_raise:
        lr = last_raise if last_raise is not None else to_call
        r["min_raise"] = min(opp_bet + max(lr, 2), max_raise)
        r["max_raise"] = max_raise
    return r


def hand_(hole3, board, seat="big_blind", keep=None, opp_discard=None, hid=1):
    h = HandState(hid, seat, hole3.split())
    h.board = ids(board)
    if keep is not None:
        h.update_from_discard_result({"my_discard": [c for c in hole3.split() if c not in keep.split()][0],
                                      "opp_discard": opp_discard, "hole_cards": keep.split()})
    h.rebuild_dead()
    return h


def spot(r):
    return P._Spot(r)


def fake_equity(monkeypatch, e, ec=None):
    res = (e, e if ec is None else ec, 500, "mc")
    monkeypatch.setattr(B, "_flop_equity", lambda *a, **k: res)
    monkeypatch.setattr(B, "_turn_river_equity", lambda *a, **k: res)


@pytest.fixture(autouse=True)
def fresh_cache():
    B._HC.clear()
    B._HC["key"] = None
    yield


# ----------------------------------------------------------------------------------------------- B3 arithmetic
def test_opening_bet_sizes():
    r = req_("flop", ["2c", "7d", "9h"], pot=20)
    s = spot(r)
    assert (s.lo, s.hi) == (2, 190)
    for f, want in ((1 / 3, 7), (2 / 3, 13), (1.0, 20)):           # my_bet + round(f * pot)
        got = B.bet_amount(s, f)
        assert got == want and isinstance(got, int)


def test_raise_over_a_bet_calls_first_then_raises_by_f_of_the_new_pot():
    # pot 30 holds their bet of 10; after our call the pot is 40; 2/3 of that on top of their 10 -> 37
    r = req_("turn", ["2c", "7d", "9h", "Ks"], pot=30, opp_bet=10)
    s = spot(r)
    assert B.bet_amount(s, 2 / 3) == 10 + round(2 / 3 * 40) == 37
    assert B.bet_amount(s, 2 / 3) != 10 + round(2 / 3 * 30)        # the under-sized opp_bet + f * pot
    assert B.bet_amount(s, 1.0) == 50
    assert B.bet_amount(s, 1 / 3) == 10 + 13


def test_clamping_and_shove_snap():
    r = req_("flop", ["2c", "7d", "9h"], pot=20)
    s = spot(r)
    assert B.bet_amount(s, 0.0) == s.lo                              # below min_raise -> min_raise
    assert B.bet_amount(s, 50.0) == s.hi                             # above max_raise -> max_raise
    # 100 in the pot, 90 behind each: a 2/3 bet (67) would leave 23 < 1/3 of the 234 pot after a call -> shove
    r = req_("turn", ["2c", "7d", "9h", "Ks"], pot=100, my_stack=90, opp_stack=90)
    s = spot(r)
    assert s.hi == 90
    assert B.bet_amount(s, 2 / 3) == 90
    assert B.bet_amount(s, 1 / 3) == 33                              # 57 behind >= 1/3 of 166: no snap
    assert B.bet_amount(s, 1 / 3, spr_shove=1.0) == 90               # ... but SPR <= 1 for strong value
    for f in (0.1, 0.33, 0.5, 0.67, 1.0, 1.5, 3.0):
        a = B.bet_amount(s, f)
        assert isinstance(a, int) and s.lo <= a <= s.hi


# ----------------------------------------------------------------------------------------------- B1
def test_calling_rule_formula():
    # pot already holds their bet: price = to_call / (pot + to_call)
    assert B.calls(0.26, 10, 30, "river", False, True)               # 0.26 > 10 / 40
    assert not B.calls(0.24, 10, 30, "river", False, True)
    # flop / turn: R_pos and the margin; out of position needs more
    assert B.calls(0.27, 10, 30, "flop", True, False) == (1.08 * 0.27 > 0.25 + 0.03)
    assert not B.calls(0.30, 10, 30, "flop", False, False)           # 0.92 * 0.30 = 0.276 < 0.28
    assert B.calls(0.30, 10, 30, "flop", True, False)                # 1.08 * 0.30 = 0.324 > 0.28


def test_huge_equity_facing_a_small_bet_never_folds(monkeypatch):
    fake_equity(monkeypatch, 0.97, 0.95)
    h = hand_("As Ah Kd", "Ac 7d 2h")
    for seed in range(30):
        r = req_("flop", ["Ac", "7d", "2h"], pot=14, opp_bet=2)
        got = B.decide(r, h, OppModel(), Clock(), random.Random(seed))
        assert got["action"] in ("call", "raise")


def test_near_zero_equity_folds_to_a_pot_sized_river_bet(monkeypatch):
    fake_equity(monkeypatch, 0.02, 0.01)
    h = hand_("3c 4d 9s", "Ac Kd Qh Jc 8s", keep="3c 4d", opp_discard="2h")
    r = req_("river", ["Ac", "Kd", "Qh", "Jc", "8s"], pot=80, opp_bet=40)
    assert B.decide(r, h, OppModel(), Clock(), random.Random(1)) == {"action": "fold"}


def test_pot_is_not_double_counted(monkeypatch):
    # price 10 / (30 + 10) = 0.25; counting their bet twice would give 10 / 50 = 0.20 and call with 0.23
    fake_equity(monkeypatch, 0.23, 0.10)
    h = hand_("3c 4d 9s", "Ac Kd Qh Jc 8s", keep="3c 4d", opp_discard="2h")
    r = req_("river", ["Ac", "Kd", "Qh", "Jc", "8s"], pot=30, opp_bet=10)
    assert B.decide(r, h, OppModel(), Clock(), random.Random(1)) == {"action": "fold"}
    fake_equity(monkeypatch, 0.27, 0.10)
    B._HC.clear()
    assert B.decide(r, h, OppModel(), Clock(), random.Random(1)) == {"action": "call"}


def test_all_in_call_uses_plain_pot_odds(monkeypatch):
    # turn, out of position, facing a shove of 100 into 200: price 1/3. E = 0.35 calls by plain pot odds, while
    # R_oop and the turn margin (0.92 * 0.35 < 0.333 + 0.03) would fold it.
    fake_equity(monkeypatch, 0.35, 0.20)
    h = hand_("3c 4d 9s", "Ac Kd Qh 8s", keep="3c 4d", opp_discard="2h")
    r = req_("turn", ["Ac", "Kd", "Qh", "8s"], pot=200, opp_bet=100, my_stack=100, opp_stack=0)
    assert "raise" not in r["legal_actions"]
    assert not B.calls(0.35, 100, 200, "turn", False, False)
    assert B.decide(r, h, OppModel(), Clock(), random.Random(1)) == {"action": "call"}


# ----------------------------------------------------------------------------------------------- B4
def test_last_raise_with_a_monster_is_big(monkeypatch):
    fake_equity(monkeypatch, 0.97, 0.96)
    h = hand_("As Ah Kd", "Ac 7d 2h")
    hist = [{"street": "flop", "actor": "opp", "action": "raise", "amount": 4},
            {"street": "flop", "actor": "me", "action": "raise", "amount": 10},
            {"street": "flop", "actor": "opp", "action": "raise", "amount": 24}]
    r = req_("flop", ["Ac", "7d", "2h"], pot=12 + 10 + 24, my_bet=10, opp_bet=24, raises_left=1, history=hist,
             last_raise=14)
    got = B.decide(r, h, OppModel(), Clock(), random.Random(1))
    s = spot(r)
    assert got["action"] == "raise"
    assert got["amount"] >= min(s.hi, s.opp_bet + round(1.0 * (s.pot + s.to_call)))   # at least a pot raise


def test_no_raise_when_raises_left_is_zero_or_raise_is_absent(monkeypatch):
    fake_equity(monkeypatch, 0.97, 0.96)
    h = hand_("As Ah Kd", "Ac 7d 2h")
    r = req_("flop", ["Ac", "7d", "2h"], pot=60, my_bet=14, opp_bet=34, raises_left=0)
    assert r["legal_actions"] == ["fold", "call"]
    assert B.decide(r, h, OppModel(), Clock(), random.Random(1)) == {"action": "call"}
    # raise missing although raises_left > 0 (the opponent is all-in)
    r = req_("flop", ["Ac", "7d", "2h"], pot=200, my_bet=0, opp_bet=180, opp_stack=0, raises_left=3)
    assert "raise" not in r["legal_actions"]
    assert B.decide(r, h, OppModel(), Clock(), random.Random(1)) == {"action": "call"}
    fake_equity(monkeypatch, 0.10, 0.05)
    B._HC.clear()
    assert B.decide(r, h, OppModel(), Clock(), random.Random(1)) == {"action": "fold"}


# ----------------------------------------------------------------------------------------------- flop best keep
@pytest.mark.parametrize("hole, flop", [("As Ks Qd", "Jd Tc 2s"), ("Ad Qd 9c", "As 9h 4c"), ("7h 7c 2d", "Kh 8h 3s")])
def test_flop_best_keep_is_max_of_averages(hole, flop):
    h, f = ids(hole), ids(flop)
    n = 600
    res = D.keep_equities(h, f, dead_mask(h + f), INF, random.Random(9), max_samples=n)
    # independent computation on the same samples
    rng = random.Random(9)
    rest = [c for c in range(52) if c not in h and c not in f]
    keeps = [k for _, k in D._keep_order(tuple(h))]
    tot = [0.0, 0.0, 0.0]
    per_sample_best = 0.0
    for _ in range(n):
        t0, t1, t2, r1, r2 = rng.sample(rest, 5)
        d = D.opp_discard_policy((t0, t1, t2), tuple(f))
        x, y = [c for c in (t0, t1, t2) if c != d]
        ov = eval7((x, y) + tuple(f) + (r1, r2))
        vals = []
        for i, k in enumerate(keeps):
            hv = eval7(tuple(k) + tuple(f) + (r1, r2))
            vals.append(1.0 if hv > ov else (0.5 if hv == ov else 0.0))
            tot[i] += vals[-1]
        per_sample_best += max(vals)
    avgs = [t / n for t in tot]
    assert res["n"] == n
    assert res["eq"] == pytest.approx(tuple(avgs), abs=1e-12)
    assert res["best"] == pytest.approx(max(avgs), abs=1e-12)
    assert res["best"] <= per_sample_best / n + 1e-12


def test_flop_equity_in_decide_is_the_best_keep(monkeypatch):
    seen = {}
    real = D.keep_equities

    def spy(*a, **k):
        out = real(*a, **k)
        seen["res"] = out
        return out
    monkeypatch.setattr(D, "keep_equities", spy)
    h = hand_("As Ks Qd", "9s 4s 2d")
    r = req_("flop", ["9s", "4s", "2d"], pot=12)
    B.decide(r, h, OppModel(), Clock(budget=50.0), random.Random(3))
    res = seen["res"]
    assert res is not None and res["best"] == max(res["eq"])
    cached = [v for k, v in B._HC.items() if isinstance(k, tuple) and k[0] == "eq"]
    assert len(cached) == 1 and cached[0][0] == res["best"] and cached[0][3] == "mc"


def test_discard_refactor_keeps_choose_discard_results():
    """keep_equities with no plug-ins draws exactly the samples choose_discard draws."""
    h, f = ids("As Ks Qd"), ids("Jd Tc 2s")
    D.choose_discard(h, f, None, None, INF, random.Random(4), max_samples=800)
    res = D.keep_equities(h, f, None, INF, random.Random(4), max_samples=800)
    assert res["eq"] == D.last_info["eq"]


# ----------------------------------------------------------------------------------------------- B7 range model
def _turn_spot(history_turn, opp=None, board="Kh 8h 3s 2c", hist_flop=None):
    h = hand_("As Ad 5c", "Kh 8h 3s 2c", keep="As Ad", opp_discard="4d")
    hist = (hist_flop or [{"street": "flop", "actor": "opp", "action": "check"},
                          {"street": "flop", "actor": "me", "action": "check"}]) + history_turn
    r = req_("turn", board.split(), pot=12, history=hist)
    return r, h


def _mean_strength(w, board):
    bd = tuple(ids(board))
    vals = np.array([eval7(PAIRS[i] + bd) >> 20 if w[i] > 0 else 0 for i in range(1326)], dtype=float)
    return float((w * vals).sum() / w.sum())


@pytest.mark.parametrize("hist", [[], [{"street": "turn", "actor": "opp", "action": "raise", "amount": 8}],
                                  [{"street": "turn", "actor": "opp", "action": "check"}]])
def test_range_weights_are_valid(hist):
    r, h = _turn_spot(hist)
    w = B.opp_range(r, h, OppModel())
    assert w.shape == (1326,) and np.all(np.isfinite(w)) and np.all(w >= 0) and w.sum() > 0
    for c in list(h.hole3) + list(h.board) + [parse("4d")]:
        assert all(w[i] == 0 for i, (a, b) in enumerate(PAIRS) if c in (a, b))


def test_aggression_shifts_mass_to_stronger_hands():
    board = "Kh 8h 3s 2c"
    r0, h0 = _turn_spot([{"street": "turn", "actor": "opp", "action": "check"}])
    r1, h1 = _turn_spot([{"street": "turn", "actor": "opp", "action": "raise", "amount": 8}])
    w0 = B.opp_range(r0, h0, OppModel())
    B._HC.clear()
    w1 = B.opp_range(r1, h1, OppModel())
    assert _mean_strength(w1, board) > _mean_strength(w0, board) + 0.1
    # flop aggression (through the posterior's flop_action) too
    B._HC.clear()
    bet_flop = [{"street": "flop", "actor": "opp", "action": "raise", "amount": 4},
                {"street": "flop", "actor": "me", "action": "call", "amount": 4}]
    r2, h2 = _turn_spot([], hist_flop=bet_flop)
    w2 = B.opp_range(r2, h2, OppModel())
    B._HC.clear()
    r3, h3 = _turn_spot([])
    w3 = B.opp_range(r3, h3, OppModel())
    assert _mean_strength(w2, board) > _mean_strength(w3, board) + 0.05
    # the flop tilt is monotone in S
    f = B._flop_tilt(1.1)
    assert f(0.2) < f(1.5) < f(2.5) < f(4.0)


def test_random_archetype_leaves_the_range_as_dealt():
    r, h = _turn_spot([{"street": "turn", "actor": "opp", "action": "raise", "amount": 8}],
                      hist_flop=[{"street": "flop", "actor": "opp", "action": "raise", "amount": 4},
                                 {"street": "flop", "actor": "me", "action": "call", "amount": 4}])
    w = B.opp_range(r, h, Opp(arch={"random": 1.0}))
    live = [i for i, (a, b) in enumerate(PAIRS) if not h.dead[a] and not h.dead[b]]
    assert np.allclose(w[live], w[live][0]) and w.sum() > 0
    assert np.count_nonzero(w) == len(live)
    # and the flop prior is uninformative
    assert min(B.preflop_play(r["history"], P._Reads(Opp()), info=0.0)) == 1.0


def test_preflop_prior_follows_the_line():
    reads = P._Reads(OppModel())
    pct = np.array(P.PCT)
    raised = B.preflop_play([{"street": "preflop", "actor": "opp", "action": "raise", "amount": 6}], reads)
    raised = np.array(raised)
    top = pct >= 1 - reads.pfr + 0.15
    bottom = pct <= 1 - reads.pfr - 0.15
    assert raised[top].min() > 0.9 and raised[bottom].max() < 0.1
    checked = B.preflop_play([{"street": "preflop", "actor": "me", "action": "call", "amount": 2},
                              {"street": "preflop", "actor": "opp", "action": "check"}], reads)
    assert min(checked) == 1.0
    three = np.array(B.preflop_play([{"street": "preflop", "actor": "me", "action": "raise", "amount": 6},
                                     {"street": "preflop", "actor": "opp", "action": "raise", "amount": 18}], reads))
    assert (three > 0.5).mean() < (raised > 0.5).mean()


# ----------------------------------------------------------------------------------------------- B5 / B6 mixing
def test_river_bluff_rate_tracks_the_formula(monkeypatch):
    fake_equity(monkeypatch, 0.05, 0.02)
    h = hand_("3c 4d 9s", "Ac Kd Qh Jc 8s", keep="3c 4d", opp_discard="2h")
    r = req_("river", ["Ac", "Kd", "Qh", "Jc", "8s"], pot=30)
    s = spot(r)
    amt = B.bet_amount(s, params.BET_F_STD)
    p = B.bluff_prob(amt - s.my_bet, s.pot, 0.42, False)
    assert p == pytest.approx(min(1.0, params.BET_BLUFF_V / params.BET_BLUFF_A * amt / (30 + amt)))
    rng = random.Random(123)
    n = 4000
    k = sum(B.decide(r, h, OppModel(), Clock(), rng)["action"] == "raise" for _ in range(n))
    assert abs(k / n - p) < 4 * math.sqrt(p * (1 - p) / n), (k / n, p)
    assert 0.05 < p < 0.4                                            # rarely, not never
    k = sum(B.decide(r, h, Opp(arch={"station": 1.0}), Clock(), rng)["action"] == "raise" for _ in range(500))
    assert k == 0
    k = sum(B.decide(r, h, Opp(arch={"random": 1.0}), Clock(), rng)["action"] == "raise" for _ in range(500))
    assert k == 0


def _flop_folder_river_caller(n=80):
    """The review's opponent: folds to our flop bet three hands in four, checks down to call our river bet in the
    fourth. Aggregate fold-to-bet ~0.69, river fold-to-bet ~0.25."""
    pre = [{"street": "preflop", "actor": "me", "action": "raise", "amount": 6},
           {"street": "preflop", "actor": "opp", "action": "call", "amount": 6}]
    folds = pre + [{"street": "flop", "actor": "opp", "action": "check"},
                   {"street": "flop", "actor": "me", "action": "raise", "amount": 8},
                   {"street": "flop", "actor": "opp", "action": "fold"}]
    calls_ = pre + [{"street": st, "actor": a, "action": "check"} for st in ("flop", "turn") for a in ("opp", "me")]
    calls_ += [{"street": "river", "actor": "opp", "action": "check"},
               {"street": "river", "actor": "me", "action": "raise", "amount": 8},
               {"street": "river", "actor": "opp", "action": "call", "amount": 8}]
    o = OppModel()
    for i in range(n):
        h = calls_ if i % 4 == 3 else folds
        o.observe_hand({"type": "hand_result", "result": "fold" if h is folds else "showdown", "history": h})
    return o


def test_river_bluffs_read_the_river_fold_to_bet(monkeypatch):
    o = _flop_folder_river_caller()
    assert o.stat("fold_to_bet") == pytest.approx(0.688, abs=0.002)
    assert o.stat("fold_to_bet_river") == pytest.approx(0.249, abs=0.002)
    fake_equity(monkeypatch, 0.05, 0.02)
    hist = [{"street": st, "actor": a, "action": "check"} for st in ("flop", "turn") for a in ("opp", "me")]
    hist.append({"street": "river", "actor": "opp", "action": "check"})
    board = ["Ac", "Kd", "Qh", "Jc", "8s"]
    r = req_("river", board, pot=12, history=hist)
    h = hand_("3c 4d 9s", " ".join(board), seat="button", keep="3c 4d", opp_discard="2h")
    assert B.bet_amount(spot(r), params.BET_F_STD) == 8                # 8 into 12: bar 0.4 < aggregate 0.688
    rng = random.Random(7)
    acts = [B.decide(r, h, o, Clock(), rng) for _ in range(300)]
    assert all(a["action"] == "check" for a in acts)                   # river 0.249 < BET_BLUFF_MIN_FTB: never
    # the per-street read falls back to the aggregate while the stats are untrusted
    stub = Opp(hands=5, fold_to_bet=0.9, fold_to_bet_river=0.0)
    assert B._Opp(stub).ftb_st["river"] == B._Opp(stub).ftb == params.OPP_FREQ["fold_to_bet"][0]
    trusted = Opp(hands=50, fold_to_bet=0.9)                            # no street data: shrinks to the aggregate
    assert B._Opp(trusted).ftb_st == {"flop": 0.9, "turn": 0.9, "river": 0.9}


def test_pit_k_inverts_the_tilted_mean():
    assert B.pit_k(0.5) == 0.0
    for m in (0.3, 0.42, 0.55):
        k = B.pit_k(m)
        assert B._tilted_mean(k) == pytest.approx(m, abs=1e-6)
    assert B.pit_k(0.3) < B.pit_k(0.42) < 0 < B.pit_k(0.55)
    assert B.pit_k(0.01) == params.BET_PIT_K_LO and B.pit_k(0.99) == params.BET_PIT_K_HI
    assert B.pit_k(float("nan")) == 0.0


def test_river_calibration_weakens_their_betting_range_and_records_the_base():
    hist = [{"street": st, "actor": a, "action": "check"} for st in ("flop", "turn") for a in ("me", "opp")]
    hist.append({"street": "river", "actor": "me", "action": "check"})
    hist.append({"street": "river", "actor": "opp", "action": "raise", "amount": 10})
    board = ["2c", "7d", "9h", "Ks", "4s"]
    r = req_("river", board, pot=22, opp_bet=10, history=hist)
    eqs = []
    for pit in (0.5, 0.3):
        B._HC.clear()
        B._HC["key"] = None
        h = hand_(" ".join(["9c", "8d", "3c"]), " ".join(board), keep="9c 8d", opp_discard="2h")
        o = B._Opp(Opp(hands=50, river_pit=pit))
        e = B._turn_river_equity(r, h, o, "river", 1e9, 400, random.Random(1), B._now())[0]
        eqs.append(e)
        assert B._HC.get("pit_base") is not None
        out = B.decide(r, h, Opp(hands=50, river_pit=pit), Clock(), random.Random(1))
        if out["action"] == "call":
            assert h.river_pit is not None
    assert eqs[1] > eqs[0] + 0.03                    # their bets are weaker than modelled -> more equity for us
    # not facing a river bet: no correction, nothing recorded
    B._HC.clear()
    B._HC["key"] = None
    r2 = req_("river", board, pot=12, history=hist[:-1])
    h2 = hand_("9c 8d 3c", " ".join(board), keep="9c 8d", opp_discard="2h")
    B._range_for(r2, h2, B._Opp(Opp(hands=50, river_pit=0.3)), "river")
    assert B._HC.get("pit_base") is None


def test_turn_without_samples_uses_the_draw_aware_static_path(monkeypatch):
    """Review bug 1: on the turn, current-hand strength is not equity. A flush draw + gutshot (5s6s on KsQs2d3c,
    ~36% against a uniform range over the legal rivers) facing a 20-chip all-in into 360 must not fold when no
    time is left for sampling or too few samples were drawn."""
    hist = [{"street": "flop", "actor": "opp", "action": "check"}, {"street": "flop", "actor": "me", "action": "check"},
            {"street": "turn", "actor": "me", "action": "check"},
            {"street": "turn", "actor": "opp", "action": "raise", "amount": 20}]
    r = req_("turn", ["Ks", "Qs", "2d", "3c"], pot=360, opp_bet=20, my_stack=20, opp_stack=0, history=hist)
    assert r["legal_actions"] == ["fold", "call"]
    h = hand_("5s 6s 2c", "Ks Qs 2d 3c", keep="5s 6s", opp_discard="7h")
    o = B._Opp(Opp(arch={"random": 1.0}))
    assert B._turn_river_equity(r, h, o, "turn", 0.0, 1000, random.Random(1), B._now()) is None
    assert B._turn_river_equity(r, h, o, "turn", 1e9, params.BET_TURN_MIN_SAMPLES - 1, random.Random(1),
                                B._now()) is None
    e = B._turn_river_equity(r, h, o, "turn", 1e9, 1000, random.Random(1), B._now())
    assert e[3] == "mc" and e[0] > 0.25                             # the sampler sees the river
    st = B._static_equity(h, "turn", o, B._actions(r["history"])[0])
    assert st[0] > 0.25                                             # the static fallback counts the draws
    for budget in (0.001, 1.0):                                     # < BET_MIN_EXTRA_MS: no sampling
        B._HC.clear()
        B._HC["key"] = None
        before = B.stats["path"].get("static", 0)
        assert B.decide(r, h, Opp(arch={"random": 1.0}), Clock(budget), random.Random(1))["action"] == "call"
        assert B.stats["path"].get("static", 0) == before + 1


def test_river_range_scores_the_turn_action_without_the_river_card():
    """Review bug 2: the turn percentiles behind their turn action must not see the river card as dead (holdings
    containing it are dropped afterwards). And the river reuses the turn's own percentiles."""
    board5 = "Kh 8h 3s 2c Ah"
    hist = [{"street": "flop", "actor": "opp", "action": "check"}, {"street": "flop", "actor": "me", "action": "check"},
            {"street": "turn", "actor": "opp", "action": "raise", "amount": 8},
            {"street": "turn", "actor": "me", "action": "call", "amount": 8}]
    r = req_("river", board5.split(), pot=28, history=hist)
    h = hand_("As Ad 5c", board5, keep="As Ad", opp_discard="4d")
    o = B._Opp(OppModel())
    w = B._range_for(r, h, o, "river")[0].copy()
    by, _ = B._actions(r["history"])
    post = B._posterior(B._hand_cache(h), r, h, o, by).copy()
    board = list(h.board)
    dead4 = dead_mask(list(h.hole3) + board[:4] + [parse("4d")])
    idx4, _, u4 = B._strengths(post, board[:4], B._live(dead4, board[:4]), "turn")
    g = B._tilts(r["history"], o.size_damp)["turn"] * o.tilt_mult
    assert g != 0.0 and B._tilts(r["history"], o.size_damp)["river"] == 0.0
    want = post.copy()
    want[idx4] *= np.exp(g * params.BET_U_SCALE * u4)
    want[~B._live(h.dead, board)] = 0.0
    assert np.allclose(w / w.sum(), want / want.sum(), rtol=1e-9, atol=1e-12)
    # the old reconstruction (river card dead on the turn) moves the turn percentiles: the test can tell
    idx_bad, _, u_bad = B._strengths(post, board[:4], B._live(h.dead, board[:4]), "turn")
    assert np.abs(u_bad - u4[np.isin(idx4, idx_bad)]).max() > 0.01
    # turn first, then river (the live order): the cached turn percentiles give the same river range
    B._HC.clear()
    B._HC["key"] = None
    h4 = hand_("As Ad 5c", "Kh 8h 3s 2c", keep="As Ad", opp_discard="4d")
    B._range_for(req_("turn", "Kh 8h 3s 2c".split(), pot=28, history=hist[:2]), h4, o, "turn")
    h4.board = ids(board5)
    h4.rebuild_dead()
    w2 = B._range_for(r, h4, o, "river")[0]
    assert np.allclose(w2, w, rtol=1e-12, atol=0)


def test_bluff_exploit_test():
    # 2/3 pot: bar 0.4. Trusted fold-to-bet above the bar -> always; below the floor -> never
    assert B.bluff_prob(20, 30, 0.45, True) == 1.0
    assert B.bluff_prob(20, 30, 0.10, True) == 0.0
    assert B.bluff_prob(20, 30, 0.45, False) == pytest.approx(params.BET_BLUFF_V / params.BET_BLUFF_A * 0.4)
    assert B.bluff_prob(30, 30, 0.42, True) == pytest.approx(params.BET_BLUFF_V / params.BET_BLUFF_A * 0.5)
    assert B.semi_prob(0.6, True) == params.BET_SEMI_P_HIGH
    assert B.semi_prob(0.3, True) == 0.0
    assert B.semi_prob(0.3, False) == params.BET_SEMI_P_BASE
    assert B.semi_prob(0.6, True, mult=0.0) == 0.0


# ----------------------------------------------------------------------------------------------- panic tier
def test_panic_tier_never_samples(monkeypatch):
    calls = []

    def boom(name):
        def f(*a, **k):
            calls.append(name)
            raise AssertionError(name)
        return f
    for mod, name in ((D, "keep_equities"), (D, "posterior_after_discard"), (D, "_simulate_core"),
                      (EQ, "equity"), (EQ, "deal_samples"), (EQ, "_drawer"), (B, "_flop_equity"),
                      (B, "_turn_river_equity"), (B, "_range_for")):
        monkeypatch.setattr(mod, name, boom(name))
    before = B.stats["path"].get("static", 0)
    cases = [
        (hand_("As Ks Qd", "Jd Tc 2s"), req_("flop", ["Jd", "Tc", "2s"], pot=12)),
        (hand_("As Ks Qd", "Jd Tc 2s"), req_("flop", ["Jd", "Tc", "2s"], pot=20, opp_bet=8)),
        (hand_("As Ks Qd", "Jd Tc 2s 7h", keep="As Ks", opp_discard="3c"),
         req_("turn", ["Jd", "Tc", "2s", "7h"], pot=40, opp_bet=20)),
        (hand_("As Ks Qd", "Jd Tc 2s 7h Ah", keep="As Ks", opp_discard="3c"),
         req_("river", ["Jd", "Tc", "2s", "7h", "Ah"], pot=40)),
    ]
    for h, r in cases:
        got = B.decide(r, h, OppModel(), Clock(budget=0.0, tier="panic"), random.Random(1))
        assert legal.make_legal(got, r) == dict({"type": "action"}, **got)
    assert calls == []
    assert B.stats["path"].get("static", 0) == before + len(cases)


# ----------------------------------------------------------------------------------------------- property test
def _random_request(rng):
    """A random engine-consistent postflop request: earlier streets checked through, this street played by the
    engine's rules with random actions until it is our turn."""
    street = rng.choice(["flop", "turn", "river"])
    nb = {"flop": 3, "turn": 4, "river": 5}[street]
    cards = rng.sample(range(52), 3 + 3 + 1 + nb)
    hole3, opp3, board = cards[:3], cards[3:6], cards[7:7 + nb]
    our_seat = rng.choice([0, 1])                                     # 0 = button
    c = rng.choice([2, 2, 4, 6, 18, 40, 100, 150, 198])
    stacks = [200 - c, 200 - c]
    committed = [c, c]
    bets = [0, 0]
    last_raise, raises, actor = 0, 0, 1
    acted = [False, False]
    hist = []
    while True:
        opp = 1 - actor
        to_call = bets[opp] - bets[actor]
        max_raise = min(bets[actor] + stacks[actor], bets[opp] + stacks[opp])
        legal_ = ["fold", "call"] if to_call > 0 else ["check"]
        can_raise = raises < 4 and max_raise > bets[opp]
        if can_raise:
            legal_.append("raise")
        if actor == our_seat and (rng.random() < 0.35 or not acted[actor]):
            break
        a = rng.choice([x for x in legal_ if x != "fold"])
        who = "me" if actor == our_seat else "opp"
        if a == "check":
            hist.append({"street": street, "actor": who, "action": "check"})
        elif a == "call":
            stacks[actor] -= to_call
            committed[actor] += to_call
            bets[actor] = bets[opp]
            hist.append({"street": street, "actor": who, "action": "call", "amount": bets[actor]})
        else:
            lo = min(bets[opp] + max(last_raise, 2), max_raise)
            amt = rng.randint(lo, max_raise)
            stacks[actor] -= amt - bets[actor]
            committed[actor] += amt - bets[actor]
            last_raise = amt - bets[opp]
            bets[actor] = amt
            raises += 1
            acted[opp] = False
            hist.append({"street": street, "actor": who, "action": "raise", "amount": amt})
        acted[actor] = True
        if (acted[0] and acted[1] and bets[0] == bets[1]) or 0 in stacks:
            return None
        actor = opp
    me, op = our_seat, 1 - our_seat
    to_call = bets[op] - bets[me]
    max_raise = min(bets[me] + stacks[me], bets[op] + stacks[op])
    can_raise = raises < 4 and max_raise > bets[op]
    req = {"type": "action_request", "hand_id": 7, "street": street, "board": [fmt(x) for x in board],
           "pot": sum(committed), "my_bet": bets[me], "opp_bet": bets[op], "to_call": to_call,
           "my_stack": stacks[me], "opp_stack": stacks[op],
           "legal_actions": (["fold", "call"] if to_call > 0 else ["check"]) + (["raise"] if can_raise else []),
           "raises_left": 4 - raises, "time_left_ms": 20000,
           "history": [{"street": "preflop", "actor": "me" if our_seat == 0 else "opp", "action": "raise",
                        "amount": c}, {"street": "preflop", "actor": "opp" if our_seat == 0 else "me",
                                       "action": "call", "amount": c}] + hist}
    if can_raise:
        req["min_raise"] = min(bets[op] + max(last_raise, 2), max_raise)
        req["max_raise"] = max_raise
    h = HandState(7, "button" if our_seat == 0 else "big_blind", [fmt(x) for x in hole3])
    h.update_from_request(req)
    if street != "flop":
        h.update_from_discard_result({"my_discard": fmt(hole3[2]), "opp_discard": fmt(opp3[0]),
                                      "hole_cards": [fmt(hole3[0]), fmt(hole3[1])]})
    return req, h


def test_random_requests_always_get_a_legal_reply():
    rng = random.Random(2024)
    n = 0
    archs = [None, {"station": 1.0}, {"random": 0.5, "nit": 0.5}, {"maniac": 1.0, "weird": 2.0}]
    while n < 150:
        got = _random_request(rng)
        if got is None:
            continue
        req, h = got
        B._HC.clear()
        opp = Opp(arch=rng.choice(archs), hands=rng.choice([0, 50]), fold_to_bet=rng.random())
        clock = Clock(budget=rng.choice([0.0, 2.0, 6.0]), tier=rng.choice(["normal", "throttle", "panic"]))
        intent = B.decide(req, h, opp, clock, random.Random(n))
        reply = legal.make_legal(intent, req)
        assert reply == dict({"type": "action"}, **intent), (req, intent)
        assert intent["action"] in req["legal_actions"]
        if intent["action"] == "raise":
            assert isinstance(intent["amount"], int) and req["min_raise"] <= intent["amount"] <= req["max_raise"]
        n += 1


def test_decide_never_raises_on_garbage():
    h = HandState(1, "button", ["As", "Kd", "7c"])
    h.board = ids("2c 7d 9h")
    for r in ({}, {"street": "flop"}, {"street": "turn", "legal_actions": ["check", "raise"], "min_raise": "x"},
              {"street": "river", "legal_actions": None, "pot": float("nan")},
              {"street": "flop", "legal_actions": ["check", "raise"], "min_raise": 2, "max_raise": 1.5, "pot": "x"},
              {"street": "flop", "legal_actions": ["fold", "call"], "to_call": 5, "pot": None, "history": "junk"}):
        got = B.decide(r, h, None, None, random.Random(1))
        if r.get("street") == "turn":                                 # no 2-card hole yet: deferred to the caller
            assert got is None
            continue
        assert isinstance(got, dict) and "action" in got
        legal.make_legal(got, r)


def test_unknown_hole_cards_defer_to_the_caller():
    h = HandState(9)                                                  # new_hand missed: no hole cards
    r = req_("flop", ["Ah", "7d", "2s"], pot=12, opp_bet=5)
    assert B.decide(r, h, OppModel(), Clock(), random.Random(1)) is None
    b = Brain()
    r["hand_id"] = 99
    assert b.act(r) == {"action": "call"}                             # Brain's v0 fallback


def test_brain_routes_postflop_to_betting(monkeypatch):
    b = Brain()
    b.on_new_hand({"hand_id": 3, "seat": "big_blind", "hole_cards": ["As", "Ah", "Ks"]})
    r = req_("flop", ["Ac", "7d", "2h"], pot=12)
    r["hand_id"] = 3
    seen = []
    monkeypatch.setattr(B, "decide", lambda *a, **k: seen.append(a) or {"action": "raise", "amount": 8})
    assert b.act(r) == {"action": "raise", "amount": 8} and len(seen) == 1

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(B, "decide", boom)
    assert b.act(r) == {"action": "check"}                          # v0 fallback


# ----------------------------------------------------------------------------------------------- engine
@pytest.mark.parametrize("opp", ["random", "starter", "shove"])
def test_engine_match_no_notices(tmp_path, opp):
    path = {"random": RANDOM_BOT, "starter": STARTER, "shove": TESTS / "shove_bot.py"}[opp]
    out, res = run_match(BOT, path, seed=41, log_dir=tmp_path, hands=200)
    assert_clean(out, res)
    log = (tmp_path / "match.log").read_text(encoding="utf-8")
    if opp != "shove":                                              # the shover's hands end all-in preflop
        assert re.search(r"(flop|turn|river): [^|]* Ar\d+", log), "we never bet postflop"
