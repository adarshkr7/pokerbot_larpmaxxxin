"""Hand state and dead cards (F01 plan 3.2, 3.5 and the in-process rows of 6B)."""
from brain import Brain
from cards import fmt, is_valid, parse, parse_valid
from state import HandState


def dead_set(hand):
    return {fmt(c) for c in range(52) if hand.dead[c]}


def test_cards_roundtrip():
    assert parse("As") == 48 and fmt(48) == "As" and parse("2s") == 0 and fmt(51) == "Ac"
    for c in range(52):
        assert parse(fmt(c)) == c
    for bad in ("2x", "AS", "", "10h", None, 5, "Ahh"):
        assert not is_valid(bad)
    assert parse_valid(["As", "2x", "As", "Kd"]) == [48, parse("Kd")]
    assert parse_valid("As") == []


def test_preflop_all_in_then_discard_request_syncs_everything():
    b = Brain()
    b.on_init({"total_hands": 200, "time_bank_ms": 30000})
    b.on_new_hand({"hand_id": 7, "seat": "button", "hole_cards": ["Qc", "Jc", "3h"]})
    b.act({"type": "action_request", "hand_id": 7, "street": "preflop", "board": [], "pot": 3,
           "my_bet": 1, "opp_bet": 2, "to_call": 1, "my_stack": 199, "opp_stack": 198,
           "legal_actions": ["fold", "call", "raise"], "min_raise": 4, "max_raise": 200,
           "raises_left": 3, "history": [], "time_left_ms": 30000})
    # We shoved, opponent called: the engine skips flop betting and sends the discard request.
    req = {"type": "discard_request", "hand_id": 7, "hole_cards": ["Ah", "9d", "4s"],
           "board": ["Kh", "7d", "2s"], "pot": 400, "my_stack": 0, "opp_stack": 0, "time_left_ms": 29950}
    reply = b.discard(req)
    h = b.hand
    assert h.hole_strs == ["Ah", "9d", "4s"]
    assert h.hole3 == h.hole == parse_valid(["Ah", "9d", "4s"])
    assert h.board == parse_valid(["Kh", "7d", "2s"])
    assert (h.pot, h.my_stack, h.opp_stack, h.street) == (400, 0, 0, "flop")
    assert dead_set(h) == {"Ah", "9d", "4s", "Kh", "7d", "2s"}      # stale new_hand cards are gone
    assert reply == {"type": "discard", "card": "4s"}


def test_same_length_board_replacement_drops_stale_card():
    h = HandState(3, "big_blind", ["As", "Kd", "7c"])
    base = {"type": "action_request", "hand_id": 3, "street": "turn", "legal_actions": ["check"]}
    h.update_from_request({**base, "board": ["2h", "3h", "4h", "5h"]})
    assert "5h" in dead_set(h)
    h.update_from_request({**base, "board": ["2h", "3h", "4h", "9c"]})
    assert h.board == parse_valid(["2h", "3h", "4h", "9c"])
    assert "9c" in dead_set(h) and "5h" not in dead_set(h)


def test_dead_grows_monotonically_through_a_normal_hand():
    b = Brain()
    b.on_new_hand({"hand_id": 1, "seat": "big_blind", "hole_cards": ["As", "Kd", "7c"]})
    seen = [dead_set(b.hand)]
    act = {"type": "action_request", "hand_id": 1, "legal_actions": ["check"], "time_left_ms": 30000}
    b.act({**act, "street": "preflop", "board": []})
    seen.append(dead_set(b.hand))
    b.act({**act, "street": "flop", "board": ["Ah", "7d", "2s"]})
    seen.append(dead_set(b.hand))
    b.discard({"type": "discard_request", "hand_id": 1, "hole_cards": ["As", "Kd", "7c"],
               "board": ["Ah", "7d", "2s"], "pot": 4, "my_stack": 198, "opp_stack": 198})
    seen.append(dead_set(b.hand))
    b.on_discard_result({"type": "discard_result", "hand_id": 1, "my_discard": "7c",
                         "opp_discard": "3c", "hole_cards": ["As", "Kd"]})
    seen.append(dead_set(b.hand))
    assert b.hand.hole == parse_valid(["As", "Kd"]) and len(b.hand.hole3) == 3
    b.act({**act, "street": "turn", "board": ["Ah", "7d", "2s", "Td"]})
    seen.append(dead_set(b.hand))
    b.act({**act, "street": "river", "board": ["Ah", "7d", "2s", "Td", "Jh"]})
    seen.append(dead_set(b.hand))
    for before, after in zip(seen, seen[1:]):
        assert before <= after
    assert seen[-1] == {"As", "Kd", "7c", "Ah", "7d", "2s", "3c", "Td", "Jh"}
    b.on_hand_result({"type": "hand_result", "hand_id": 1, "net": 2, "result": "showdown"})
    assert b.hand is None and b.leg.hands_done == 1 and b.leg.net == 2


def test_action_request_for_unknown_hand_creates_minimal_state():
    b = Brain()
    reply = b.act({"type": "action_request", "hand_id": 99, "street": "flop", "board": ["Ah", "7d", "2s"],
                   "legal_actions": ["fold", "call"], "to_call": 5})
    assert reply == {"action": "call"}
    assert b.hand.hand_id == 99 and dead_set(b.hand) == {"Ah", "7d", "2s"}


def test_notice_is_counted():
    b = Brain()
    b.on_notice({"type": "notice", "code": "illegal_action", "applied": "fold"})
    assert b.leg.notices == 1
