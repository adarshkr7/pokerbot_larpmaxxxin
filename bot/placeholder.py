"""Champion v0 behaviour (the organisers' starter strategy). Deleted once F04-F06 replace it."""

RANKS = "23456789TJQKA"


def v0_action(req):
    """Check if free, else call, else fold (starter_kit/bot.py::choose_action)."""
    legal = req["legal_actions"]
    if "check" in legal:
        return {"action": "check"}
    if "call" in legal:
        return {"action": "call"}
    return {"action": "fold"}


def v0_discard(hole_cards):
    """The first lowest-rank card in list order (starter_kit/bot.py::choose_discard).

    Raises on malformed cards; the caller's firewall then falls back to legal.fallback_discard.
    """
    return min(hole_cards, key=lambda c: RANKS.index(c[0]))
