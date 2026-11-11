ROUND 2 REVIEW of `agents/plans/F01_engine_skeleton.md`

B1 [major] §3.1 / §3.4 malformed legal_actions fallback — The new tests require non-list legal_actions to produce a complete check reply, but legal_actions=7 makes membership checks in fallback_action and the final fallback raise TypeError. The fallback_action call in the exception handler is outside the subsequent legality try. Separately, make_legal's missing/empty/non-list branch explicitly returns {"action":"check"} without the required type. — Normalize legal_actions before every fallback membership check, protect fallback execution, and return {"type":"action","action":"check"} for this input class. Test missing, null, integer, and empty-list values through the protocol loop.

B2 [major] §3.1 `elif t in HANDLERS` — The new dictionary dispatch raises TypeError for a parsed JSON object with an unhashable type, such as {"type":[]} or {"type":{}}. This happens outside dispatch's exception guard and prevents later valid requests from being answered. — Ignore non-string message types before dictionary lookup and add both examples followed by a valid request to the robustness tests.

B3 [major] §3.2 / §3.5 discard synchronization — The revised handler updates hole_strs and hole3 but omits the separate public hand.hole field. When discard_request replaces the new_hand cards, hand.hole remains stale. The new replacement-card test also omits this field. — Set hand.hole to the parsed current cards alongside hole3 before the discard policy, and assert both in the state test.

B4 [minor] §6D “3,000 < 1.25 × 2,400” — Both sides equal 3,000. With hand_id=200, the specified per-hand budget is 600 ms and the tier is normal, contradicting the unconditional panic expectation. — Specify the hand id in the test and assert the tier from both conditions. Use 2,999 ms for a case that must panic regardless of remaining hands, and test equality at 3,000 separately.

B5 [minor] §3.5 “rebuild dead if the board grew” — The same section says every request's board is authoritative and dead is rebuilt whenever a source changes. A replacement board of the same length changes board without rebuilding dead under the stated action-update rule. — Rebuild when board contents change, and test a same-length replacement so stale dead cards are removed.

VERDICT: 5 bugs

