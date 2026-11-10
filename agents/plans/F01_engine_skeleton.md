# F01: Engine skeleton (protocol loop, legality, state, clock, fallbacks)

**Status:** in review (round 1)
**Workstream:** W1 · **Strategy items:** 01/R1–R6, 01/R5b, 02/E5 · **Owner:** Claude (implements) · **Reviewer:** Codex

## 1. Goal
Replace the single-file starter bot with a modular skeleton that **never forfeits and is never corrected by the
engine** (0 `notice`s, 0 forfeits, exactly one reply per request), while playing **exactly like champion v0**
(check if legal, else call; discard the lowest rank), so later features change one thing at a time against a
known baseline.

## 2. Scope
**In:** `bot/bot.py` (protocol loop), `bot/brain.py` (dispatch + firewall), `bot/legal.py` (legality layer +
fallbacks), `bot/state.py` (hand and leg state, dead cards), `bot/timing.py` (clock and tiers), `bot/cards.py`
(parse/format only), `bot/log.py` (stderr debug logging), `bot/opponent.py` (neutral stub), `bot/placeholder.py`
(v0 policies), `bot/params.py` (W1 section), and tests.
**Out (later features):** any strategy change (F04–F06), the evaluator and equity (F02), opponent statistics (F12).

**Interface changes to `agents/INTERFACES.md`, applied on approval:**
- `cards.py`: F01 owns `parse`, `fmt`, `RANKS`, `SUITS`, `is_valid`; F02 adds `deck_without` and the rest.
- New `log.py`: `log(*parts)`.
- New `placeholder.py`: `v0_action(req)`, `v0_discard(hole_cards)`. Deleted once F04–F06 replace them.
- `legal.py` gains `make_legal_discard(card, req) -> dict`.

## 3. Design

### 3.1 `bot.py`: protocol loop (the only stdout writer)
```
PROTO = sys.stdout            # saved before anything else
sys.stdout = sys.stderr       # any stray print() anywhere goes to stderr, never to the engine
brain = construct Brain() inside try; on failure brain = None (log the traceback)
for raw in sys.stdin:                       # Python 3 text-mode iteration is line-buffered: no read-ahead stall
    line = raw.strip(); skip if empty
    msg = json.loads(line) in try; skip on error; skip if not a dict
    t = msg.get("type")
    if t == "action_request":  reply = respond_action(brain, msg);  send(reply)
    elif t == "discard_request": reply = respond_discard(brain, msg); send(reply)
    elif t == "match_end": safe(brain.on_match_end, msg); break
    elif t in ("init", "new_hand", "discard_result", "hand_result", "notice"): safe(handler, msg)
    else: ignore                            # forward compatibility
exit normally (code 0) after match_end or EOF
```
- `respond_action(brain, req)`: `intent = brain.act(req)` inside try. On any exception or `brain is None`,
  `intent = fallback_action(req)`. Then `reply = make_legal(intent, req)` inside try. If *that* raises,
  `reply = {"type":"action","action":"check" if "check" in L else "fold"}`, where L comes from
  `req.get("legal_actions")` or `[]`. **Every branch produces exactly one dict, and `send` is called exactly
  once per request.**
- `respond_discard` works the same way, with `make_legal_discard`, and finally `{"type":"discard","card": first valid card in hole_cards, else "2s"}`.
- `send(reply)`: `PROTO.write(json.dumps(reply, separators=(",",":")) + "\n"); PROTO.flush()`. On
  `BrokenPipeError`/`OSError`: exit quietly (the engine is gone).
- `safe(fn, msg)`: call; on exception log the traceback (rate-limited), never raise.
- `json.dumps` only ever sees Python `str`/`int`, because `make_legal` casts the amount with `int()`. A future numpy
  integer can't reach `dumps`.

### 3.2 `brain.py`: dispatch
- `Brain()` holds `LegState` and the current `HandState` (or None), plus `OppModel()` (stub).
- `on_init(msg)`: store `total_hands` (default 200), `time_bank_ms` (default 30000), `per_response_ms` (default
  5000), `small_blind`, `big_blind`, `starting_stack` (defaults 1, 2, 200).
- `on_new_hand(msg)`: a fresh `HandState` from `hand_id`, `seat`, `hole_cards`. Invalid or missing cards are kept as
  given strings, so the v0 discard still works.
- `act(req)`: `self.clock.start(req, self.leg, self.hand)`; ensure a HandState exists for `req["hand_id"]`
  (create a minimal one if `new_hand` was missed or ids differ); `hand.update_from_request(req)`; return
  `placeholder.v0_action(req)`.
- `discard(req)`: start the clock; ensure the hand; `hand.hole_strs = req["hole_cards"]`; return
  `{"type":"discard","card": placeholder.v0_discard(req["hole_cards"])}`.
- `on_discard_result(msg)`: record `my_discard`, `opp_discard`, the kept `hole_cards`; mark `opp_discard` dead.
- `on_hand_result(msg)`: `leg.record(msg)` (net, result, opp cards shown); `opp.observe_showdown(...)`
  (stub no-op); drop the hand state.
- `on_notice(msg)`: `leg.notices += 1`; log it. Any notice is a bug, surfaced by tests and the gate.
- `on_match_end(msg)`: log a one-line leg summary.

### 3.3 `placeholder.py`: exact v0 behaviour
- `v0_action(req)`: `{"action":"check"}` if `"check"` ∈ legal; elif `"call"` ∈ legal → call; else fold.
  This is identical to `starter_kit/bot.py::choose_action`.
- `v0_discard(hole_cards)`: `min(hole_cards, key=lambda c: "23456789TJQKA".index(c[0]))`. Python's `min`
  returns the **first** minimal element in list order, identical to `starter_kit/bot.py::choose_discard`. If a
  card string is malformed, `index` raises; the firewall then uses `fallback_discard`.

### 3.4 `legal.py`: one legality boundary
Inputs follow the engine (`starter_kit/engine.py::betting_round`, `parse_action`): `L = req["legal_actions"]`. `fold`
and `call` are in L iff `to_call > 0`; `check` iff `to_call == 0`; `raise` iff the cap isn't reached and
`max_raise > opp_bet`. `min_raise`/`max_raise` are present only when raise ∈ L, and `min_raise = max_raise`
for short all-ins.

`make_legal(intent, req) -> {"type":"action","action":a[, "amount":int]}`:

| Intent | Raise ∈ L | Result |
|---|---|---|
| raise x | yes | `amount = clamp(to_int(x, default=min_raise), min_raise, max_raise)` |
| raise x | no | `call` if ∈ L, else `check` |
| call | — | `call` if ∈ L, else `check` (calling 0 = checking) |
| check | — | `check` if ∈ L, else `fold` (same as the engine's correction, but with no notice) |
| fold | — | `fold` if ∈ L, else `check` (never fold for free) |
| anything else / missing | — | `fallback_action(req)` |

- `to_int(x, default)`: accepts int (not bool), finite float (rounded half-up), or a numeric string; anything else
  (None, NaN, ±inf, bool, a non-numeric string) gives `default`. The engine rejects `bool` amounts as malformed, so
  bool must never pass through.
- If `min_raise`/`max_raise` are missing or not ints while raise ∈ L (protocol violation): treat raise as not legal.
- If L is missing, empty or not a list: return `{"action":"check"}`. The engine will correct it if needed; this
  can't happen with a correct engine.
- `fallback_action(req)`: `check` if ∈ L, else `fold`.

`make_legal_discard(card, req)`:
- `hole = req["hole_cards"]`. If `card` is a string in `hole`, reply with it.
- Otherwise `fallback_discard(hole)`, which mirrors `engine.default_discard`: the lowest rank, ties broken
  s < h < d < c, over the **valid** cards in `hole`. If none is valid, use `hole[0]` if it exists, else `"2s"`.

### 3.5 `state.py`
- `HandState`: `hand_id`, `seat` (`"button"`/`"big_blind"`), `hole_strs` (as received), `hole` (ints, 3 then 2),
  `board` (ints), `street`, `pot`, `my_bet`, `opp_bet`, `to_call`, `my_stack`, `opp_stack`, `history` (as
  received), `my_discard`, `opp_discard`, `dead: bytearray(52)`.
- `dead` = our 3 original hole cards + the board + `opp_discard` once known. Our own discard is already in our
  original 3. **Invariant:** `dead` never loses a card during a hand; tests assert this.
- `update_from_request(req)`: copy the fields with `.get` and defaults; parse cards, skipping invalid ones; mark
  board cards dead.
- `LegState`: `total_hands`, `time_bank_ms`, `per_response_ms`, `hands_done`, `net`, `notices`, `results`
  (bounded list of small dicts, max 1,000 entries).
- **No state survives the process** (no file writes), so nothing carries across legs.

### 3.6 `timing.py`: `Clock`
Used by later features; F01 implements and tests it, and starts it on every request.
- `start(req, leg, hand)`: `t0 = perf_counter()`; `time_left = req.get("time_left_ms")` (fallback: the last
  known value, else `leg.time_bank_ms`); `remaining_hands = max(1, total_hands − hand_id + 1)`.
- `reserve_ms = max(RESERVE_MIN_MS=1500, RESERVE_FRAC=0.08 × time_bank_ms)`: 2,400 ms in Stage 1, 6,000 ms in Stage 2.
- `per_hand_ms = max(0, time_left − reserve_ms) / remaining_hands`.
- `tier()`: `panic` if `time_left < 1.25 × reserve_ms` or `per_hand_ms < 25`; `throttle` if `per_hand_ms < 80`;
  else `normal`. Stage 1 starts at (30000 − 2400)/200 = 138 ms, so normal.
- `budget_ms(kind)` with SHARE = {preflop 0.02, flop 0.25, discard 0.30, turn 0.23, river 0.20}:
  `per_hand_ms × SHARE[kind] × TARGET_USE (0.65)`, ×0.5 in throttle, 0 in panic; clamped to
  `[0, min(MAX_DECISION_MS=400, 0.2 × per_response_ms)]`.
- `elapsed_ms()`, `expired(budget)`: from `t0`. All constants live in `params.py`.
- The engine's clock starts when it *sends*; ours when we *parse*. The pipe latency gap is small and covered by
  the reserve.

### 3.7 `cards.py`, `log.py`, `opponent.py`, `params.py`
- `cards.py`: `RANKS="23456789TJQKA"`, `SUITS="shdc"`, `parse("As") -> 12*4+0 = 48`, `fmt(48) -> "As"`,
  `is_valid(s)`. `parse` raises `ValueError` on bad input; callers in `state.py` catch it.
- `log.py`: writes to `sys.stderr` only when env `POKERBOT_DEBUG=1`; hard cap of 48 KB per process (the engine
  keeps 64 KB); never raises. Exception tracebacks are logged regardless of the env var, but count towards the cap.
- `opponent.py`: `OppModel` with no-op `observe_action`/`observe_showdown`, `stat(name)` returning priors,
  `archetype_weights() -> {"neutral": 1.0}`, `range_weights(...) -> None`.
- `params.py`: `# --- W1 ---` section with the clock constants above. No logic.

## 4. Edge cases (and handling)
1. `action_request` before any `new_hand`, or with a different `hand_id` → minimal HandState from the request.
2. `raise` ∈ L with `min_raise == max_raise` (short all-in) → the clamp yields exactly that amount.
3. `raise` absent while `raises_left > 0` (opponent all-in) → a raise intent maps to call.
4. Preflop, the button facing the BB (to_call = 1) → v0 calls. The BB option after a limp (to_call = 0) → v0 checks.
5. All-in before the flop → no action requests on later streets, but `discard_request` still arrives → v0 discard,
   with `my_stack == 0` → no division by stack anywhere.
6. `discard_request` hole cards differ from the `new_hand` cards → trust the request.
7. Duplicate cards, malformed card strings or 2-card hole lists in a request → parse what's valid; the discard
   comes from the request's list; never crash.
8. A `notice` arrives (shouldn't) → counted and logged; no reply.
9. Unknown message types and extra fields → ignored.
10. EOF without `match_end` → leave the loop, exit 0.
11. Our reply arrives "late" (an engine bug) → not our concern; we never send unsolicited lines.
12. Hand ids restart at 1 in leg 2 → it's a new process anyway.

## 5. Failure handling and time
- Every handler is wrapped. `respond_*` has three layers (brain → legality → hardcoded) and always replies exactly once.
- The start-up path imports only stdlib modules (no numpy in F01). Measured start-up is reported in the PR (target < 100 ms).
- F01 does no heavy computation. Expected per-decision cost < 0.5 ms. The clock is wired for later features.
- stderr volume is capped (§3.7), so the engine's 64 KB truncation never hides the first traceback.

## 6. Tests (check two ways)
**A. Legality: two independent checks.**
1. `tests/test_legal.py`: a generator builds requests with the engine's own formulas (copied from `betting_round`
   into a test helper with a comment pointing to the source): random bets, stacks, `last_raise`, `raises`,
   `street`. For ~20,000 requests × every intent (fold/check/call/raise with amounts: in range, below, above,
   negative, float, `"12"`, `"abc"`, None, NaN, inf, True), assert that the reply would pass
   `engine.parse_action` (imported from `starter_kit/engine.py`) with no error code.
2. **Chaos bot** (`tests/chaos_bot.py`, test-only): uses `bot/` modules but replaces `Brain.act`/`discard` with
   seeded random *garbage* intents (illegal actions, wrong amounts, cards not in hand). Run 2 × 200 hands vs
   `random_bot` and vs `starter` through the real engine and assert **0 notices, 0 forfeits**, proving the
   legality layer in the engine's own judgement.

**B. Protocol robustness:** `tests/test_protocol.py`, extended. Feed `bot.py` scripted stdin: malformed JSON,
non-dict JSON, unknown types, an `action_request` before `new_hand`, missing `legal_actions`, missing
`min_raise` while raise is legal, a 2-card `hole_cards`, an invalid card string, EOF without `match_end`. Assert:
one reply per request (count exact), every reply parses with `engine.parse_action`/`parse_discard` against its
request, exit code 0, finishes within 5 s.

**C. Exact v0 equivalence: two independent checks.**
1. Engine head-to-head, the new bot vs `champion/bot/bot.py`, on 10 seeds × 400 hands: **net exactly 0 in every
   match** (identical deterministic strategies cancel under duplicate deals).
2. `match.log` of (the new bot vs `starter`) is **line-for-line identical** to (v0 vs `starter`) on the same 5 seeds,
   apart from bot labels.

**D. Clock:** `tests/test_timing.py`. Tier boundaries (exact thresholds); budgets never negative and never above
the caps; `time_left_ms` missing or 0 or negative → panic with budget 0; Stage 1 and Stage 2 values match §3.6.

**E. Engine runs:** `scripts/arena.py --rivals random starter --stage 2 --seeds 4` → 0 notices, 0 forfeits.
`scripts/build.py --check` passes.

## 7. Acceptance criteria
- [ ] All tests in §6 pass; `pytest` is green.
- [ ] 0 notices and 0 forfeits in every engine run, including the chaos-bot runs.
- [ ] v0 equivalence: C1 and C2 both hold, so **no promotion** (behaviour unchanged). Committed to `main` as infrastructure.
- [ ] `scripts/build.py --check` passes; no `print(` to stdout outside `bot.py`'s `send`.
- [ ] `agents/INTERFACES.md` updated with the §2 changes.

## 8. Risks and open questions (for the reviewer)
1. **Fallback when facing a bet after an internal error:** `fold` (chosen; minimal risk) vs calling small bets.
   Errors should be ~0, so this only matters as a safety net.
2. **Reserve and tier thresholds** (8% of the bank, 25 / 80 ms) are initial values, to be tuned once real
   computation exists (F02+).
3. **Redirecting `sys.stdout` to stderr** protects the protocol from any stray print, but means any library writing to
   stdout writes to stderr. Intended.
4. Should `make_legal` also snap raises close to all-in up to all-in? Decided **no**: that's a strategy decision,
   left to F09, so the legality layer stays pure.

## Review log
### Round 1: 2026-11-10
_Awaiting Codex review._
