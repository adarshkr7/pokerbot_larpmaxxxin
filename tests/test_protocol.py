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


# --------------------------------------------------------------- F01 plan 6B: robustness
import os  # noqa: E402

from engine_util import engine  # noqa: E402

PATCHED = ROOT / "tests" / "patched_bot.py"


def run_script(lines, script=BOT, mode=None, timeout=5):
    """Feed raw stdin lines (dicts are JSON-encoded, strings sent verbatim); return (proc, stdout lines)."""
    stdin = "".join((json.dumps(x) if not isinstance(x, str) else x) + "\n" for x in lines)
    env = dict(os.environ, PATCH_MODE=mode or "")
    proc = subprocess.run([sys.executable, str(script)], input=stdin, capture_output=True, text=True,
                          timeout=timeout, cwd=ROOT, env=env)
    out = [line for line in proc.stdout.splitlines() if line.strip()]
    return proc, out


def requests_in(lines):
    return [x for x in lines if isinstance(x, dict) and x.get("type") in ("action_request", "discard_request")]


def assert_liveness(lines, proc, out):
    """Exactly one well-formed reply per request, in order, nothing else on stdout, exit 0."""
    assert proc.returncode == 0, proc.stderr
    reqs = requests_in(lines)
    assert len(out) == len(reqs), (out, proc.stderr)
    for req, line in zip(reqs, out):
        reply = json.loads(line)
        assert isinstance(reply, dict)
        want = "action" if req["type"] == "action_request" else "discard"
        assert reply["type"] == want, (req, reply)
        if want == "discard":
            assert isinstance(reply.get("card"), str)
        else:
            assert isinstance(reply.get("action"), str)
    return [json.loads(line) for line in out]


def assert_engine_legal(req, line):
    if req["type"] == "action_request":
        _, _, err = engine.parse_action(line, req)
    else:
        _, err = engine.parse_discard(line, req["hole_cards"])
    assert err is None, (req, line, err)


def discard_req(hole, hand_id=1):
    return {**DISCARD, "hand_id": hand_id, "hole_cards": hole}


def test_well_formed_edge_requests_are_engine_legal():
    other_hand = {**PREFLOP, "hand_id": 5}
    two_cards = discard_req(["Qs", "Jh"])
    bad_card = discard_req(["2x", "As", "Kd"])
    lines = [PREFLOP, INIT, other_hand, NEW_HAND, PREFLOP, two_cards, bad_card, FACING_ALLIN, MATCH_END]
    proc, out = run_script(lines)
    assert_liveness(lines, proc, out)
    for req, line in zip(requests_in(lines), out):
        assert_engine_legal(req, line)
    assert json.loads(out[4])["card"] == "Kd"


MALFORMED_LEGAL = ["missing", None, 7, "check fold", []]


def malformed_legal_requests():
    out = []
    for value in MALFORMED_LEGAL:
        req = {k: v for k, v in PREFLOP.items() if k != "legal_actions"}
        if value != "missing":
            req["legal_actions"] = value
        out.append(req)
    return out


def test_malformed_legal_actions_get_check_through_the_loop():
    reqs = malformed_legal_requests()
    for mode in (None, "act_raises"):
        lines = [INIT, NEW_HAND, *reqs, MATCH_END]
        proc, out = run_script(lines, script=PATCHED, mode=mode)
        replies = assert_liveness(lines, proc, out)
        assert replies == [{"type": "action", "action": "check"}] * len(reqs), (mode, replies)


def test_raise_legal_but_bounds_missing_or_bad():
    variants = []
    for drop, extra in (("min_raise", {}), ("max_raise", {}), (None, {"min_raise": "4"}),
                        (None, {"min_raise": True})):
        req = {k: v for k, v in PREFLOP.items() if k != drop}
        req.update(extra)
        variants.append(req)
    lines = [INIT, NEW_HAND, *variants, MATCH_END]
    for mode in (None, "always_raise"):   # v0 intends call; always_raise intends an (unusable) raise
        proc, out = run_script(lines, script=PATCHED, mode=mode)
        assert_liveness(lines, proc, out)
        for req, line in zip(variants, out):
            assert json.loads(line)["action"] == "call"
            no_raise = {**req, "legal_actions": [a for a in req["legal_actions"] if a != "raise"]}
            assert_engine_legal(no_raise, line)


def test_discard_with_no_valid_card_or_missing_hole():
    no_valid = discard_req(["zz", "1x"])
    missing = {k: v for k, v in DISCARD.items() if k != "hole_cards"}
    lines = [INIT, NEW_HAND, no_valid, missing, MATCH_END]
    proc, out = run_script(lines)
    replies = assert_liveness(lines, proc, out)
    assert replies == [{"type": "discard", "card": "zz"}, {"type": "discard", "card": "2s"}]


def test_garbage_lines_get_no_reply_and_do_not_stop_the_loop():
    lines = [INIT, "{not json", "[1, 2, 3]", '"just a string"', "42", "null", {"type": []}, PREFLOP,
             {"type": {}}, {"no_type": 1}, {"type": None}, UNKNOWN, {**NEW_HAND, "extra_field": [1]},
             {**PREFLOP, "extra": {"x": 1}}, DISCARD, MATCH_END]
    proc, out = run_script(lines)
    assert_liveness(lines, proc, out)
    for req, line in zip(requests_in(lines), out):
        assert_engine_legal(req, line)


def test_eof_without_match_end_mid_hand():
    lines = [INIT, NEW_HAND, PREFLOP]
    proc, out = run_script(lines)
    assert_liveness(lines, proc, out)


def test_constructor_failure_still_answers_and_exits_cleanly():
    hand_result = {"type": "hand_result", "hand_id": 1, "result": "fold", "net": -2}
    lines = [INIT, NEW_HAND, PREFLOP, DISCARD, FACING_ALLIN, hand_result, MATCH_END]
    proc, out = run_script(lines, script=PATCHED, mode="init_raises")
    assert_liveness(lines, proc, out)
    for req, line in zip(requests_in(lines), out):
        assert_engine_legal(req, line)
    assert "Traceback" in proc.stderr and "sabotaged" in proc.stderr


def test_lines_after_match_end_are_not_answered():
    lines = [INIT, NEW_HAND, MATCH_END, PREFLOP]
    proc, out = run_script(lines)
    assert proc.returncode == 0 and out == []


def test_invalid_utf8_on_stdin_does_not_crash():
    stdin = (json.dumps(INIT) + "\n").encode() + b"\xff\xfe{bad\n" + (json.dumps(PREFLOP) + "\n").encode() \
        + (json.dumps(MATCH_END) + "\n").encode()
    env = dict(os.environ, PYTHONIOENCODING="utf-8:strict")   # as on a UTF-8 Linux judge
    proc = subprocess.run([sys.executable, str(BOT)], input=stdin, capture_output=True, timeout=5,
                          cwd=ROOT, env=env)
    assert proc.returncode == 0, proc.stderr
    out = [line for line in proc.stdout.decode().splitlines() if line.strip()]
    assert len(out) == 1
    assert_engine_legal(PREFLOP, out[0])
