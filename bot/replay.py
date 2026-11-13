"""Rebuild bets, stacks and the pot along an engine history (the rules of starter_kit/engine.py Hand.betting_round).

walk(history, stack=200, sb=1, bb=2) -> (events, me_button) or None when the history is malformed.

One event per history entry, describing the spot the actor faced *before* acting:
  street, actor ("me"/"opp"), action, amount (raise-to / call total or None),
  pot        chips committed by both players before the action,
  bet_a      the actor's bet on this street before acting, bet_o the other player's,
  to_call    bet_o - bet_a,
  max_raise  min(bet_a + stack_a, bet_o + stack_o) (the engine's max_raise),
  raise_legal  raises < 4 and max_raise > bet_o (the engine's rule; the big blind counts as a raise preflop),
  allin      a raise to max_raise (the actor or the other player is then all-in),
  aggr       who made the last voluntary raise on this street before the action ("me"/"opp"/None).
The button is the first preflop actor. Pure; never raises.
"""
STREETS = ("preflop", "flop", "turn", "river")
ACTIONS = ("fold", "check", "call", "raise")
MAX_RAISES = 4


def _int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def walk(history, stack=200, sb=1, bb=2):
    try:
        return _walk(history, stack, sb, bb)
    except Exception:
        return None


def _walk(history, stack, sb, bb):
    if not isinstance(history, list) or not history:
        return None
    for h in history:
        if (not isinstance(h, dict) or h.get("street") not in STREETS or h.get("actor") not in ("me", "opp")
                or h.get("action") not in ACTIONS):
            return None
    first = history[0]
    if first["street"] != "preflop":
        return None
    btn = first["actor"]
    other = "opp" if btn == "me" else "me"
    committed = {btn: sb, other: bb}
    bets = {btn: sb, other: bb}
    raises = 1
    aggr = None
    street_i = 0
    events = []
    for h in history:
        si = STREETS.index(h["street"])
        if si < street_i:
            return None
        if si > street_i:
            street_i = si
            bets = {btn: 0, other: 0}
            raises = 0
            aggr = None
        a = h["actor"]
        o = "opp" if a == "me" else "me"
        st_a = stack - committed[a]
        st_o = stack - committed[o]
        to_call = bets[o] - bets[a]
        max_raise = min(bets[a] + st_a, bets[o] + st_o)
        act = h["action"]
        ev = {"street": h["street"], "actor": a, "action": act, "amount": None, "pot": committed[a] + committed[o],
              "bet_a": bets[a], "bet_o": bets[o], "to_call": to_call, "max_raise": max_raise,
              "raise_legal": raises < MAX_RAISES and max_raise > bets[o], "allin": False, "aggr": aggr}
        if act == "raise":
            amt = _int(h.get("amount"))
            if amt is None or amt <= bets[o] or amt > max_raise:
                return None
            ev["amount"] = amt
            ev["allin"] = amt >= max_raise
            committed[a] += amt - bets[a]
            bets[a] = amt
            raises += 1
            aggr = a
        elif act == "call":
            if to_call <= 0:
                return None
            pay = min(to_call, st_a)
            committed[a] += pay
            bets[a] += pay
            ev["amount"] = bets[a]
        elif act == "check":
            if to_call > 0:
                return None
        events.append(ev)
    return events, btn == "me"
