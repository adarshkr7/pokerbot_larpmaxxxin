ROUND 1 REVIEW of `agents/plans/F01_engine_skeleton.md`

B1 [major] §3.1 `safe(brain.on_match_end, msg)` — If Brain construction fails, `brain` is `None`. Accessing `brain.on_match_end` raises before `safe()` runs, defeating the promised clean exit. — Guard absent brains and perform handler lookup inside the protected call. Test constructor failure followed by requests and `match_end`.

B2 [major] §3.2 `discard(req)` — The handler updates only `hole_strs`, leaving the parsed hole cards, board, dead mask, pot, and stacks stale. After a preflop all-in, the flop first arrives in the discard request because the engine skips flop betting. — Synchronize state from every discard request before invoking the policy. Test the preflop-all-in sequence and replacement hole cards.

B3 [major] §3.4 `make_legal_discard` — Membership alone accepts malformed cards. With `["2x","As","Kd"]`, the placeholder selects `"2x"` and the boundary accepts it, but the engine returns `malformed`. — Require both `is_valid(card)` and membership, then fall back to a valid card from the hand.

B4 [major] §6B “every reply parses … against its request” — The proposed missing-`legal_actions` test cannot satisfy this assertion. `engine.parse_action` directly indexes that field and raises `KeyError`. A hand containing no valid cards also cannot produce a legal discard. — Specify liveness, reply shape, and fallback assertions for malformed requests. Use well-formed requests for engine legality assertions.

B5 [minor] §6C2 “line-for-line identical … apart from bot labels” — `match.log` includes measured execution time and output paths, which can differ despite identical play. — Compare deterministic hand records and result fields, excluding timing, paths, and labels.

B6 [minor] §3.6 versus §6D, missing `time_left_ms` — The design falls back to the last known bank or initial bank, while the test requires panic and zero budget. Initially, the specified fallback yields 138 ms per hand and normal mode. — Choose one missing-clock policy and align the design and tests.

B7 [major] §2 interface changes — The plan changes `Clock.start(req)` to `start(req, leg, hand)` and `expired()` to `expired(budget)` without declaring those changes to the shared contract. — Explicitly list and update both signatures in `agents/INTERFACES.md`, or preserve the existing signatures.

B8 [major] §6E and §7 timing acceptance — The Stage 2 command omits `--jobs 1`, so the arena defaults to concurrent matches. The acceptance criteria also impose no measured bank-use threshold, allowing an almost-exhausted bank to pass. — Run timing validation with `--jobs 1` and enforce the repository’s local ≤40% bank target, accounting for the engine summary reporting time summed across both legs.

VERDICT: 8 bugs
