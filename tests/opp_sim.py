"""Test helper: play hands in-process through the organisers' engine (starter_kit/engine.py Hand, imported by file
path, never modified) between two Python policies, and collect the hand_result messages seen by side A.

A policy is an object with act(req) -> reply dict, discard(req) -> reply dict, and optional on_message(msg).
"""
import json
import random

from engine_util import engine

RANKS = "23456789TJQKA"
DECK = [r + s for r in RANKS for s in "shdc"]


class _Fake:
    """The engine's Bot interface (send / begin / wait_reply / notices), answered by a policy in-process."""

    def __init__(self, policy):
        self.policy = policy
        self.notices = 0
        self.reply = None
        self.results = []
        self.seat = None

    def send(self, msg):
        t = msg.get("type")
        if t == "new_hand":
            self.seat = msg.get("seat")
        if t == "hand_result":
            self.results.append((dict(msg), self.seat))
        if t == "notice":
            self.notices += 1
        f = getattr(self.policy, "on_message", None)
        if f is not None:
            f(msg)
        return True

    def begin(self, msg):
        msg["time_left_ms"] = 10 ** 6
        if msg["type"] == "action_request":
            self.reply = self.policy.act(msg)
        else:
            self.reply = self.policy.discard(msg)

    def wait_reply(self, wall_deadline):
        return json.dumps(self.reply), None


class _Match:
    def __init__(self, a, b):
        self.bots = [a, b]
        self.wall_deadline = float("inf")


def play(policy_a, policy_b, hands, seed):
    """Play `hands` hands (button alternating, random deals from `seed`); return A's [(hand_result, seat)]."""
    rng = random.Random(seed)
    a, b = _Fake(policy_a), _Fake(policy_b)
    m = _Match(a, b)
    for i in range(hands):
        cards = rng.sample(DECK, 11)
        h = engine.Hand(m, i + 1, i % 2, (cards[0:3], cards[3:6]), cards[6:11])
        h.play()
    assert a.notices == 0 and b.notices == 0
    return a.results


# ----------------------------------------------------------------------------------------------- simple policies
def _r(c):
    return RANKS.index(c[0])


def _low(hole):
    return min(hole, key=lambda c: (_r(c), "shdc".index(c[1])))


class Policy:
    discard_rule = "lowest"

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def discard(self, req):
        hole = req["hole_cards"]
        if self.discard_rule == "random":
            card = self.rng.choice(hole)
        else:
            card = _low(hole)
        return {"type": "discard", "card": card}

    @staticmethod
    def act_(a, req=None, amount=None):
        m = {"type": "action", "action": a}
        if amount is not None:
            m["amount"] = int(max(req["min_raise"], min(req["max_raise"], amount)))
        return m


class Station(Policy):
    def act(self, req):
        return self.act_("check" if "check" in req["legal_actions"] else "call")


class Shover(Policy):
    def act(self, req):
        legal = req["legal_actions"]
        if "raise" in legal:
            return self.act_("raise", req, req["max_raise"])
        return self.act_("call" if "call" in legal else "check")


class Maniac(Policy):
    """Raises (often all-in) most of the time when it can, rarely folds."""

    def act(self, req):
        legal = req["legal_actions"]
        u = self.rng.random()
        if "raise" in legal and u < 0.80:
            if u < 0.30:
                return self.act_("raise", req, req["max_raise"])
            return self.act_("raise", req, req["opp_bet"] + req["pot"] + req["to_call"])
        if "check" in legal:
            return self.act_("check")
        return self.act_("fold" if u > 0.92 else "call")


class RandomBot(Policy):
    """The behaviour of starter_kit/example_bots/random_bot.py: raise 20% (pot-relative sizes), else check, else call
    60% / fold 20%; random discards."""
    discard_rule = "random"

    def act(self, req):
        legal = req["legal_actions"]
        roll = self.rng.random()
        if "raise" in legal and roll < 0.2:
            size = self.rng.choice((0.5, 0.75, 1.0, 2.0))
            return self.act_("raise", req, req["opp_bet"] + int(size * (req["pot"] + req["to_call"])))
        if "check" in legal:
            return self.act_("check")
        return self.act_("call" if roll < 0.8 else "fold")


class RandomActs(Policy):
    """Uniformly random legal actions, raise sizes uniform over the legal range, random discards."""
    discard_rule = "random"

    def act(self, req):
        a = self.rng.choice(req["legal_actions"])
        if a == "raise":
            return self.act_("raise", req, self.rng.randint(req["min_raise"], req["max_raise"]))
        return self.act_(a)


class Nit(Policy):
    """Plays a pair of 8s+ or two cards Q+; postflop continues only with a pair of the top board rank or better."""

    def __init__(self, seed=0):
        super().__init__(seed)
        self.hole = []

    def on_message(self, msg):
        if msg.get("type") == "new_hand":
            self.hole = list(msg["hole_cards"])
        elif msg.get("type") == "discard_result":
            self.hole = list(msg["hole_cards"])

    def strong(self, req):
        rs = sorted((_r(c) for c in self.hole), reverse=True)
        if req["street"] == "preflop":
            pair = [x for x in rs if rs.count(x) >= 2]
            return bool(pair and max(pair) >= 6) or rs[1] >= 10
        board = [_r(c) for c in req["board"]]
        return any(x in board and x >= max(board) for x in rs) or any(rs.count(x) >= 2 and x > max(board) for x in rs)

    def act(self, req):
        legal = req["legal_actions"]
        s = self.strong(req)
        if s and req["street"] == "preflop" and "raise" in legal and req.get("raises_left", 0) >= 2:
            return self.act_("raise", req, 3 * max(req["opp_bet"], 2))
        if "check" in legal:
            return self.act_("check")
        return self.act_("call" if s else "fold")


class Sensible(Policy):
    """A simple strength-based player: preflop by our own percentile table, postflop by made-hand category and
    pot odds; bets and raises in proportion to its strength. Discards by the max-S rule."""

    def __init__(self, seed=0):
        super().__init__(seed)
        self.hole = []

    def on_message(self, msg):
        if msg.get("type") in ("new_hand", "discard_result"):
            self.hole = list(msg["hole_cards"])

    def strength(self, req):
        import preflop
        from cards import parse
        from evaluator import eval7
        if req["street"] == "preflop":
            return preflop.percentile(self.hole)
        hole = [parse(c) for c in self.hole]
        board = [parse(c) for c in req["board"]]
        if len(hole) == 3:
            import discard
            return min(1.0, max(discard.flop_score(p, board) for p in ((hole[0], hole[1]), (hole[0], hole[2]),
                                                                          (hole[1], hole[2]))) / 3.0)
        v = eval7(tuple(hole + board))
        bv = eval7(tuple(board)) if len(board) >= 5 else 0
        cat = (v >> 20) - (0.7 if len(board) >= 5 and (bv >> 20) >= (v >> 20) else 0.0)
        return min(1.0, max(0.0, (cat + (v & 0xFFFFF) / float(1 << 20)) / 3.0))

    def act(self, req):
        legal = req["legal_actions"]
        s = self.strength(req) + self.rng.uniform(-0.05, 0.05)
        price = req["to_call"] / (req["pot"] + req["to_call"]) if req["to_call"] > 0 else 0.0
        if "raise" in legal and s > 0.72:
            return self.act_("raise", req, req["opp_bet"] + int((0.4 + s) * (req["pot"] + req["to_call"])))
        if "check" in legal:
            return self.act_("check")
        return self.act_("call" if s > 0.25 + price else "fold")

    def discard(self, req):
        import discard
        from cards import fmt, parse
        hole = [parse(c) for c in req["hole_cards"]]
        board = [parse(c) for c in req["board"]]
        return {"type": "discard", "card": fmt(discard.opp_discard_policy(hole, board))}


class Hero(Policy):
    """Side A: a plain mixed policy that opens, bets and folds sometimes (so every statistic gets opportunities)."""

    def act(self, req):
        legal = req["legal_actions"]
        u = self.rng.random()
        if "raise" in legal and u < 0.45:
            if req["street"] == "preflop":
                return self.act_("raise", req, 3 * max(req["opp_bet"], 2))
            return self.act_("raise", req, req["opp_bet"] + int(0.66 * (req["pot"] + req["to_call"])))
        if "check" in legal:
            return self.act_("check")
        return self.act_("call" if u < 0.8 else "fold")
