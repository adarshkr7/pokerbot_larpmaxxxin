"""Shared helpers for the style sparring bots in tests/ (stdlib only; test-only, never shipped).

Each style bot defines `act(req, hole, rng, memo)` and calls `run(act)`. `req` carries `my_discard` /
`opp_discard` once known, and `memo` is a per-hand dict (e.g. who raised preflop). Equity is the pot-odds bot's
small Monte Carlo against a random hand, taking the best keep while holding three cards."""
import json
import random
import sys
from itertools import combinations

import potodds_bot as po

preflop_score = po.preflop_score
discard = po.discard


def eq_now(req, hole, rng, n=80):
    board = req.get("board", [])
    dead = set(hole) | set(board)
    for k in ("my_discard", "opp_discard"):
        if req.get(k):
            dead.add(req[k])
    keeps = list(combinations(hole, 2)) if len(hole) == 3 else [tuple(hole)]
    return max(po.equity(k, board, dead, rng, n) for k in keeps)


def price(req):
    tc = req.get("to_call", 0)
    return tc / (req.get("pot", 0) + tc) if tc > 0 else 0.0


def reply(req, a, amt=None):
    legal = req["legal_actions"]
    if a == "raise" and "raise" not in legal:
        a = "call" if "call" in legal else "check"
    if a == "check" and "check" not in legal:
        a = "fold"
    if a == "call" and "call" not in legal:
        a = "check" if "check" in legal else "fold"
    if a == "fold" and "check" in legal:
        a = "check"
    m = {"type": "action", "action": a}
    if a == "raise":
        m["amount"] = int(max(req["min_raise"], min(req["max_raise"], amt if amt is not None else req["min_raise"])))
    return m


def pot_raise(req, f):
    """Raise-to that adds f x (pot after calling) on top of the call."""
    return req["opp_bet"] + int(round(f * (req["pot"] + req.get("to_call", 0))))


def run(act):
    hole, extra, memo = [], {}, {}
    rng = random.Random(0)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        t = msg.get("type")
        if t == "new_hand":
            hole = list(msg.get("hole_cards", []))
            extra, memo = {}, {}
            rng = random.Random(msg.get("hand_id", 0) * 7919 + 17)
            continue
        if t == "discard_result":
            hole = list(msg.get("hole_cards", hole))
            extra = {"my_discard": msg.get("my_discard"), "opp_discard": msg.get("opp_discard")}
            continue
        if t == "action_request":
            out = act(dict(msg, **extra), hole, rng, memo)
        elif t == "discard_request":
            hole = list(msg["hole_cards"])
            out = {"type": "discard", "card": discard(hole, msg.get("board", []))}
        elif t == "match_end":
            break
        else:
            continue
        print(json.dumps(out), flush=True)
