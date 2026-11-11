"""The single legality boundary: every outgoing action and discard passes through here (01/R2).

Mirrors starter_kit/engine.py (betting_round, parse_action, parse_discard, default_discard).
Every function in this module is total: it never raises and always returns a complete reply.
"""
import math
import numbers

from cards import RANK, SUIT, is_valid


def _act(action):
    return {"type": "action", "action": action}


def legal_list(req):
    """The str entries of req["legal_actions"] if it is a list, else None. Never raises."""
    try:
        legal = req.get("legal_actions") if isinstance(req, dict) else None
        if not isinstance(legal, list):
            return None
        return [a for a in legal if isinstance(a, str)]
    except Exception:
        return None


def fallback_action(req):
    """check if legal (or legality unknown), else fold."""
    legal = legal_list(req)
    if not legal or "check" in legal:
        return _act("check")
    return _act("fold")


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def to_int(x, default):
    """int (not bool), finite real (rounded half-up) or numeric string -> int; anything else -> default."""
    try:
        if isinstance(x, bool):
            return default
        if isinstance(x, numbers.Integral):
            return int(x)
        if isinstance(x, str):
            x = float(x.strip())
        if isinstance(x, numbers.Real):
            x = float(x)
            if not math.isfinite(x):
                return default
            return int(math.floor(x + 0.5))
    except Exception:
        pass
    return default


def make_legal(intent, req):
    """Map any intent ({"action": ..., "amount": ...}, or garbage) to a legal action reply."""
    legal = legal_list(req)
    if not legal:
        return _act("check")
    action = intent.get("action") if isinstance(intent, dict) else None
    if action == "raise":
        lo, hi = req.get("min_raise"), req.get("max_raise")
        if "raise" in legal and _is_int(lo) and _is_int(hi) and lo <= hi:
            amount = min(max(to_int(intent.get("amount"), lo), lo), hi)
            return {"type": "action", "action": "raise", "amount": int(amount)}
        action = "call"
    if action == "call":
        return _act("call" if "call" in legal else "check")
    if action == "check":
        return _act("check" if "check" in legal else "fold")
    if action == "fold":
        return _act("fold" if "fold" in legal else "check")
    return fallback_action(req)


def fallback_discard(hole):
    """engine.default_discard over the valid cards: lowest rank, ties s < h < d < c.

    If no card is valid there is no legal discard: hole[0] if it is a string, else "2s".
    """
    hole = hole if isinstance(hole, list) else []
    valid = [c for c in hole if is_valid(c)]
    if valid:
        return min(valid, key=lambda c: (RANK[c[0]], SUIT[c[1]]))
    if hole and isinstance(hole[0], str):
        return hole[0]
    return "2s"


def make_legal_discard(card, req):
    """Keep `card` only if it is a valid card string in our hole cards; else the engine's default."""
    hole = req.get("hole_cards") if isinstance(req, dict) else None
    hole = hole if isinstance(hole, list) else []
    if is_valid(card) and card in hole:
        return {"type": "discard", "card": card}
    return {"type": "discard", "card": fallback_discard(hole)}
