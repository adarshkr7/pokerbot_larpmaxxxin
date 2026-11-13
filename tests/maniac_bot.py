"""Test-only opponent: a maniac. Raises or shoves often but not always, rarely folds; discards its lowest card.
Deterministic given MANIAC_SEED (default 7): its random stream depends only on the sequence of requests."""
import json
import os
import random
import sys

RANKS = "23456789TJQKA"


def act(req, rng):
    legal = req["legal_actions"]
    roll = rng.random()
    if "raise" in legal:
        lo, hi = req["min_raise"], req["max_raise"]
        if roll < 0.30:
            return {"type": "action", "action": "raise", "amount": hi}
        if roll < 0.65:
            target = req["opp_bet"] + int(1.0 * (req["pot"] + req["to_call"]))
            return {"type": "action", "action": "raise", "amount": max(lo, min(hi, target))}
    if "check" in legal:
        return {"type": "action", "action": "check"}
    if roll > 0.90:
        return {"type": "action", "action": "fold"}
    return {"type": "action", "action": "call"}


def main():
    rng = random.Random(int(os.environ.get("MANIAC_SEED", "7")))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        t = msg.get("type")
        if t == "action_request":
            reply = act(msg, rng)
        elif t == "discard_request":
            reply = {"type": "discard", "card": min(msg["hole_cards"], key=lambda c: RANKS.index(c[0]))}
        elif t == "match_end":
            break
        else:
            continue
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
