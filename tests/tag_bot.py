"""Test-only opponent: tight-aggressive (a competent-looking student bot). Raises the top ~35% preflop to 3x,
3-bets strong hands, defends reasonable prices; c-bets 2/3 pot most of the time as the preflop raiser, value-bets
and raises by equity, calls only with a margin over the price, and bluffs some rivers when checked to."""
from _sparring import eq_now, pot_raise, preflop_score, price, reply, run


def act(req, hole, rng, memo):
    street = req["street"]
    legal = req["legal_actions"]
    if street == "preflop":
        s = preflop_score(hole)
        facing = req.get("to_call", 0) > 0 and req.get("opp_bet", 0) > 2
        if s >= (0.62 if facing else 0.45) and req.get("raises_left", 0) >= 2:
            memo["pfr"] = True
            return reply(req, "raise", 3 * max(req["opp_bet"], 2))
        if "check" in legal:
            return reply(req, "check")
        if s >= 0.30 + 0.6 * price(req):
            return reply(req, "call")
        return reply(req, "fold")
    eq = eq_now(req, hole, rng)
    tc = req.get("to_call", 0)
    if tc == 0:
        if eq >= 0.62 or (memo.get("pfr") and street == "flop" and rng.random() < 0.65):
            return reply(req, "raise", pot_raise(req, 2 / 3))
        if street == "river" and eq < 0.30 and rng.random() < 0.18:
            return reply(req, "raise", pot_raise(req, 2 / 3))
        return reply(req, "check")
    if eq >= 0.80:
        return reply(req, "raise", pot_raise(req, 0.8))
    if eq >= price(req) + 0.10:
        return reply(req, "call")
    return reply(req, "fold")


if __name__ == "__main__":
    run(act)
