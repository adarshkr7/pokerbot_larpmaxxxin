"""Test-only opponent: polarised over-bettor. Postflop it either checks (medium hands) or bets 1.5x pot / all-in,
with its strong hands and with a share of its air (bluffs ~35% of its weakest hands), so its big bets are a mix
of nuts and nothing. Calls a bet only with a strong hand. Preflop: raises the top ~40% to 4x, calls cheap prices."""
from _sparring import eq_now, pot_raise, preflop_score, price, reply, run


def act(req, hole, rng, memo):
    legal = req["legal_actions"]
    if req["street"] == "preflop":
        s = preflop_score(hole)
        if s >= 0.42 and req.get("raises_left", 0) >= 2:
            return reply(req, "raise", 4 * max(req["opp_bet"], 2))
        if "check" in legal:
            return reply(req, "check")
        return reply(req, "call" if s >= 0.20 + 0.6 * price(req) else "fold")
    eq = eq_now(req, hole, rng)
    big = eq >= 0.75 or (eq < 0.30 and rng.random() < 0.35)
    if big and "raise" in legal and (req.get("to_call", 0) == 0 or eq >= 0.75):
        amt = req["max_raise"] if req["street"] == "river" and eq >= 0.85 else pot_raise(req, 1.5)
        return reply(req, "raise", amt)
    if "check" in legal:
        return reply(req, "check")
    if eq >= max(0.55, price(req) + 0.05):
        return reply(req, "call")
    return reply(req, "fold")


if __name__ == "__main__":
    run(act)
