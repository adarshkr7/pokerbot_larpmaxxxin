"""Preflop (strategies/04_preflop.md P1-P4; W4). Every random draw is seeded."""
import json
import math
import random
from itertools import combinations

import pytest

import discard as D
import legal
import params
import preflop as P
from brain import Brain
from cards import fmt, parse
from engine_util import BOT, RANDOM_BOT, STARTER, TESTS, assert_clean, run_match
from equity import canon3
from evaluator import eval7
from opponent import OppModel
from state import HandState


def ids(s):
    return [parse(x) for x in s.split()]


def cls(s):
    return canon3(ids(s))


# ----------------------------------------------------------------------------------------------- request builder
def replay(seq, stacks=(200, 200)):
    """Replay the preflop actions `seq` by the rules of starter_kit/engine.py::Hand.betting_round (seat 0 = button,
    which posts 1 and acts first). Items: "fold", "check", "call" or ("raise", to). Returns (req, actor, over):
    the action_request the engine would send next to `actor`, and whether the round has already ended."""
    bets = [1, 2]
    st = [stacks[0] - 1, stacks[1] - 2]
    last_raise, raises, actor = 2, 1, 0
    acted = [False, False]
    over = False
    hist = []
    for a in seq:
        opp = 1 - actor
        to_call = bets[opp] - bets[actor]
        if a == "fold":
            hist.append((actor, "fold", None))
            over = True
            break
        if a == "call":
            st[actor] -= to_call
            bets[actor] = bets[opp]
            hist.append((actor, "call", bets[actor]))
        elif a == "check":
            hist.append((actor, "check", None))
        else:
            _, amt = a
            st[actor] -= amt - bets[actor]
            last_raise = amt - bets[opp]
            bets[actor] = amt
            raises += 1
            acted[opp] = False
            hist.append((actor, "raise", amt))
        acted[actor] = True
        if acted[0] and acted[1] and bets[0] == bets[1]:
            over = True
            break
        actor = opp
    opp = 1 - actor
    to_call = bets[opp] - bets[actor]
    max_raise = min(bets[actor] + st[actor], bets[opp] + st[opp])
    legal_actions = ["fold", "call"] if to_call > 0 else ["check"]
    can_raise = raises < 4 and max_raise > bets[opp]
    if can_raise:
        legal_actions.append("raise")
    req = {"type": "action_request", "hand_id": 1, "street": "preflop", "board": [],
           "pot": (stacks[0] - st[0]) + (stacks[1] - st[1]),
           "my_bet": bets[actor], "opp_bet": bets[opp], "to_call": to_call,
           "my_stack": st[actor], "opp_stack": st[opp], "legal_actions": legal_actions}
    if can_raise:
        req["min_raise"] = min(bets[opp] + max(last_raise, 2), max_raise)
        req["max_raise"] = max_raise
    req["raises_left"] = 4 - raises
    req["history"] = [dict({"street": "preflop", "actor": "me" if a == actor else "opp", "action": act},
                           **({"amount": amt} if amt is not None else {})) for a, act, amt in hist]
    req["time_left_ms"] = 30000
    return req, actor, over


def preflop_req(seq, stacks=(200, 200)):
    req, actor, over = replay(seq, stacks)
    assert not over, seq
    return req, actor


def hand_for(hole, actor):
    return HandState(1, "button" if actor == 0 else "big_blind", hole.split())


def decide(hole, seq, opp=None, seed=1, stacks=(200, 200), with_hand=True):
    req, actor = preflop_req(seq, stacks)
    hs = hand_for(hole, actor) if with_hand else None
    out = P.decide(req, hs, opp if opp is not None else OppModel(), rng=random.Random(seed))
    check_legal(out, req)
    return out, req


def check_legal(intent, req):
    """The intent is already legal: make_legal leaves it unchanged; raise amounts are ints in range."""
    assert isinstance(intent, dict)
    reply = legal.make_legal(intent, req)
    expect = {"type": "action", "action": intent["action"]}
    if intent["action"] == "raise":
        assert isinstance(intent["amount"], int) and not isinstance(intent["amount"], bool)
        assert req["min_raise"] <= intent["amount"] <= req["max_raise"]
        expect["amount"] = intent["amount"]
    assert intent["action"] in req["legal_actions"]
    assert reply == expect, (intent, reply, req)


def hand_at(pct_lo, pct_hi):
    """Some physical hand (as a string) whose percentile is in [pct_lo, pct_hi)."""
    for k in range(P.N_CLASSES):
        if pct_lo <= P.PCT[k] < pct_hi:
            for tri in combinations(range(52), 3):
                if canon3(tri) == k:
                    return " ".join(fmt(c) for c in tri)
    raise AssertionError("no class in range")


class Stats(OppModel):
    def __init__(self, **kw):
        self.kw = kw

    def stat(self, name):
        return self.kw.get(name, super().stat(name))


# ----------------------------------------------------------------------------------------------- table
def test_table_loaded_and_shaped():
    assert P.SOURCE == "table"
    with open(P.DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    h = data["header"]
    for key in ("opponent_range", "discard_policy", "samples_per_class", "seed", "max_se", "range_widths"):
        assert key in h
    assert h["max_se"] <= 0.005
    assert len(P.EQ) == 1755 and all(0.0 < x < 1.0 for x in P.EQ)
    assert P.VS_TOP is not None and len(P.VS_TOP) == len(P.WIDTHS)
    assert all(len(col) == 1755 and all(0.0 < x < 1.0 for x in col) for col in P.VS_TOP)
    assert len(json.dumps(data)) < 120_000


def test_strength_invariant_under_suit_permutation_and_order():
    rng = random.Random(3)
    perms = [dict(zip("shdc", p)) for p in __import__("itertools").permutations("shdc")]
    for _ in range(200):
        tri = rng.sample(range(52), 3)
        s = [fmt(c) for c in tri]
        base = P.strength(s)
        for perm in rng.sample(perms, 5):
            t = [x[0] + perm[x[1]] for x in s]
            rng.shuffle(t)
            assert P.strength(t) == base
            assert P.strength([parse(x) for x in t]) == base


def test_trips_are_not_all_premium_and_two_suited_beats_monotone():
    # 04/P1 independent figures: 222 ~ 32 %, 999 ~ 58 %, AAA ~ 77 % (100k samples, same model)
    assert P.strength(ids("2s 2h 2d")) == pytest.approx(0.32, abs=0.035)
    assert P.strength(ids("9s 9h 9d")) == pytest.approx(0.58, abs=0.03)
    assert P.strength(ids("As Ah Ad")) == pytest.approx(0.77, abs=0.03)
    assert P.percentile(ids("2s 2h 2d")) < 0.10
    assert P.strength(ids("As Ah Ks")) > P.strength(ids("As Ah Ad"))
    # same ranks: the best two-suited version beats the monotone one
    wins = total = 0
    for r1, r2, r3 in combinations(range(13), 3):
        a, b, c = r3 * 4, r2 * 4, r1 * 4                 # all spades = monotone
        mono = P.EQ[canon3((a, b, c))]
        two = max(P.EQ[canon3((a + 1, b, c))], P.EQ[canon3((a, b + 1, c))], P.EQ[canon3((a, b, c + 1))])
        total += 1
        wins += two > mono
    assert wins / total >= 0.97, (wins, total)
    for hand, mono in (("As Ks Qd", "As Ks Qs"), ("Ts 9s 8d", "Ts 9s 8s"), ("Kh Qh Jc", "Kh Qh Jh")):
        assert P.strength(ids(hand)) > P.strength(ids(mono))


def _mc_vs_random(hole, n, seed):
    """Independent re-estimate of the table entry: our own sampler, eval7 showdown, both sides keep max-S."""
    rng = random.Random(seed)
    hero = tuple(ids(hole))
    deck = [c for c in range(52) if c not in hero]
    acc = acc2 = 0.0
    for _ in range(n):
        rng.shuffle(deck)
        opp, board = tuple(deck[:3]), tuple(deck[3:8])
        flop = board[:3]
        hd, od = D.opp_discard_policy(hero, flop), D.opp_discard_policy(opp, flop)
        h = eval7(tuple(c for c in hero if c != hd) + board)
        o = eval7(tuple(c for c in opp if c != od) + board)
        v = 1.0 if h > o else (0.5 if h == o else 0.0)
        acc += v
        acc2 += v * v
    m = acc / n
    return m, math.sqrt(max(0.0, acc2 / n - m * m) / n)


@pytest.mark.parametrize("hole", ["As Ah Ks", "Ts 9s 8d", "7s 2h 3d", "4s 4h 9c", "Kh Qd 5c"])
def test_table_matches_independent_monte_carlo(hole):
    m, se = _mc_vs_random(hole, 4000, seed=777)
    assert abs(P.strength(ids(hole)) - m) < 4 * se + 0.005, (hole, P.strength(ids(hole)), m, se)


def test_range_column_matches_independent_monte_carlo():
    """equity vs the top 20 % (opponent uniform over those physical hands, minus card collisions)."""
    rng = random.Random(99)
    hole = "Ah Kh 7c"
    hero = set(ids(hole))
    rng_hands = [t for t in combinations(range(52), 3) if P.PCT[canon3(t)] >= 0.8 - 1e-12 and not hero & set(t)]
    n = 3000
    acc = acc2 = 0.0
    for _ in range(n):
        opp = rng.choice(rng_hands)
        deck = [c for c in range(52) if c not in hero and c not in opp]
        board = tuple(rng.sample(deck, 5))
        flop = board[:3]
        h3 = tuple(sorted(hero))
        hd, od = D.opp_discard_policy(h3, flop), D.opp_discard_policy(opp, flop)
        h = eval7(tuple(c for c in h3 if c != hd) + board)
        o = eval7(tuple(c for c in opp if c != od) + board)
        v = 1.0 if h > o else (0.5 if h == o else 0.0)
        acc += v
        acc2 += v * v
    m = acc / n
    se = math.sqrt(max(0.0, acc2 / n - m * m) / n)
    got = P.equity_vs_top(ids(hole), 0.20)
    assert abs(got - m) < 4 * se + 0.012, (got, m, se)
    assert got < P.strength(ids(hole))           # a strong range costs equity


def test_equity_vs_top_is_monotone_in_width_for_a_strong_hand():
    xs = [P.equity_vs_top(ids("Ks Kh Qs"), w) for w in (0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0)]
    assert all(a <= b + 0.01 for a, b in zip(xs, xs[1:]))
    assert P.equity_vs_top(ids("Ks Kh Qs"), 0.01) == xs[0]


# ----------------------------------------------------------------------------------------------- percentiles
def test_percentiles_are_combination_weighted():
    assert sum(P.MULT) == 22100
    assert sum(P.MULT[canon3(t)] == 0 for t in combinations(range(52), 3)) == 0
    count = [0] * 1755
    for t in combinations(range(52), 3):
        count[canon3(t)] += 1
    assert count == P.MULT
    for x in (0.05, 0.15, 0.38, 0.70, 0.78, 0.92):
        top = sum(P.MULT[k] for k in range(1755) if P.PCT[k] >= 1 - x) / 22100
        assert abs(top - x) <= 25 / 22100, (x, top)       # within one class of the target
    best = max(range(1755), key=lambda k: P.EQ[k])
    worst = min(range(1755), key=lambda k: P.EQ[k])
    assert P.PCT[worst] == 0.0 and P.PCT[best] == pytest.approx(1 - P.MULT[best] / 22100)
    assert sorted(P.PCT) == sorted(set(P.PCT))                      # a strict order: no two classes share a value


# ----------------------------------------------------------------------------------------------- heuristic
def test_heuristic_ranks_the_named_examples():
    h = P.heuristic
    for prem in ("As Ah Ks", "Kd Kc Qd", "As Ks Qd", "Ks Qs Jd"):
        assert h(ids(prem)) > h(ids("As Kh 2c")), prem                     # premiums above a dangler
    # suited connected wraps beat the same top cards with a dangler (vs a random hand the table ranks them mid-pack,
    # below A-K-x: equity 0.49 / 0.51 vs 0.56, so "premium" in P1 does not survive the table for these two)
    assert h(ids("Ts 9s 8d")) > h(ids("Ts 9h 2c")) and h(ids("Jh Th 8c")) > h(ids("Jh Tc 2d"))
    assert P.EQ[cls("Ts 9s 8d")] > P.EQ[cls("Ts 9h 2c")]
    assert h(ids("As Kh 2c")) < h(ids("As Kh Qc"))
    for two, mono in (("As Ks Qd", "As Ks Qs"), ("Ts 9s 8d", "Ts 9s 8s")):
        assert h(ids(two)) > h(ids(mono))
    assert h(ids("2s 2h 2d")) < h(ids("As Kh 2c"))                          # low trips not top tier
    assert h(ids("9s 9h 9d")) < h(ids("As Ah Ks"))
    assert h(ids("7s 2h 3d")) < h(ids("4s 4h 9c")) < h(ids("Qs Qh 9c"))
    vals = [P._heuristic_key(k) for k in P.KEY]
    assert all(0.15 < v < 0.95 for v in vals)


def test_heuristic_agrees_with_the_table_in_rank():
    xs = [P._heuristic_key(k) for k in P.KEY]
    ys = P.EQ
    rx = {k: i for i, k in enumerate(sorted(range(1755), key=lambda k: xs[k]))}
    ry = {k: i for i, k in enumerate(sorted(range(1755), key=lambda k: ys[k]))}
    n = 1755
    d2 = sum((rx[k] - ry[k]) ** 2 for k in range(n))
    rho = 1 - 6 * d2 / (n * (n * n - 1))
    assert rho > 0.9, rho


def test_strength_falls_back_to_the_heuristic(tmp_path, monkeypatch):
    saved = (P.EQ, P.PCT, P.WIDTHS, P.VS_TOP, P.SOURCE)
    try:
        for content in (None, "{not json", json.dumps({"equity": [0.5] * 10}), json.dumps({"equity": [2.0] * 1755})):
            path = tmp_path / "pf.json"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            else:
                path = tmp_path / "missing.json"
            P._install(str(path))
            assert P.SOURCE == "heuristic"
            assert P.strength(ids("As Ah Ks")) == pytest.approx(P.heuristic(ids("As Ah Ks")))
            assert P.percentile(ids("As Ah Ks")) > 0.95
            # the range fallback is still sane and decide still works
            assert 0.0 < P.equity_vs_top(ids("As Ah Ks"), 0.2) < P.strength(ids("As Ah Ks"))
            out, _ = decide("As Ah Ks", [])
            assert out["action"] == "raise"
            out, _ = decide("7s 2h 3d", [])
            assert out["action"] == "fold"
        # equity present but vs_top broken -> table + approximate ranges
        good = json.loads(open(P.DATA_PATH, encoding="utf-8").read())
        good["vs_top"] = [[0.5] * 3]
        path = tmp_path / "half.json"
        path.write_text(json.dumps(good), encoding="utf-8")
        P._install(str(path))
        assert P.SOURCE == "table" and P.VS_TOP is None
        assert P.equity_vs_top(ids("As Ah Ks"), 0.2) < P.strength(ids("As Ah Ks"))
    finally:
        P.EQ, P.PCT, P.WIDTHS, P.VS_TOP, P.SOURCE = saved


def test_public_functions_never_raise():
    for bad in (None, [], ["As"], ["As", "As", "Kd"], ["zz", "Kd", "2c"], 5):
        assert P.strength(bad) == 0.5
        assert P.percentile(bad) == 0.5
        assert P.heuristic(bad) == 0.5
        assert P.equity_vs_top(bad, 0.2) == 0.5
    for req in (None, {}, {"legal_actions": "x"}, {"legal_actions": ["fold", "call"], "to_call": "a"}):
        out = P.decide(req, hand_for("As Ah Ks", 0), OppModel())
        assert out["action"] in ("check", "call", "fold", "raise")


# ----------------------------------------------------------------------------------------------- decide by spot
TOP = "As Ah Ks"          # premium
TRASH = "7s 2h 3d"        # bottom of the table


def test_button_first_in():
    out, req = decide(TOP, [])
    assert out == {"action": "raise", "amount": 6}                  # P3: open to 3 BB
    out, _ = decide(TRASH, [])
    assert out == {"action": "fold"}
    # the limp band: between the open and the fold cut
    limp = hand_at(1 - params.PF_OPEN_PCT - params.PF_LIMP_PCT + 0.025, 1 - params.PF_OPEN_PCT - 0.025)
    assert decide(limp, [])[0] == {"action": "call"}
    mid = hand_at(0.5, 0.52)
    assert decide(mid, [])[0] == {"action": "raise", "amount": 6}


def test_open_share_matches_params():
    """Over all physical hands, the button raises ~PF_OPEN_PCT and plays ~PF_OPEN_PCT + PF_LIMP_PCT."""
    rng = random.Random(5)
    raised = played = 0
    for t in combinations(range(52), 3):
        hs = HandState(1, "button", [fmt(c) for c in t])
        out = P.decide(preflop_req([])[0], hs, OppModel(), rng=rng)
        raised += out["action"] == "raise"
        played += out["action"] != "fold"
    assert raised / 22100 == pytest.approx(params.PF_OPEN_PCT, abs=0.01)
    assert played / 22100 == pytest.approx(params.PF_OPEN_PCT + params.PF_LIMP_PCT, abs=0.01)


def test_big_blind_vs_limp():
    out, req = decide(TOP, ["call"])
    assert req["to_call"] == 0 and out == {"action": "raise", "amount": 8}
    assert decide(TRASH, ["call"])[0] == {"action": "check"}
    assert decide(hand_at(0.40, 0.50), ["call"])[0] == {"action": "check"}


def test_big_blind_vs_open_ranges_and_3bet_size():
    out, _ = decide(TOP, [("raise", 6)])
    assert out == {"action": "raise", "amount": 18}                 # P3: 3x the open
    out, _ = decide(TOP, [("raise", 4)])
    assert out == {"action": "raise", "amount": 12}
    assert decide(TRASH, [("raise", 6)])[0] == {"action": "fold"}
    # never fold to a min-raise with a top-90% hand (price 25 %)
    for lo in (0.10, 0.2, 0.4, 0.6, 0.8):
        h = hand_at(lo, lo + 0.02)
        for seed in range(5):
            assert decide(h, [("raise", 4)], seed=seed)[0]["action"] in ("call", "raise"), h
    # vs 3x open: top ~70 % defends, the bottom folds
    assert decide(hand_at(0.40, 0.42), [("raise", 6)])[0] == {"action": "call"}
    assert decide(hand_at(0.20, 0.22), [("raise", 6)])[0] == {"action": "fold"}
    # vs an oversized open (to 20: 18 into 22, price 0.45): tighter
    assert decide(hand_at(0.40, 0.42), [("raise", 20)])[0] == {"action": "fold"}
    assert decide(hand_at(0.75, 0.77), [("raise", 20)])[0] == {"action": "call"}
    # a 3-bet that would commit > 40 % of the stack is a shove
    out, req = decide(TOP, [("raise", 30)])
    assert out == {"action": "raise", "amount": req["max_raise"]}


def test_defend_share_tracks_price():
    def share(seq):
        rng = random.Random(8)
        req, actor = preflop_req(seq)
        n = 0
        for t in combinations(range(0, 52), 3):
            out = P.decide(req, HandState(1, "big_blind", [fmt(c) for c in t]), OppModel(), rng=rng)
            n += out["action"] != "fold"
        return n / 22100
    s4, s6, s10 = share([("raise", 4)]), share([("raise", 6)]), share([("raise", 10)])
    assert s4 == pytest.approx(0.92, abs=0.015)
    assert s6 == pytest.approx(0.70, abs=0.015)
    assert s4 > s6 > s10


def test_facing_open_shove():
    out, req = decide(TOP, [("raise", 200)])
    assert req["legal_actions"] == ["fold", "call"] and out == {"action": "call"}
    assert decide(TRASH, [("raise", 200)])[0] == {"action": "fold"}
    assert decide(hand_at(0.5, 0.52), [("raise", 200)])[0] == {"action": "fold"}
    # widening: a frequent shover's range is wide, so a medium hand calls
    mid = hand_at(0.70, 0.72)
    assert decide(mid, [("raise", 200)])[0] == {"action": "fold"}
    maniac = Stats(hands=60, shove=0.9, pfr=0.9)
    assert decide(mid, [("raise", 200)], opp=maniac)[0] == {"action": "call"}


def test_shove_call_rule_is_pot_odds_vs_the_range():
    req, actor = preflop_req([("raise", 200)])
    s = P._Spot(req)
    assert P.allin_price(s) == pytest.approx(0.495)
    req, actor = preflop_req([("raise", 6), ("raise", 200)])
    assert P.allin_price(P._Spot(req)) == pytest.approx(0.485)
    w = params.PF_SHOVE_RANGE
    for k in range(0, 1755, 7):
        tri = next(t for t in combinations(range(52), 3) if canon3(t) == k)
        h = " ".join(fmt(c) for c in tri)
        out, _ = decide(h, [("raise", 200)])
        if P.PCT[k] < 1 - params.PF_VALUE_SHOVE_PCT:
            want = "call" if P._eq_vs_cls(k, w) >= 0.495 + params.PF_CALL_MARGIN else "fold"
            assert out["action"] == want, (h, P._eq_vs_cls(k, w))


def test_facing_a_3bet():
    out, req = decide(TOP, [("raise", 6), ("raise", 18)])
    assert req["raises_left"] == 1
    assert out == {"action": "raise", "amount": 40}                  # P3: 2.2x the 3-bet
    assert decide(hand_at(0.70, 0.72), [("raise", 6), ("raise", 18)])[0] == {"action": "call"}
    assert decide(hand_at(0.40, 0.42), [("raise", 6), ("raise", 18)])[0] == {"action": "fold"}
    # low trips never 4-bet
    out, _ = decide("7s 7h 7d", [("raise", 6), ("raise", 18)])
    assert out["action"] != "raise"


def test_continue_vs_3bet_share():
    rng = random.Random(9)
    req, _ = preflop_req([("raise", 6), ("raise", 18)])
    n = 0
    for t in combinations(range(52), 3):
        out = P.decide(req, HandState(1, "button", [fmt(c) for c in t]), OppModel(), rng=rng)
        n += out["action"] != "fold"
    assert n / 22100 == pytest.approx(0.38, abs=0.015)


def test_facing_a_4bet_calls_or_folds_by_realised_equity():
    out, req = decide(TOP, [("raise", 6), ("raise", 18), ("raise", 40)])
    assert req["raises_left"] == 0 and "raise" not in req["legal_actions"]
    assert out == {"action": "call"}
    assert decide(TRASH, [("raise", 6), ("raise", 18), ("raise", 40)])[0] == {"action": "fold"}
    # the rule: R_oop * equity vs their 4-bet range >= to_call / (pot + to_call)
    k = cls("Qs Js 9d")
    e = P._eq_vs_cls(k, params.PF_FOURBET_RANGE)
    want = "call" if params.PF_R_OOP * e >= 22 / 80 else "fold"
    assert decide("Qs Js 9d", [("raise", 6), ("raise", 18), ("raise", 40)])[0]["action"] == want
    # an all-in 4-bet is priced as an all-in
    out, req = decide(TRASH, [("raise", 6), ("raise", 18), ("raise", 200)])
    assert out == {"action": "fold"}
    assert decide(TOP, [("raise", 6), ("raise", 18), ("raise", 200)])[0] == {"action": "call"}


def test_limp_raise_lines():
    # button limps, BB raises to 8: the button continues by the price (limp hands are weak -> fold)
    limp = hand_at(1 - params.PF_OPEN_PCT - params.PF_LIMP_PCT + 0.025, 1 - params.PF_OPEN_PCT - 0.025)
    out, req = decide(limp, ["call", ("raise", 8)])
    assert req["raises_left"] == 2 and out == {"action": "fold"}
    # BB raised a limp, button 3-bets: the BB faces a 3-bet
    out, req = decide(TOP, ["call", ("raise", 8), ("raise", 24)])
    assert out["action"] == "raise" and out["amount"] == round(2.2 * 24)
    out, req = decide(TOP, ["call", ("raise", 8), ("raise", 24), ("raise", 53)])
    assert out == {"action": "call"}


def test_raise_missing_when_opponent_all_in():
    # short-stacked opponent all-in: raise is not legal, we only call/fold
    out, req = decide(TOP, [("raise", 50)], stacks=(50, 200))
    assert "raise" not in req["legal_actions"] and out == {"action": "call"}


def test_works_from_req_alone():
    for seq in ([], ["call"], [("raise", 6)], [("raise", 6), ("raise", 18)], [("raise", 200)]):
        out, req = decide(TOP, seq, with_hand=False)       # no hole cards: a safe action
        assert out["action"] in ("check", "call", "fold")
    req, _ = preflop_req([("raise", 6)])
    hs = HandState(1, None, ["As", "Ah", "Ks"])            # seat unknown: inferred from the history
    out = P.decide(req, hs, None, rng=random.Random(1))
    assert out == {"action": "raise", "amount": 18}
    req.pop("raises_left")                                   # raises counted from the history instead
    assert P.decide(req, hs, None, rng=random.Random(1)) == {"action": "raise", "amount": 18}


def test_exploit_hooks_off_with_the_stub_and_on_with_stats():
    stub = OppModel()
    mid_low = hand_at(0.03, 0.05)
    assert decide(mid_low, [], opp=stub)[0] == {"action": "fold"}
    nit = Stats(hands=50, fold_to_steal=0.8)
    assert decide(mid_low, [], opp=nit)[0] == {"action": "raise", "amount": 4}       # steal: min-raise to 4
    few = Stats(hands=5, fold_to_steal=0.8)                                            # not enough hands yet
    assert decide(mid_low, [], opp=few)[0] == {"action": "fold"}
    maniac = Stats(hands=50, pfr=0.9)
    assert decide(hand_at(0.40, 0.45), [], opp=maniac)[0] == {"action": "fold"}
    broken = Stats(hands=float("nan"))
    assert decide(TOP, [], opp=broken)[0] == {"action": "raise", "amount": 6}


def test_randomisation_is_bounded_and_seedable():
    cut = 1 - params.PF_OPEN_PCT
    h = hand_at(cut - 0.005, cut + 0.005)
    outs = {decide(h, [], seed=s)[0]["action"] for s in range(40)}
    assert outs <= {"raise", "call"} and len(outs) == 2
    assert [decide(h, [], seed=3)[0] for _ in range(3)] == [decide(h, [], seed=3)[0]] * 3


# ----------------------------------------------------------------------------------------------- property test
def test_random_preflop_requests_always_yield_legal_intents():
    """Random engine-consistent preflop sequences (random stacks, sizes, hole cards, partial hand states): every
    intent is already legal, so make_legal leaves it unchanged."""
    rng = random.Random(2026)
    n_req = 0
    for _ in range(2500):
        stacks = (200, 200) if rng.random() < 0.7 else (rng.randint(3, 200), rng.randint(3, 200))
        seq = []
        while True:
            req, actor, over = replay(seq, stacks)
            if over:
                break
            hole = " ".join(fmt(c) for c in rng.sample(range(52), 3))
            hs = hand_for(hole, actor) if rng.random() < 0.9 else HandState(1)
            opp = OppModel() if rng.random() < 0.7 else Stats(hands=rng.choice([0, 10, 50]), shove=rng.random(),
                                                             pfr=rng.random(), fold_to_steal=rng.random(),
                                                             vpip=rng.random(), fold_to_bet=rng.random(),
                                                             three_bet=rng.random())
            out = P.decide(req, hs, opp, rng=rng)
            check_legal(out, req)
            n_req += 1
            mine = rng.random() < 0.5                       # continue with our intent or a random legal action
            a = out["action"] if mine else rng.choice(req["legal_actions"])
            if a == "raise":
                amt = out["amount"] if mine else rng.randint(req["min_raise"], req["max_raise"])
                seq.append(("raise", amt))
            else:
                seq.append(a)
    assert n_req > 4000


def test_decide_is_fast():
    import time
    reqs = [preflop_req(s)[0] for s in ([], ["call"], [("raise", 6)], [("raise", 6), ("raise", 18)])]
    hs = hand_for("Qs Jh 9d", 0)
    t = time.perf_counter()
    for _ in range(500):
        for r in reqs:
            P.decide(r, hs, OppModel(), rng=random.Random(1))
    assert (time.perf_counter() - t) / 2000 < 0.001


# ----------------------------------------------------------------------------------------------- brain + engine
def test_brain_routes_preflop_and_falls_back(monkeypatch):
    b = Brain()
    b.on_new_hand({"hand_id": 1, "seat": "button", "hole_cards": ["As", "Ah", "Ks"]})
    req, _ = preflop_req([])
    assert b.act(req) == {"action": "raise", "amount": 6}

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(P, "decide", boom)
    assert b.act(req) == {"action": "call"}                         # v0 fallback
    flop = dict(req, street="flop", board=["2c", "7d", "9h"], legal_actions=["check", "raise"], to_call=0)
    import betting
    monkeypatch.setattr(betting, "decide", boom)                     # postflop (W5) failing -> v0 fallback too
    assert b.act(flop) == {"action": "check"}


@pytest.mark.parametrize("opp", ["random", "starter", "shove"])
def test_engine_match_no_notices(tmp_path, opp):
    path = {"random": RANDOM_BOT, "starter": STARTER, "shove": TESTS / "shove_bot.py"}[opp]
    out, res = run_match(BOT, path, seed=31, log_dir=tmp_path, hands=200)
    assert_clean(out, res)
    log = (tmp_path / "match.log").read_text(encoding="utf-8")
    assert "Ar" in log or "Br" in log                                # somebody raised preflop
