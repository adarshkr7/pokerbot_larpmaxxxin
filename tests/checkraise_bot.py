"""Test-only opponent: a trapper. Passive preflop (calls wide, raises only the top ~10%); postflop it never bets
first: it checks, then check-raises pot with strong hands and some draws, calls with a small margin, folds the
rest. Probes whether we bet into it too thinly and how we handle raises after betting."""
from _sparring import eq_now, pot_raise, preflop_score, price, reply, run


def act(req, hole, rng, memo):
    legal = req["legal_actions"]
    if req["street"] == "preflop":
        s = preflop_score(hole)
        if s >= 0.70 and req.get("raises_left", 0) >= 1:
            return reply(req, "raise", 3 * max(req["opp_bet"], 2))
        if "check" in legal:
            return reply(req, "check")
        return reply(req, "call" if s >= 0.15 + 0.6 * price(req) else "fold")
    if req.get("to_call", 0) == 0:
        return reply(req, "check")
    eq = eq_now(req, hole, rng)
    draw_raise = req["street"] == "flop" and 0.38 <= eq < 0.55 and rng.random() < 0.25
    if (eq >= 0.72 or draw_raise) and "raise" in legal:
        return reply(req, "raise", pot_raise(req, 1.0))
    if eq >= price(req) + 0.05:
        return reply(req, "call")
    return reply(req, "fold")


if __name__ == "__main__":
    run(act)
