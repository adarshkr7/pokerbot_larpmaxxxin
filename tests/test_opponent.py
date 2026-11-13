"""Opponent model (strategies/06_opponent_modelling.md M1, M2, M4; 05/B7 size-aware narrowing; 07/G2 MDF).
Every random draw is seeded."""
import math
import os
import random
from concurrent.futures import ThreadPoolExecutor

import pytest

import betting as B
import opp_sim as S
import params
import preflop as P
import replay
from brain import Brain
from engine_util import TESTS, assert_clean, run_match
from opponent import OppModel, aggression_factor, corr, hand_observations, ramp, shrink


def H(street, actor, action, amount=None):
    e = {"street": street, "actor": actor, "action": action}
    if amount is not None:
        e["amount"] = amount
    return e


def result(history, result="fold", opp_hole=None, opp_discard=None, board=None):
    return {"type": "hand_result", "hand_id": 1, "result": result, "net": 0, "board": board or [],
            "my_hole_cards": ["2s", "3h"], "opp_hole_cards": opp_hole, "opp_discard": opp_discard,
            "history": history}


def obs(history, **kw):
    got = hand_observations(result(history, **kw))
    assert got is not None
    return got[0]


def no_decay():
    return OppModel(half_life=0)            # lam = 1: plain counts


# ----------------------------------------------------------------------------------------------- replay
def test_replay_reconstructs_stacks_and_recognises_all_ins():
    hist = [H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6),
            H("flop", "opp", "check"), H("flop", "me", "raise", 8), H("flop", "opp", "raise", 194),
            H("flop", "me", "call", 194)]
    ev, me_btn = replay.walk(hist)
    assert me_btn is True
    assert [e["pot"] for e in ev] == [3, 8, 12, 12, 20, 214]
    shove = ev[4]
    assert shove["max_raise"] == 194 and shove["allin"] and shove["to_call"] == 8 and shove["aggr"] == "me"
    assert not ev[3]["allin"]
    # preflop open shove by the button (opponent): 200 is the max raise
    ev, me_btn = replay.walk([H("preflop", "opp", "raise", 200), H("preflop", "me", "fold")])
    assert me_btn is False and ev[0]["allin"] and ev[0]["raise_legal"] and ev[0]["max_raise"] == 200
    # facing an all-in, a re-raise is not legal
    ev, _ = replay.walk([H("preflop", "me", "raise", 200), H("preflop", "opp", "call", 200)])
    assert ev[1]["raise_legal"] is False


@pytest.mark.parametrize("bad", [None, [], "x", [1], [H("flop", "me", "check")],
                                 [H("preflop", "me", "raise")], [H("preflop", "me", "raise", 1)],
                                 [H("preflop", "me", "raise", 201)], [H("preflop", "me", "check")],
                                 [H("preflop", "me", "call"), H("preflop", "opp", "jam")],
                                 [H("preflop", "me", "call"), H("flop", "opp", "check"), H("preflop", "me", "check")],
                                 [H("preflop", "me", "raise", True)]])
def test_replay_rejects_malformed_histories(bad):
    assert replay.walk(bad) is None


# ----------------------------------------------------------------------------------------------- M1 definitions
def test_vpip_counts_calls_and_raises_but_not_the_big_blind_checking_its_option():
    # we limp on the button, they check the big blind: a decision, not voluntary
    o = obs([H("preflop", "me", "call", 2), H("preflop", "opp", "check"), H("flop", "opp", "check"),
             H("flop", "me", "check")])
    assert o["vpip"] == (0.0, 1.0) and o["pfr"] == (0.0, 1.0)
    # they limp on the button
    o = obs([H("preflop", "opp", "call", 2), H("preflop", "me", "check")])
    assert o["vpip"] == (1.0, 1.0) and o["pfr"] == (0.0, 1.0)
    # they call our open in the big blind
    o = obs([H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6), H("flop", "opp", "check"),
             H("flop", "me", "check")])
    assert o["vpip"] == (1.0, 1.0)
    # they fold the button: a decision with no money in
    o = obs([H("preflop", "opp", "fold")])
    assert o["vpip"] == (0.0, 1.0) and o["pfr"] == (0.0, 1.0) and o["shove"] == (0.0, 1.0)
    # we fold the button: they never decided -> no opportunity at all
    o = obs([H("preflop", "me", "fold")])
    assert "vpip" not in o and "pfr" not in o and "shove" not in o


def test_three_bet_and_shove_are_separate_counters():
    # open shove by them: a shove, not a 3-bet (no raise of ours to answer)
    o = obs([H("preflop", "opp", "raise", 200), H("preflop", "me", "fold")])
    assert o["shove"] == (1.0, 1.0) and o["pfr"] == (1.0, 1.0) and "three_bet" not in o
    # small 3-bet of our open: a 3-bet, not a shove
    o = obs([H("preflop", "me", "raise", 6), H("preflop", "opp", "raise", 18), H("preflop", "me", "fold")])
    assert o["three_bet"] == (1.0, 1.0) and o["shove"] == (0.0, 1.0)
    # 3-bet all-in: both
    o = obs([H("preflop", "me", "raise", 6), H("preflop", "opp", "raise", 200), H("preflop", "me", "fold")])
    assert o["three_bet"] == (1.0, 1.0) and o["shove"] == (1.0, 1.0)
    # they called our open: a 3-bet opportunity not taken
    o = obs([H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6), H("flop", "opp", "check"),
             H("flop", "me", "check")])
    assert o["three_bet"] == (0.0, 1.0)
    # our open was all-in: they could not re-raise -> no 3-bet opportunity, and no shove opportunity
    o = obs([H("preflop", "me", "raise", 200), H("preflop", "opp", "call", 200)])
    assert "three_bet" not in o and "shove" not in o
    # they opened and we 3-bet; their 4-bet is not a "3-bet"
    o = obs([H("preflop", "opp", "raise", 6), H("preflop", "me", "raise", 18), H("preflop", "opp", "raise", 40),
             H("preflop", "me", "fold")])
    assert "three_bet" not in o and o["pfr"] == (1.0, 1.0)


def test_fold_to_steal_only_directly_facing_our_first_button_raise():
    o = obs([H("preflop", "me", "raise", 6), H("preflop", "opp", "fold")])
    assert o["fold_to_steal"] == (1.0, 1.0)
    o = obs([H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6), H("flop", "opp", "check"),
             H("flop", "me", "raise", 8), H("flop", "opp", "fold")])
    assert o["fold_to_steal"] == (0.0, 1.0)                 # the postflop fold does not count
    # they 3-bet, then fold to our 4-bet: an answered steal, not a fold to it
    o = obs([H("preflop", "me", "raise", 6), H("preflop", "opp", "raise", 18), H("preflop", "me", "raise", 40),
             H("preflop", "opp", "fold")])
    assert o["fold_to_steal"] == (0.0, 1.0) and o["three_bet"] == (1.0, 1.0)
    # we limp, they raise, we raise, they fold: not a steal
    o = obs([H("preflop", "me", "call", 2), H("preflop", "opp", "raise", 8), H("preflop", "me", "raise", 24),
             H("preflop", "opp", "fold")])
    assert "fold_to_steal" not in o
    # they are the button: no steal of ours
    o = obs([H("preflop", "opp", "call", 2), H("preflop", "me", "raise", 8), H("preflop", "opp", "fold")])
    assert "fold_to_steal" not in o and o["three_bet"] == (0.0, 1.0)


def test_fold_to_bet_opportunities_postflop():
    hist = [H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6),
            H("flop", "opp", "check"), H("flop", "me", "raise", 8), H("flop", "opp", "call", 8),
            H("turn", "opp", "raise", 10), H("turn", "me", "raise", 40), H("turn", "opp", "fold")]
    o = obs(hist)
    assert o["fold_to_bet"] == (1.0, 2.0)                   # faced our flop bet (call) and our turn raise (fold)
    assert o["fold_to_bet_flop"] == (0.0, 1.0) and o["fold_to_bet_turn"] == (1.0, 1.0)
    assert o["agg_freq"] == (1.0, 3.0)                      # check, call, bet
    ex = hand_observations(result(hist))[1]
    assert ex["af"] == (1, 1)
    assert ex["mdf"] == [(False, pytest.approx(28 / 38))]    # their opening turn bet (10 into 28): we raised
    hist2 = hist[:6] + [H("turn", "me", "fold")]
    ex2 = hand_observations(result(hist2))[1]
    assert ex2["mdf"] == [(True, pytest.approx(28 / 38))]    # their 10 into 28: MDF = 28 / 38


def test_allin_frequency_any_street():
    o = obs([H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6), H("flop", "opp", "raise", 194),
             H("flop", "me", "fold")])
    assert o["allin"] == (1.0, 1.0) and o["shove"] == (0.0, 1.0)


# ----------------------------------------------------------------------------------------------- independent check
def _independent(results):
    """Counts of the M1 definitions on engine histories, written separately from opponent.py / replay.py: chips
    tracked as committed totals only (stacks 200, blinds 1/2)."""
    c = {k: [0, 0] for k in ("vpip", "pfr", "shove", "fold_to_bet", "fold_to_steal", "three_bet")}
    for msg, _ in results:
        hist = msg["history"]
        btn = hist[0]["actor"]
        com = {btn: 1, ("opp" if btn == "me" else "me"): 2}
        street, street_bet = "preflop", {btn: 1, ("opp" if btn == "me" else "me"): 2}
        n_raises = 1
        last_raiser = None
        opp_dec = opp_vol = opp_raise = opp_shove = opp_could = False
        first_raise_seen = False
        for i, h in enumerate(hist):
            if h["street"] != street:
                street, street_bet, n_raises, last_raiser = h["street"], {"me": 0, "opp": 0}, 0, None
            a, act = h["actor"], h["action"]
            other = "opp" if a == "me" else "me"
            if a == "opp" and street == "preflop":
                opp_dec = True
                cover = min(200 - com["opp"] + street_bet["opp"], 200 - com["me"] + street_bet["me"])
                if n_raises < 4 and cover > street_bet["me"]:
                    opp_could = True
            if a == "opp" and street != "preflop" and last_raiser == "me":
                c["fold_to_bet"][1] += 1
                c["fold_to_bet"][0] += act == "fold"
            if act == "raise" and not first_raise_seen:
                first_raise_seen = True
                if a == "me" and i + 1 < len(hist) and hist[i + 1]["street"] == "preflop" == street:
                    nxt = hist[i + 1]
                    cover = min(200 - com["opp"] + street_bet["opp"], 200 - com["me"] + street_bet["me"])
                    if n_raises + 1 < 4 and cover > h["amount"]:
                        c["three_bet"][1] += 1
                        c["three_bet"][0] += nxt["action"] == "raise"
                    if i == 0:
                        c["fold_to_steal"][1] += 1
                        c["fold_to_steal"][0] += nxt["action"] == "fold"
            if act == "call":
                com[a] += street_bet[other] - street_bet[a]
                street_bet[a] = street_bet[other]
            elif act == "raise":
                com[a] += h["amount"] - street_bet[a]
                street_bet[a] = h["amount"]
                n_raises += 1
                last_raiser = a
                if a == "opp" and street == "preflop":
                    opp_raise = True
                    opp_shove = opp_shove or com["opp"] == 200 or com["me"] + (h["amount"] - street_bet["me"]) >= 200
            if a == "opp" and street == "preflop" and act in ("call", "raise"):
                opp_vol = True
        if opp_dec:
            c["vpip"][1] += 1
            c["vpip"][0] += opp_vol
            c["pfr"][1] += 1
            c["pfr"][0] += opp_raise
        if opp_could:
            c["shove"][1] += 1
            c["shove"][0] += opp_shove
    return c


@pytest.mark.parametrize("opp_cls", [S.RandomActs, S.Maniac, S.Sensible, S.Nit])
def test_stats_match_an_independent_counter_on_engine_histories(opp_cls):
    res = S.play(S.Hero(5), opp_cls(6), 300, seed=7)
    want = _independent(res)
    got = {}
    for msg, _ in res:
        for name, (k, n) in hand_observations(msg)[0].items():
            g = got.setdefault(name, [0.0, 0.0])
            g[0] += k
            g[1] += n
    for name, (k, n) in want.items():
        assert got.get(name, [0.0, 0.0]) == [float(k), float(n)], name
    assert want["vpip"][1] > 100 and want["fold_to_bet"][1] > 20
    m = no_decay()
    for msg, seat in res:
        m.observe_hand(msg, seat)
    assert m.stat("hands") == 300
    k, n = want["vpip"]
    assert m.stat("vpip") == pytest.approx(shrink(k, n, 0.65, 12))


# ----------------------------------------------------------------------------------------------- arithmetic
def test_shrinkage_arithmetic():
    assert shrink(8, 8, 0.12, 10) == pytest.approx(9.2 / 18)           # the 06/M1 example: 0.511
    assert shrink(0, 0, 0.42, 12) == pytest.approx(0.42)
    m = no_decay()
    assert m.stat("shove") == pytest.approx(0.12) and m.stat("vpip") == pytest.approx(0.65)
    assert m.stat("hands") == 0 and m.stat("no_such_stat") == 0.0
    for _ in range(3):
        m.observe_hand(result([H("preflop", "opp", "raise", 200), H("preflop", "me", "fold")]))
    assert m.stat("shove") == pytest.approx((3 + 4 * 0.12) / (3 + 4))   # the configured shove strength N0 = 4


def test_aggression_factor_pseudo_counts():
    assert aggression_factor(0, 0) == pytest.approx(1.5)
    assert aggression_factor(10, 5) == pytest.approx((10 + 22.5) / 20)
    assert aggression_factor(0, 1000) < 0.03 and aggression_factor(1000, 0) > 60
    m = no_decay()
    m.observe_hand(result([H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6),
                           H("flop", "opp", "raise", 8), H("flop", "me", "call", 8), H("turn", "opp", "check"),
                           H("turn", "me", "raise", 10), H("turn", "opp", "call", 10), H("river", "opp", "check"),
                           H("river", "me", "check")]))
    assert m.stat("aggression") == pytest.approx((1 + 22.5) / (1 + 15))


def test_correlation_formula_and_degenerate_cases():
    assert corr(0, 0, 0, 0, 0, 0) == 0.0
    assert corr(1, 1, 1, 1, 1, 1) == 0.0                                  # one observation
    xs, ys = [1.0] * 8, [float(i) for i in range(8)]                     # x has zero variance
    sums = lambda xs, ys: (len(xs), sum(xs), sum(ys), sum(x * x for x in xs), sum(y * y for y in ys),
                           sum(x * y for x, y in zip(xs, ys)))
    assert corr(*sums(xs, ys)) == 0.0
    assert corr(*sums(ys, xs)) == 0.0
    xs = [float(i) for i in range(8)]
    assert corr(*sums(xs, [2 * x + 1 for x in xs])) == pytest.approx(8 / 16)        # r = 1 shrunk n / (n + 8)
    assert corr(*sums(xs, [-x for x in xs])) == pytest.approx(-0.5)
    rng = random.Random(3)
    a = [rng.random() for _ in range(40)]
    b = [x + rng.random() for x in a]
    mx, my = sum(a) / 40, sum(b) / 40
    r = (sum((x - mx) * (y - my) for x, y in zip(a, b))
         / math.sqrt(sum((x - mx) ** 2 for x in a) * sum((y - my) ** 2 for y in b)))
    assert corr(*sums(a, b)) == pytest.approx(40 * r / 48)


def test_ramp():
    assert ramp(0.5, 0.4, 0.6) == pytest.approx(0.5) and ramp(0.3, 0.4, 0.6) == 0 and ramp(0.9, 0.4, 0.6) == 1
    assert ramp(0.1, 0.3, 0.15) == 1 and ramp(0.4, 0.3, 0.15) == 0                  # decreasing


# ----------------------------------------------------------------------------------------------- tau / toss-lowest
SHOW = [H("preflop", "me", "call", 2), H("preflop", "opp", "check"), H("flop", "opp", "check"), H("flop", "me", "check"),
        H("turn", "opp", "check"), H("turn", "me", "check"), H("river", "opp", "check"), H("river", "me", "check")]
BOARD = ["Ks", "8d", "3c", "2h", "Jc"]


def show(kept, disc, board=BOARD):
    return result(SHOW, result="showdown", opp_hole=kept, opp_discard=disc, board=board)


def test_tau_and_toss_lowest_on_constructed_showdowns():
    # flop Ks 8d 3c; triple Kd Qh 4s: keeping Kd Qh (top pair) is the max-S keep and tosses the lowest card
    _, ex = hand_observations(show(["Kd", "Qh"], "4s"))
    assert ex["show"][0] is True and ex["show"][1] is True
    # keeping Qh 4s and tossing Kd: neither
    _, ex = hand_observations(show(["Qh", "4s"], "Kd"))
    assert ex["show"][0] is False and ex["show"][1] is False
    # triple 4s 4h Ah: keeping the pair of 4s tosses the ace (max-S, not lowest)
    _, ex = hand_observations(show(["4s", "4h"], "Ah"))
    assert ex["show"][0] is True and ex["show"][1] is False
    # suit order of the engine default (s < h < d < c): 4c 4s Kd, discarding 4s is the lowest
    _, ex = hand_observations(show(["4c", "Kd"], "4s"))
    assert ex["show"][1] is True
    _, ex = hand_observations(show(["4s", "Kd"], "4c"))
    assert ex["show"][1] is False
    # the model: priors with no showdowns; toss_lowest stays 0 until 6 showdowns
    m = no_decay()
    assert m.stat("discard_tau") == pytest.approx(0.9) and m.stat("toss_lowest") == 0.0
    for i in range(5):
        m.observe_hand(show(["Qh", "4s"], "Kd") if i % 2 else show(["Kd", "Qh"], "4s"))
    assert m.stat("toss_lowest") == 0.0
    m.observe_hand(show(["Kd", "Qh"], "4s"))
    assert m.stat("showdowns") == 6
    assert m.stat("toss_lowest") == pytest.approx(4 / 6)
    assert m.stat("discard_tau") == pytest.approx((4 + 6 * 0.9) / 12)
    # a random discarder: tau far below the toss-lowest bot's
    rng = random.Random(1)
    deck = [r + s for r in "23456789TJQKA" for s in "shdc"]
    rnd, low = no_decay(), no_decay()
    for _ in range(300):
        c = rng.sample(deck, 8)
        triple, board = c[:3], c[3:]
        d = rng.choice(triple)
        rnd.observe_hand(show([x for x in triple if x != d], d, board))
        d = min(triple, key=lambda x: ("23456789TJQKA".index(x[0]), "shdc".index(x[1])))
        low.observe_hand(show([x for x in triple if x != d], d, board))
    assert rnd.stat("discard_tau") < 0.45 and 0.6 < low.stat("discard_tau") < 0.8
    assert low.stat("toss_lowest") == 1.0 and rnd.stat("toss_lowest") < 0.45


def test_showdown_with_bad_cards_is_not_counted():
    m = no_decay()
    for bad in (show(["Kd", "Kd"], "4s"), show(["Kd", "Qh"], "Ks"), show(["Kd"], "4s"), show(["Kd", "Qh"], None),
                show(["Kd", "Qh"], "4s", board=BOARD[:4]), show(["Kd", "Qh"], "4x")):
        m.observe_hand(bad)
    assert m.stat("showdowns") == 0 and m.stat("hands") == 6          # the actions still count


# ----------------------------------------------------------------------------------------------- M2 archetypes
def weights_over(policy, hands, seed, model=None):
    m = model or OppModel()
    out = []
    for msg, seat in S.play(S.Hero(seed), policy, hands, seed):
        m.observe_hand(msg, seat)
        out.append(m.archetype_weights())
    return m, out


def test_weights_sum_to_one_and_start_neutral():
    m = OppModel()
    assert m.archetype_weights() == {"station": 0.0, "nit": 0.0, "random": 0.0, "maniac": 0.0, "neutral": 1.0}
    for cls in (S.Station, S.Shover, S.RandomBot, S.RandomActs, S.Nit, S.Maniac, S.Sensible):
        _, ws = weights_over(cls(4), 60, 4)
        for w in ws:
            assert set(w) == {"station", "nit", "random", "maniac", "neutral"}
            assert sum(w.values()) == pytest.approx(1.0) and min(w.values()) >= 0.0


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_archetypes_converge_on_scripted_opponents(seed):
    _, ws = weights_over(S.Station(seed), 120, seed)
    assert ws[4]["neutral"] > 0.5 and ws[-1]["station"] > 0.9
    _, ws = weights_over(S.Shover(seed), 30, seed)
    assert ws[0]["neutral"] == 1.0 and ws[9]["maniac"] > 0.9
    _, ws = weights_over(S.Maniac(seed), 200, seed)
    assert sum(w["maniac"] for w in ws[100:]) / 100 > 0.6
    _, ws = weights_over(S.Nit(seed), 200, seed)
    assert sum(w["nit"] for w in ws[60:]) / 140 > 0.4
    _, ws = weights_over(S.RandomBot(seed), 300, seed)          # random_bot.py's behaviour
    assert ws[20]["random"] < 0.1 and sum(w["random"] for w in ws[150:]) / 150 > 0.25
    assert max(w["random"] for w in ws) > 0.6
    assert max(w["station"] + w["nit"] for w in ws[100:]) < 0.5
    _, ws = weights_over(S.RandomActs(seed), 300, seed)         # uniform actions: few showdowns -> slow, cautious
    assert ws[30]["random"] < 0.3 and max(w["station"] + w["nit"] for w in ws[100:]) < 0.5


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_a_sensible_opponent_stays_mostly_neutral(seed):
    _, ws = weights_over(S.Sensible(seed), 240, seed)
    assert min(w["neutral"] for w in ws) > 0.7
    assert sum(w["neutral"] for w in ws) / len(ws) > 0.9


def test_weights_move_smoothly():
    for cls in (S.Station, S.Nit, S.RandomBot, S.RandomActs, S.Sensible):
        _, ws = weights_over(cls(9), 200, 9)
        for a, b in zip(ws[20:], ws[21:]):
            assert max(abs(a[k] - b[k]) for k in a) < 0.3


def test_style_switch_mid_leg_is_tracked():
    m, ws = weights_over(S.Station(11), 120, 11)
    assert ws[-1]["station"] > 0.9
    m, ws = weights_over(S.Maniac(12), 150, 12, model=m)
    assert ws[-1]["station"] < 0.1 and ws[-1]["maniac"] > 0.3
    assert m.stat("aggression") > 1.2
    # without forgetting the station stats would still dominate the same evidence for much longer
    m2, ws2 = weights_over(S.Station(11), 120, 11, model=OppModel(half_life=1e9))
    m2, ws2 = weights_over(S.Maniac(12), 150, 12, model=m2)
    assert m2.stat("aggression") < m.stat("aggression")


# ----------------------------------------------------------------------------------------------- robustness
BAD_RESULTS = [None, 7, "hand_result", {}, {"type": "hand_result"}, {"history": None}, {"history": "x"},
               {"history": [None]}, {"history": [{"street": "preflop"}]},
               {"history": [H("preflop", "opp", "raise", "200")]},
               {"history": [H("preflop", "opp", "raise", 200.5)]},
               {"history": [H("river", "opp", "raise", 20)]},
               {"history": [H("preflop", "opp", "fold")], "result": "showdown", "opp_hole_cards": "AsKs",
                "opp_discard": 5, "board": None},
               {"history": [H("preflop", "opp", "call", 2), H("preflop", "me", "check")], "result": "showdown",
                "opp_hole_cards": [None, 3], "opp_discard": "As", "board": ["As"] * 5}]


def test_malformed_results_never_raise_and_do_not_corrupt_counts():
    m = no_decay()
    good = result([H("preflop", "me", "raise", 6), H("preflop", "opp", "fold")])
    m.observe_hand(good)
    before = (dict(m._k), dict(m._n), m.stat("hands"))
    for bad in BAD_RESULTS[:-2]:
        m.observe_hand(bad)
        m.observe_showdown(bad)
    assert (dict(m._k), dict(m._n), m.stat("hands")) == before
    for bad in BAD_RESULTS[-2:]:                 # valid histories, broken showdown fields: actions only
        m.observe_hand(bad)
    assert m.stat("hands") == 3 and m.stat("showdowns") == 0
    for name in ("vpip", "pfr", "shove", "aggression", "size_corr", "discard_tau", "toss_lowest", "mdf_tilt", "x"):
        assert math.isfinite(m.stat(name))
    assert m.archetype_weights()["neutral"] == pytest.approx(1.0)


def test_brain_feeds_the_model_and_swallows_its_errors():
    b = Brain()
    b.on_new_hand({"hand_id": 1, "seat": "button", "hole_cards": ["As", "Kd", "2c"]})
    b.on_hand_result(result([H("preflop", "me", "raise", 6), H("preflop", "opp", "fold")]))
    assert b.opp.stat("hands") == 1 and b.hand is None

    class Boom(OppModel):
        def observe_hand(self, msg, seat=None):
            raise RuntimeError("model bug")
    b.opp = Boom()
    b.on_hand_result(result([H("preflop", "opp", "fold")]))       # must not raise
    assert b.hand is None and b.leg.hands_done == 2


def test_the_model_is_cheap():
    import time
    res = S.play(S.Hero(1), S.Maniac(2), 200, 3)
    m = OppModel()
    t = time.perf_counter()
    for msg, seat in res:
        m.observe_hand(msg, seat)
        m.archetype_weights()
        m.stat("mdf_tilt")
    assert (time.perf_counter() - t) / len(res) < 0.001


def test_river_pit_counts_only_shown_pairs_in_the_stored_range():
    import numpy as np
    from cards import pair_index, parse
    m = no_decay()
    assert m.stat("river_pit") == 0.5
    hist = [H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6), H("river", "opp", "raise", 8),
            H("river", "me", "call", 8)]
    board = ["2c", "7d", "9h", "Ks", "4s"]
    shown = ["Ah", "3d"]
    pi = pair_index(parse("Ah"), parse("3d"))
    pit = (np.array([5, pi, 7]), np.array([0.9, 0.1, 0.4]))
    sd = result(hist, "showdown", opp_hole=shown, opp_discard="5c", board=board)
    for _ in range(6):
        m.observe_hand(sd)
        m.observe_pit(sd, pit)
    assert m.stat("river_pit") == pytest.approx((6 * 0.1 + params.OPP_PIT_N0 * 0.5) / (6 + params.OPP_PIT_N0))
    before = m.stat("river_pit")
    m.observe_pit(result(hist), pit)                                  # no showdown: nothing
    m.observe_pit(sd, None)
    m.observe_pit(sd, (np.array([1, 2]), np.array([0.0, 0.0])))       # their pair not in the range: nothing
    m.observe_pit("junk", pit)
    m.observe_pit(sd, "junk")
    assert m.stat("river_pit") == before


# ----------------------------------------------------------------------------------------------- consumers
def test_shove_estimate_is_read_from_the_first_hand():
    jam = result([H("preflop", "opp", "raise", 200), H("preflop", "me", "fold")])
    m = OppModel()
    widths = [P._Reads(m).shove_range()]
    for _ in range(8):
        m.observe_hand(jam)
        widths.append(P._Reads(m).shove_range())
    assert widths[0] == pytest.approx(params.PF_SHOVE_RANGE)
    assert widths == sorted(widths)
    assert widths[1] == pytest.approx((1 + 0.48) / 5) and widths[3] == pytest.approx(0.495, abs=0.003)
    assert widths[8] == pytest.approx(0.70, abs=0.005)

    def call_share(width):                       # big blind facing an open shove: price 0.495
        return sum(P.MULT[k] for k in range(P.N_CLASSES) if P._eq_vs_cls(k, width) >= 0.495) / P.N_HANDS
    shares = [call_share(w) for w in widths]
    assert shares[0] == pytest.approx(0.076, abs=0.005)          # unknown: top 7.6%
    assert shares[1] == pytest.approx(0.115, abs=0.005)          # 1 shove: still only strong hands
    assert shares[3] == pytest.approx(0.20, abs=0.01)            # 3 shoves: top 20%
    assert shares[8] == pytest.approx(0.30, abs=0.01)            # 8 shoves: top 30% (vs random: 48%)
    from test_preflop import TRASH, decide, hand_at
    one = OppModel()
    one.observe_hand(jam)
    assert decide(TRASH, [("raise", 200)], opp=one)[0] == {"action": "fold"}
    assert decide(hand_at(0.50, 0.52), [("raise", 200)], opp=one)[0] == {"action": "fold"}
    assert decide(hand_at(0.50, 0.52), [("raise", 200)], opp=m)[0] == {"action": "fold"}


def test_size_mult_is_monotone_and_bounded():
    xs = [0.0, 0.1, 0.33, 0.5, 0.66, 1.0, 2.0, 5.0, 50.0]
    ms = [B.size_mult(x) for x in xs]
    assert ms == sorted(ms)
    assert ms[0] == params.BET_SIZE_LO and ms[-1] == params.BET_SIZE_HI
    assert B.size_mult(0.66) == pytest.approx(1.0)
    assert B.size_mult(50.0, allin=True) == pytest.approx(params.BET_SIZE_HI * params.BET_SIZE_ALLIN)
    assert B.size_mult(50.0, True, damp=0.0) == 1.0 and B.size_mult(0.1, damp=0.0) == params.BET_SIZE_LO
    assert B.size_mult(50.0, True, damp=0.5) == pytest.approx(1 + 0.5 * (params.BET_SIZE_HI * params.BET_SIZE_ALLIN - 1))


def test_frequent_all_ins_damp_the_size_amplification():
    assert B._Opp(OppModel()).size_damp == 1.0
    m = OppModel()
    for msg, seat in S.play(S.Hero(3), S.Maniac(4), 60, 3):
        m.observe_hand(msg, seat)
    assert m.stat("allin") > 0.3 and B._Opp(m).size_damp == 0.0
    s = OppModel()
    for msg, seat in S.play(S.Hero(3), S.Sensible(4), 60, 3):
        s.observe_hand(msg, seat)
    assert B._Opp(s).size_damp > 0.8


def test_tilts_grow_with_the_bet_size():
    pre = [H("preflop", "me", "raise", 6), H("preflop", "opp", "call", 6)]
    small = B._tilts(pre + [H("flop", "opp", "raise", 2)])["flop"]
    pot = B._tilts(pre + [H("flop", "opp", "raise", 12)])["flop"]
    jam = B._tilts(pre + [H("flop", "opp", "raise", 194)])["flop"]
    assert small < B._street_tilt(["raise"]) < pot < jam <= params.BET_TILT_MAX
    assert B._tilts(pre + [H("flop", "opp", "raise", 8)])["flop"] == pytest.approx(params.BET_TILT_RAISE, rel=0.05)
    # unreplayable history -> the size-blind tilt
    assert B._tilts([H("flop", "opp", "raise")])["flop"] == B._street_tilt(["raise"])


def test_a_shove_narrows_their_range_more_than_a_small_bet():
    from test_betting import req_
    from state import HandState
    from cards import parse
    import numpy as np
    hs = HandState(1, "button", ["As", "7d", "2c"])
    hs.hole = [parse("As"), parse("7d")]
    hs.board = [parse(c) for c in ("Kh", "9c", "4d", "5s")]
    hs.opp_discard = "3h"
    hs.rebuild_dead()
    pre = [H("flop", "opp", "check"), H("flop", "me", "check")]       # req_ prepends the preflop (open, call)

    def top_mass(turn_bet):
        r = req_("turn", ["Kh", "9c", "4d", "5s"], 12 + turn_bet, opp_bet=turn_bet,
                 history=pre + [H("turn", "opp", "raise", turn_bet)])
        B._HC.clear()
        B.opp_range(r, hs, OppModel())
        w, idx, v, _ = B._range_for(r, hs, B._Opp(OppModel()), "turn")
        ww = w[idx]
        return float((ww * (v >> 20)).sum() / ww.sum())          # mean hand category of their range
    assert top_mass(4) < top_mass(8) < top_mass(194)


def test_mdf_diagnostic_relaxes_the_tilt_only_vs_aggressive_opponents():
    bet_fold = result([H("preflop", "me", "call", 2), H("preflop", "opp", "check"), H("flop", "opp", "raise", 4),
                       H("flop", "me", "fold")])
    shove = result([H("preflop", "opp", "raise", 200), H("preflop", "me", "fold")])
    passive = result([H("preflop", "me", "call", 2), H("preflop", "opp", "check"), H("flop", "opp", "check"),
                      H("flop", "me", "raise", 4), H("flop", "opp", "call", 4), H("turn", "opp", "check"),
                      H("turn", "me", "check"), H("river", "opp", "check"), H("river", "me", "check")])
    calm = OppModel()
    for i in range(80):
        calm.observe_hand(bet_fold if i % 2 else passive)
    assert calm.stat("aggression") < 2.0
    assert calm.stat("mdf_tilt") == 1.0                         # we over-fold but they are not aggressive
    wild = OppModel()
    for i in range(80):
        wild.observe_hand(bet_fold if i % 2 else shove)
    assert wild.archetype_weights()["maniac"] > 0.4
    assert params.BET_MDF_MULT_LO <= wild.stat("mdf_tilt") < 0.75
    few = OppModel()
    for i in range(16):
        few.observe_hand(bet_fold if i % 2 else shove)
    assert few.stat("mdf_tilt") == 1.0                          # fewer than 15 bets: no evidence yet

    class NoMdf(OppModel):
        def stat(self, name):
            return 1.0 if name == "mdf_tilt" else wild.stat(name)

        def archetype_weights(self):
            return wild.archetype_weights()
    assert B._Opp(wild).tilt_mult == pytest.approx(B._Opp(NoMdf()).tilt_mult * wild.stat("mdf_tilt"))


# ----------------------------------------------------------------------------------------------- engine
SPARRING = ["station_bot.py", "nit_bot.py", "maniac_bot.py", "shove_bot.py"]


def test_engine_runs_vs_sparring_bots_have_no_notices(tmp_path):
    def one(name):
        d = tmp_path / name
        out, res = run_match(TESTS.parent / "bot" / "bot.py", TESTS / name, seed=21, log_dir=d, hands=120)
        return name, d, out, res
    with ThreadPoolExecutor(max(1, min(4, (os.cpu_count() or 2) // 2))) as ex:
        runs = list(ex.map(one, SPARRING))
    for name, d, out, res in runs:
        assert_clean(out, res)
        for k in (1, 2):
            text = (d / f"A_leg{k}_stderr.txt").read_text(errors="replace")
            assert "[error" not in text, (name, text[:2000])
