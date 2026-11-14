"""Test-only opponent: its bet size tells its strength. Strong hands overbet 1.5x pot, good hands bet 2/3, weak
hands sometimes stab 1/4 pot; preflop the raise size also scales with strength. Calls by pot odds plus a margin.
A bot that reads bet sizes should beat it by much more than one that ignores them."""
from _sparring import eq_now, pot_raise, preflop_score, price, reply, run


def act(req, hole, rng, memo):
    legal = req["legal_actions"]
    if req["street"] == "preflop":
        s = preflop_score(hole)
        if s >= 0.45 and req.get("raises_left", 0) >= 2:
            mult = 5 if s >= 0.70 else 3
            return reply(req, "raise", mult * max(req["opp_bet"], 2))
        if "check" in legal:
            return reply(req, "check")
        return reply(req, "call" if s >= 0.20 + 0.6 * price(req) else "fold")
    eq = eq_now(req, hole, rng)
    if eq >= 0.78:
        return reply(req, "raise", pot_raise(req, 1.5))
    if eq >= 0.60 and req.get("to_call", 0) == 0:
        return reply(req, "raise", pot_raise(req, 2 / 3))
    if req.get("to_call", 0) == 0:
        if eq < 0.35 and rng.random() < 0.30:
            return reply(req, "raise", pot_raise(req, 0.25))
        return reply(req, "check")
    if eq >= price(req) + 0.05:
        return reply(req, "call")
    return reply(req, "fold")


if __name__ == "__main__":
    run(act)
