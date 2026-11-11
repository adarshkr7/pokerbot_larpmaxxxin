"""Legality layer (F01 plan 6A1): every reply must pass the engine's own parse_action / parse_discard."""
import json
import math
import random

import pytest

from engine_util import engine
from legal import (fallback_action, fallback_discard, legal_list, make_legal, make_legal_discard,
                   to_int)

MAX_RAISES = engine.MAX_RAISES


def gen_request(rng):
    """A request built with the formulas of engine.Hand.betting_round (starter_kit/engine.py)."""
    street = rng.choice(engine.STREETS)
    raises = rng.randint(1, MAX_RAISES) if street == "preflop" else rng.randint(0, MAX_RAISES)
    opp_bet = rng.randint(0, 200)
    my_bet = rng.randint(0, opp_bet)
    my_stack = rng.randint(1, 200 - my_bet) if my_bet < 200 else 0
    opp_stack = rng.randint(0, 200 - opp_bet)
    last_raise = rng.choice([0, 2, rng.randint(0, max(opp_bet - my_bet, 0) + 2)])
    to_call = opp_bet - my_bet
    max_raise = min(my_bet + my_stack, opp_bet + opp_stack)
    legal = ["fold", "call"] if to_call > 0 else ["check"]
    can_raise = raises < MAX_RAISES and max_raise > opp_bet
    if can_raise:
        legal.append("raise")
    req = {"type": "action_request", "hand_id": 1, "street": street, "board": [],
           "pot": my_bet + opp_bet, "my_bet": my_bet, "opp_bet": opp_bet, "to_call": to_call,
           "my_stack": my_stack, "opp_stack": opp_stack, "legal_actions": legal}
    if can_raise:
        req["min_raise"] = min(opp_bet + max(last_raise, 2), max_raise)
        req["max_raise"] = max_raise
    req["raises_left"] = MAX_RAISES - raises
    return req


def intents(req, rng):
    lo = req.get("min_raise", 10)
    hi = req.get("max_raise", 50)
    amounts = [lo, hi, rng.randint(lo, hi) if lo <= hi else lo, lo - 1, hi + 1, -5, 0, 10 ** 9,
               lo + 0.5, 12.7, "12", " 30 ", "abc", "", None, float("nan"), float("inf"),
               -float("inf"), True, False, [], {}]
    out = [{"action": a} for a in ("fold", "check", "call", "raise", "bet", "allin", "", None, 7)]
    out += [{"action": "raise", "amount": a} for a in amounts]
    out += [None, "raise", 42, [], {"amount": 5}]
    return out


def test_make_legal_always_passes_engine_parse_action():
    rng = random.Random(12345)
    checked = 0
    for _ in range(20000):
        req = gen_request(rng)
        for intent in intents(req, rng):
            reply = make_legal(intent, req)
            action, amount, err = engine.parse_action(json.dumps(reply), req)
            assert err is None, (intent, req, reply, err)
            checked += 1
    assert checked > 500_000


def test_raise_clamping_and_rounding():
    req = {"legal_actions": ["fold", "call", "raise"], "min_raise": 10, "max_raise": 50}
    assert make_legal({"action": "raise", "amount": 5}, req)["amount"] == 10
    assert make_legal({"action": "raise", "amount": 500}, req)["amount"] == 50
    assert make_legal({"action": "raise", "amount": 20.5}, req)["amount"] == 21
    assert make_legal({"action": "raise", "amount": "33"}, req)["amount"] == 33
    assert make_legal({"action": "raise", "amount": None}, req)["amount"] == 10
    assert make_legal({"action": "raise", "amount": True}, req)["amount"] == 10
    short = {"legal_actions": ["fold", "call", "raise"], "min_raise": 37, "max_raise": 37}
    assert make_legal({"action": "raise", "amount": 100}, short)["amount"] == 37


def test_raise_without_valid_bounds_is_treated_as_illegal():
    for extra in ({}, {"min_raise": 4}, {"min_raise": "4", "max_raise": 9}, {"min_raise": True, "max_raise": 9},
                  {"min_raise": 9, "max_raise": 4}):
        req = {"legal_actions": ["fold", "call", "raise"], **extra}
        assert make_legal({"action": "raise", "amount": 6}, req) == {"type": "action", "action": "call"}
        req = {"legal_actions": ["check", "raise"], **extra}
        assert make_legal({"action": "raise", "amount": 6}, req) == {"type": "action", "action": "check"}


def test_action_mapping_table():
    facing = {"legal_actions": ["fold", "call"]}
    free = {"legal_actions": ["check"]}
    assert make_legal({"action": "check"}, facing)["action"] == "fold"
    assert make_legal({"action": "fold"}, free)["action"] == "check"
    assert make_legal({"action": "call"}, free)["action"] == "check"
    assert make_legal({"action": "raise", "amount": 9}, facing)["action"] == "call"
    assert make_legal({"action": "nonsense"}, facing)["action"] == "fold"
    assert make_legal(None, free)["action"] == "check"


@pytest.mark.parametrize("value", ["missing", None, 7, "check fold", [], {"a": 1}, [1, None]])
def test_malformed_legal_actions_never_raise(value):
    req = {"type": "action_request"} if value == "missing" else {"legal_actions": value}
    assert legal_list(req) in (None, [])
    for intent in (None, {"action": "raise", "amount": 5}, {"action": "fold"}, "x"):
        assert make_legal(intent, req) == {"type": "action", "action": "check"}
    assert fallback_action(req) == {"type": "action", "action": "check"}
    assert legal_list("not a dict") is None
    assert make_legal({"action": "call"}, 5) == {"type": "action", "action": "check"}


def test_to_int():
    assert to_int(7, 0) == 7 and to_int(2.5, 0) == 3 and to_int(-2.5, 0) == -2
    assert to_int(" 12 ", 0) == 12 and to_int("1e2", 0) == 100
    for bad in (None, True, False, float("nan"), float("inf"), "abc", "", [], {}):
        assert to_int(bad, -1) == -1


ALL_CARDS = [r + s for r in engine.RANKS for s in engine.SUITS]


def test_fallback_discard_matches_engine_default_discard():
    rng = random.Random(7)
    for _ in range(5000):
        hole = rng.sample(ALL_CARDS, rng.choice([2, 3]))
        assert fallback_discard(hole) == engine.default_discard(hole)


def test_make_legal_discard_passes_engine_parse_discard():
    rng = random.Random(8)
    junk = ["2x", "Zz", "", "AS", "as", "10h", None, 5, [], "Ah "]
    for _ in range(5000):
        hole = rng.sample(ALL_CARDS, 3)
        for card in hole + rng.sample(ALL_CARDS, 3) + junk:
            reply = make_legal_discard(card, {"hole_cards": hole})
            got, err = engine.parse_discard(json.dumps(reply), hole)
            assert err is None, (card, hole, reply)
            if card in hole:
                assert got == card


def test_discard_requires_validity_and_membership():
    req = {"hole_cards": ["2x", "As", "Kd"]}
    assert make_legal_discard("2x", req)["card"] == "Kd"
    assert make_legal_discard("As", req)["card"] == "As"
    assert make_legal_discard(None, {"hole_cards": ["zz", "1x"]})["card"] == "zz"
    assert make_legal_discard("As", {})["card"] == "2s"
    assert make_legal_discard("As", {"hole_cards": [3, None]})["card"] == "2s"
