"""Test-only bot: the real bot, plus state invariants checked after every engine message.

Writes "STATE_FAIL ..." to stderr on any violation and "STATE_CHECKS <n>" at match_end, so a test can
read the engine's stderr logs (F01 plan 3.5: dead never loses a card during a hand on real sequences).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))

import bot  # noqa: E402
import brain  # noqa: E402
from cards import fmt, is_valid, parse  # noqa: E402

BOARD_LEN = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
checks = [0]
prev = {}  # hand_id -> dead set


def fail(*parts):
    sys.stderr.write("STATE_FAIL " + " ".join(str(p) for p in parts) + "\n")
    sys.stderr.flush()


def check(b, where, msg):
    h = b.hand
    if h is None:
        return
    checks[0] += 1
    dead = {c for c in range(52) if h.dead[c]}
    expect = set(h.hole3) | set(h.board) | ({parse(h.opp_discard)} if is_valid(h.opp_discard) else set())
    if dead != expect:
        fail(where, h.hand_id, "dead mismatch", sorted(map(fmt, dead)), sorted(map(fmt, expect)))
    before = prev.get(h.hand_id, set())
    if not before <= dead:
        fail(where, h.hand_id, "dead lost cards", sorted(map(fmt, before - dead)))
    prev[h.hand_id] = dead
    if len(h.hole3) != 3:
        fail(where, h.hand_id, "hole3 size", h.hole3)
    if where == "act" and len(h.board) != BOARD_LEN.get(msg.get("street"), -1):
        fail(where, h.hand_id, "board size", msg.get("street"), h.board)
    if where == "discard" and (h.hole != h.hole3 or len(h.board) != 3):
        fail(where, h.hand_id, "discard sync", h.hole, h.hole3, h.board)
    if where == "on_discard_result" and (len(h.hole) != 2 or not set(h.hole) <= set(h.hole3)):
        fail(where, h.hand_id, "kept cards", h.hole, h.hole3)


def wrap(name):
    orig = getattr(brain.Brain, name)

    def wrapped(self, msg):
        out = orig(self, msg)
        check(self, name, msg)
        return out
    setattr(brain.Brain, name, wrapped)


for _name in ("on_new_hand", "act", "discard", "on_discard_result"):
    wrap(_name)

_orig_end = brain.Brain.on_match_end


def _end(self, msg):
    sys.stderr.write(f"STATE_CHECKS {checks[0]}\n")
    sys.stderr.flush()
    return _orig_end(self, msg)


brain.Brain.on_match_end = _end
bot.main()
