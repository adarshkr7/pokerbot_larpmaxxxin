"""Test-only opponent: a min-raise pest. Min-raises (or min-bets) whenever a raise is legal and its hand is not
weak, so it raises small and often; calls cheap prices and folds big bets without a strong hand."""
from _sparring import eq_now, preflop_score, price, reply, run


def act(req, hole, rng, memo):
    legal = req["legal_actions"]
    if req["street"] == "preflop":
        s = preflop_score(hole)
        if s >= 0.30 and req.get("raises_left", 0) >= 1:
            return reply(req, "raise", req.get("min_raise"))
        if "check" in legal:
            return reply(req, "check")
        return reply(req, "call" if s >= 0.15 + 0.8 * price(req) else "fold")
    eq = eq_now(req, hole, rng)
    if eq >= 0.45 and "raise" in legal:
        return reply(req, "raise", req.get("min_raise"))
    if "check" in legal:
        return reply(req, "check")
    p = price(req)
    if p <= 0.25 or eq >= p + 0.05:
        return reply(req, "call")
    return reply(req, "fold")


if __name__ == "__main__":
    run(act)
