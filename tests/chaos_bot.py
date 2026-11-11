"""Test-only chaos bot (F01 plan 6A2): our real protocol loop and legality layer, but Brain.act and
Brain.discard return seeded random garbage (or raise). Any engine notice means the legality layer failed.
Seed from env CHAOS_SEED.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))

import bot  # noqa: E402
import brain  # noqa: E402

rng = random.Random(int(os.environ.get("CHAOS_SEED", "0")))
ACTIONS = ["fold", "check", "call", "raise", "raise", "raise", "bet", "allin", "", None, 7]
AMOUNTS = [None, -5, 0, 1, 3.7, 4, 25, 199, 200, 10 ** 9, float("nan"), float("inf"), "12", "abc", True,
           [], {}]


def chaos_act(self, req):
    r = rng.random()
    if r < 0.05:
        raise RuntimeError("chaos")
    if r < 0.10:
        return rng.choice([None, "raise", 42, [], {"amount": 5}])
    intent = {"action": rng.choice(ACTIONS)}
    if rng.random() < 0.8:
        a = rng.choice(AMOUNTS)
        if a == 25:  # sometimes a plausible in-range amount
            lo, hi = req.get("min_raise", 0), req.get("max_raise", 0)
            a = rng.randint(lo, hi) if isinstance(lo, int) and isinstance(hi, int) and lo <= hi else a
        intent["amount"] = a
    return intent


def chaos_discard(self, req):
    r = rng.random()
    if r < 0.05:
        raise RuntimeError("chaos")
    hole = req.get("hole_cards") or []
    pool = list(hole) + ["2x", "Zz", "As", "Kd", "", None, 5, "as"]
    card = rng.choice(pool)
    return {"type": "discard", "card": card} if rng.random() < 0.8 else card


brain.Brain.act = chaos_act
brain.Brain.discard = chaos_discard
bot.main()
