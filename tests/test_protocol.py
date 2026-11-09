"""Protocol-level tests: drive bot/bot.py as a subprocess, like the engine does."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT = ROOT / "bot" / "bot.py"

INIT = {"type": "init", "protocol_version": "1.0", "total_hands": 200, "starting_stack": 200,
        "small_blind": 1, "big_blind": 2, "time_bank_ms": 30000, "per_response_ms": 5000}
NEW_HAND = {"type": "new_hand", "hand_id": 1, "seat": "button",
            "hole_cards": ["As", "Kd", "7c"], "stack": 200, "opp_stack": 200}
PREFLOP = {"type": "action_request", "hand_id": 1, "street": "preflop", "board": [], "pot": 3,
           "my_bet": 1, "opp_bet": 2, "to_call": 1, "my_stack": 199, "opp_stack": 198,
           "legal_actions": ["fold", "call", "raise"], "min_raise": 4, "max_raise": 200,
           "raises_left": 3, "history": [], "time_left_ms": 30000}
FACING_ALLIN = {"type": "action_request", "hand_id": 1, "street": "preflop", "board": [],
                "pot": 201, "my_bet": 1, "opp_bet": 200, "to_call": 199, "my_stack": 199,
                "opp_stack": 0, "legal_actions": ["fold", "call"], "raises_left": 2,
                "history": [], "time_left_ms": 29000}
DISCARD = {"type": "discard_request", "hand_id": 1, "hole_cards": ["As", "Kd", "7c"],
           "board": ["Ah", "7d", "2s"], "pot": 24, "my_stack": 188, "opp_stack": 188,
           "time_left_ms": 29900}
UNKNOWN = {"type": "some_future_message", "foo": [1, 2, 3]}
MATCH_END = {"type": "match_end", "reason": "complete"}


def run_bot(messages, timeout=10):
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    proc = subprocess.run([sys.executable, str(BOT)], input=stdin, capture_output=True,
                          text=True, timeout=timeout, cwd=ROOT)
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc, replies


def assert_legal_action(reply, req):
    assert reply["type"] == "action"
    assert reply["action"] in req["legal_actions"]
    if reply["action"] == "raise":
        assert isinstance(reply["amount"], int)
        assert req["min_raise"] <= reply["amount"] <= req["max_raise"]


def test_replies_only_to_requests_and_exits():
    msgs = [INIT, UNKNOWN, NEW_HAND, PREFLOP, DISCARD, FACING_ALLIN, UNKNOWN, MATCH_END]
    proc, replies = run_bot(msgs)
    assert proc.returncode == 0, proc.stderr
    assert len(replies) == 3, f"expected 3 replies, got {replies}"
    assert_legal_action(replies[0], PREFLOP)
    assert replies[1]["type"] == "discard"
    assert replies[1]["card"] in DISCARD["hole_cards"]
    assert_legal_action(replies[2], FACING_ALLIN)


def test_exits_on_eof_without_match_end():
    proc, _ = run_bot([INIT, NEW_HAND])
    assert proc.returncode == 0, proc.stderr
