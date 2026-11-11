# F01: Engine skeleton (protocol loop, legality, state, clock, fallbacks)

**Status:** approved (round 3)
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
- `legal.py` gains `make_legal_discard(card, req) -> dict` and `legal_list(req) -> list[str] | None`;
  `fallback_action(req)` keeps its signature and returns a complete `{"type":"action",...}` dict.
- `brain.py`: `Brain` gains `on_match_end(msg)` (not in the current contract).
- `timing.py`: the constructor becomes `Clock(leg: LegState)` (the clock reads `total_hands` and `time_bank_ms`
  from the leg it is given); `start(req)` **keeps its current signature** (the hand id comes from `req`);
  `expired()` **changes to** `expired(budget_ms: float) -> bool`, because a decision can run several budgeted
  phases and a hidden "current budget" field would couple them. Both changes go into `agents/INTERFACES.md`.
- `state.py`: `HandState` gains `update_from_request(req)` and `update_from_discard_request(req)`.

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
    if not isinstance(t, str): skip         # {"type":[]} / {"type":{}} would make `t in HANDLERS` raise
    if t == "action_request":  reply = respond_action(brain, msg);  send(reply)
    elif t == "discard_request": reply = respond_discard(brain, msg); send(reply)
    elif t == "match_end": dispatch(brain, "on_match_end", msg); break
    elif t in HANDLERS: dispatch(brain, HANDLERS[t], msg)   # init/new_hand/discard_result/hand_result/notice
    else: ignore                            # forward compatibility
exit normally (code 0) after match_end or EOF
```
- `dispatch(brain, name, msg)`: does nothing if `brain is None`; otherwise looks the handler up **and** calls it
  inside one `try` (`getattr(brain, name)(msg)`), so neither a missing Brain nor a missing/raising handler can
  escape. On exception: log the traceback (rate-limited), never raise. No code path dereferences `brain` outside
  `dispatch`/`respond_*`.
- **Defence in depth:** the body of each loop iteration (from `json.loads` to `send`) runs inside one outer `try`.
  If anything escapes it while handling an `action_request`/`discard_request` *before* that request's `send`
  (tracked by a `replied` flag), the outer handler sends the constant reply `{"type":"action","action":"check"}` /
  `{"type":"discard","card":"2s"}` once; otherwise it only logs. The loop then continues with the next line, so one
  bad message can never stop later requests from being answered.
- `legal_list(req) -> list[str] | None` (in `legal.py`, never raises): returns the `str` elements of
  `req.get("legal_actions")` if that is a `list`, else `None`. Every membership test on legal actions, in every
  layer, goes through it, so `legal_actions = 7` / `null` / `"check fold"` can't raise or match substrings.
- `respond_action(brain, req)`: three layers, **each in its own `try`**:
  1. `intent = brain.act(req)`; on exception or `brain is None`, `intent = None`.
  2. `reply = make_legal(intent, req)`; `make_legal` maps a `None`/unknown intent to `fallback_action(req)` itself,
     so the fallback runs inside this protected layer, not in an exception handler.
  3. If layer 2 raises: `reply = {"type":"action","action":"check"}` if `L` is `None`/empty or `"check" ∈ L`, else
     `"fold"`, with `L = legal_list(req)`, itself in a `try` whose `except` uses the constant
     `{"type":"action","action":"check"}`.

  **Every branch produces exactly one complete dict (with `"type"`), and `send` is called exactly once per request.**
- `respond_discard` works the same way, with `make_legal_discard`, and finally `{"type":"discard","card": c}` where
  `c` = the first valid card in `hole_cards`, else `hole_cards[0]` if it is a string, else `"2s"` (same order as §3.4).
- The loop lives in `main()`, called under `if __name__ == "__main__":`, so tests can import `bot` and patch
  `brain.Brain` before running it (§6B).
- `send(reply)`: `PROTO.write(json.dumps(reply, separators=(",",":")) + "\n"); PROTO.flush()`. On
  `BrokenPipeError`/`OSError`: exit quietly (the engine is gone).
- `json.dumps` only ever sees Python `str`/`int`, because `make_legal` casts the amount with `int()`. A future numpy
  integer can't reach `dumps`.

### 3.2 `brain.py`: dispatch
- `Brain()` holds `LegState` and the current `HandState` (or None), plus `OppModel()` (stub).
- `on_init(msg)`: store `total_hands` (default 200), `time_bank_ms` (default 30000), `per_response_ms` (default
  5000), `small_blind`, `big_blind`, `starting_stack` (defaults 1, 2, 200).
- `on_new_hand(msg)`: a fresh `HandState` from `hand_id`, `seat`, `hole_cards`. Invalid or missing cards are kept as
  given strings, so the v0 discard still works.
- `act(req)`: `self.clock.start(req)`; ensure a HandState exists for `req["hand_id"]`
  (create a minimal one if `new_hand` was missed or ids differ); `hand.update_from_request(req)`; return
  `placeholder.v0_action(req)`.
- `discard(req)`: `self.clock.start(req)`; ensure the hand; `hand.update_from_discard_request(req)`, which
  synchronises **everything** the request carries before the policy runs: `hole_strs`, `hole3` **and `hole`** (all
  three from the request's `hole_cards`; `hole` and `hole3` are the same parsed list until `discard_result`), `board` (the flop), `street = "flop"`, `pot`, `my_stack`, `opp_stack`, then rebuilds `dead`
  (§3.5). This matters after a preflop all-in: the engine skips flop betting (`betting_round` returns at once
  when a stack is 0), so the `discard_request` is the first message that carries the flop. Then return
  `{"type":"discard","card": placeholder.v0_discard(hand.hole_strs)}`.
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
- `L = legal_list(req)` (§3.1). If `L` is `None` or empty (missing, `null`, integer, string, `[]`): return
  `{"type":"action","action":"check"}`. The engine will correct it if needed; this can't happen with a correct engine.
- `fallback_action(req)`: `{"type":"action","action":"check"}` if `L` is `None`/empty or `"check" ∈ L`, else
  `{"type":"action","action":"fold"}`. Never raises.
- Every return value of `make_legal` and `fallback_action` is a complete reply dict including `"type":"action"`.

`make_legal_discard(card, req)`:
- `hole = req.get("hole_cards")` (treated as `[]` if not a list). Accept `card` only if it is a `str`, **`is_valid(card)`**
  (rank in `RANKS`, suit in `SUITS`, length 2: the same set as the engine's `VALID_CARDS`) **and** `card in hole`.
  Both conditions are required: membership alone would accept `"2x"` from `["2x","As","Kd"]`, which the engine
  rejects as `malformed`.
- Otherwise `fallback_discard(hole)`, which mirrors `engine.default_discard`: the lowest rank, ties broken
  s < h < d < c, over the **valid** cards in `hole` only (here `"As"`/`"Kd"` → `"Kd"`).
- If `hole` contains no valid card, no legal discard exists. We still reply exactly once (with `hole[0]` if it is a
  string, else `"2s"`), and the engine applies its default. This cannot happen with a correct engine; §6B tests only
  liveness and reply shape for it.

### 3.5 `state.py`
- `HandState`: `hand_id`, `seat` (`"button"`/`"big_blind"`), `hole_strs` (as received), `hole3` (ints: our 3
  pre-discard cards, from the latest authoritative source), `hole` (ints, 3 then 2), `board` (ints), `street`, `pot`,
  `my_bet`, `opp_bet`, `to_call`, `my_stack`, `opp_stack`, `history` (as received), `my_discard`, `opp_discard`,
  `dead: bytearray(52)`.
- `dead` is **rebuilt** (not patched) from the authoritative sources at the end of **every** update
  (`new_hand`, every action request, the discard request, `discard_result`): `hole3 ∪ board ∪ {opp_discard}`.
  Rebuilding 52 bytes costs microseconds, and unconditional rebuilds mean a changed board of the same length can't
  leave stale cards behind. Our own discard stays dead because it is in `hole3`. Sources, latest wins:
  `new_hand.hole_cards` → `discard_request.hole_cards` (sets `hole3`); every request's `board`;
  `discard_result.opp_discard`. `discard_result.hole_cards` sets `hole` (2 cards) but not `hole3`.
- **Invariant (consistent engine):** `dead` never loses a card during a hand; tests assert this on real engine
  sequences. If a request contradicts earlier data (edge case 6), the request wins and stale cards are dropped
  rather than kept as phantom dead cards.
- `update_from_request(req)` (action requests): copy the fields with `.get` and defaults; parse cards, skipping
  invalid ones; replace `board` with the request's board; rebuild `dead`.
- `update_from_discard_request(req)`: see §3.2.
- `LegState`: `total_hands`, `time_bank_ms`, `per_response_ms`, `hands_done`, `net`, `notices`, `results`
  (bounded list of small dicts, max 1,000 entries).
- **No state survives the process** (no file writes), so nothing carries across legs.

### 3.6 `timing.py`: `Clock`
Used by later features; F01 implements and tests it, and starts it on every request.
- `Clock(leg)`: keeps a reference to the `LegState` (for `total_hands`, `time_bank_ms`, `per_response_ms`).
- `start(req)`: `t0 = perf_counter()`; `remaining_hands = max(1, total_hands − hand_id + 1)` (`hand_id` from
  `req`, defaulting to the last seen id, else 1).
- **Missing-clock policy (one rule, used by both design and tests):** if `time_left_ms` is present and a finite
  number, use it (≤ 0 counts as 0 → panic). If it is **absent or non-numeric**, use the last value received in this
  leg; if none was ever received, use `leg.time_bank_ms` (the full bank, as at the start of a leg). The engine sends
  `time_left_ms` on every request (`engine.py`, `Bot.begin`), so absence is a protocol defect and we degrade to the
  best estimate instead of crippling every later decision with panic.
- `reserve_ms = max(RESERVE_MIN_MS=1500, RESERVE_FRAC=0.08 × time_bank_ms)`: 2,400 ms in Stage 1, 6,000 ms in Stage 2.
- `per_hand_ms = max(0, time_left − reserve_ms) / remaining_hands`.
- `tier()`: `panic` if `time_left < 1.25 × reserve_ms` or `per_hand_ms < 25`; `throttle` if `per_hand_ms < 80`;
  else `normal`. Stage 1 starts at (30000 − 2400)/200 = 138 ms, so normal.
- `budget_ms(kind)` with SHARE = {preflop 0.02, flop 0.25, discard 0.30, turn 0.23, river 0.20}:
  `per_hand_ms × SHARE[kind] × TARGET_USE (0.65)`, ×0.5 in throttle, 0 in panic; clamped to
  `[0, min(MAX_DECISION_MS=400, 0.2 × per_response_ms)]`.
- `elapsed_ms()`; `expired(budget_ms) -> bool` is `elapsed_ms() >= budget_ms`, both from `t0`. All constants live in `params.py`.
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
5. All-in before the flop → no action requests on later streets, but `discard_request` still arrives and is the
   first message with the flop → `update_from_discard_request` sets board/pot/stacks/dead before the v0 discard;
   `my_stack == 0` → no division by stack anywhere.
6. `discard_request` hole cards differ from the `new_hand` cards → trust the request: `hole3` is replaced and
   `dead` rebuilt (§3.5).
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

**B. Protocol robustness:** `tests/test_protocol.py`, extended. Feed `bot.py` (as a subprocess) scripted stdin.
For **every** script assert *liveness*: exactly one reply line per `action_request`/`discard_request` (count
exact, in order), no other stdout lines, every reply is one JSON object of the right `type`, exit code 0, finishes
within 5 s. Then, per request class:

| Input | Extra assertion |
|---|---|
| Well-formed requests (including: `action_request` before `new_hand`, a different `hand_id`, a 2-card `hole_cards` with valid cards, `["2x","As","Kd"]`) | `engine.parse_action(reply, req)` / `engine.parse_discard(reply, req["hole_cards"])` returns no error code. For `["2x","As","Kd"]` the reply is `"Kd"`. |
| `legal_actions` missing, `null`, `7`, `"check fold"` or `[]`, each sent through the protocol loop (subprocess), also with a Brain whose `act` raises | Reply is exactly `{"type":"action","action":"check"}` (the documented fallback). Not run through `parse_action`, which indexes the field. Plus unit tests that `legal_list`, `fallback_action` and `make_legal` never raise on these inputs and always include `"type"`. |
| Messages `{"type":[]}` and `{"type":{}}`, each followed by a valid `action_request` | No reply to them; the following request is answered legally. |
| `raise` legal but `min_raise` missing or non-int | Reply is `call` if in L, else `check` (raise treated as illegal); `parse_action` against a copy of the request with `raise` removed from L returns no error. |
| `hole_cards` with no valid card (e.g. `["zz","1x"]`), or missing | Reply shape only: `{"type":"discard","card":<str>}`, equal to `hole[0]` / `"2s"` per §3.4. |
| Malformed JSON, non-dict JSON, unknown types, extra fields | No reply line produced for them; later requests still answered. |
| EOF without `match_end` | Exit 0. |
| `Brain()` constructor raising (a tiny test wrapper script patches `brain.Brain.__init__` to raise, then calls `bot.main()`), followed by `init`, `new_hand`, an `action_request`, a `discard_request`, `hand_result` and `match_end` | The fallback replies are legal per `parse_action`/`parse_discard`; exit code 0 after `match_end`; a traceback appears on stderr. |
| Preflop all-in sequence: `new_hand` → button raises all-in → `discard_request` with a flop and `hole_cards` different from `new_hand` | In-process test on `Brain`: after `discard(req)` the `HandState` has the request's `hole_strs`, `hole3` **and `hole`** (both equal to the parsed request cards), `board`, `pot`, `my_stack`, `opp_stack`, and `dead` = request hole ∪ flop (the stale `new_hand` cards are gone); the reply is the v0 discard of the request's cards. |
| Same-length board replacement: two consecutive turn `action_request`s for one hand whose boards differ in one card | In-process test on `HandState`: after the second update, `board` and `dead` contain the new card and **not** the replaced one. |

**C. Exact v0 equivalence: two independent checks.**
1. Engine head-to-head, the new bot vs `champion/bot/bot.py`, on 10 seeds × 400 hands: **net exactly 0 in every
   match** (identical deterministic strategies cancel under duplicate deals).
2. On the same 5 seeds, (the new bot vs `starter`) and (v0 vs `starter`) produce **identical deterministic play**.
   Compared from `match.log`: every per-hand record (hand id, deal, actions, discards, board, result, net), plus
   the summary's `N of M hands played`, both `net` values, `notices`, the `Result:` line and the `Capped delta`
   line. Excluded: `time used`, the `Logs:` path line and the bot labels, which legitimately differ between runs.
   The test parses both logs, drops the excluded fields, and asserts equality.

**D. Clock:** `tests/test_timing.py`, following the single missing-clock policy of §3.6. Tier boundaries (exact
thresholds); budgets never negative and never above the caps; `time_left_ms` = 0 or negative → panic with budget 0;
`time_left_ms` absent on the first request of a leg (hand 1) → uses `time_bank_ms` → Stage 1: 138 ms per hand,
`normal`. Every tier case states its `hand_id`, and the expected tier is derived from **both** panic conditions
(Stage 1, reserve 2,400 ms, so the bank threshold is 1.25 × 2,400 = 3,000):

| `time_left_ms` | `hand_id` (of 200) | per-hand ms | Tier | Why |
|---|---|---|---|---|
| 2,999 | 200 | 599 | panic | bank condition (2,999 < 3,000), even with ample per-hand time |
| 3,000 | 200 | 600 | normal | boundary: 3,000 is **not** < 3,000, and 600 ≥ 80 |
| 3,000 | 100 | 600 / 101 ≈ 5.9 | panic | per-hand condition (< 25) |
| 6,000 | 101 | 3,600 / 100 = 36 | throttle | 25 ≤ 36 < 80 |
| absent, after a request (hand 199) that carried 2,999 | 200 | 599 | panic | uses the last known 2,999 |

Non-numeric (`"abc"`, NaN) → same as absent; `expired(b)` false before and true after `b` ms (fake
`perf_counter`); Stage 1 and Stage 2 values match §3.6.

**E. Engine runs (timing):** `scripts/arena.py --rivals random starter --stage 2 --seeds 4 --jobs 1` (sequential, so
timing is not distorted by parallel matches; `arena.py` itself says timing is only meaningful with `--jobs 1`) →
0 notices, 0 forfeits, and **bank use ≤ 40%**: the engine's `time used` is summed over both legs, so the check is
`ourTmax ≤ 0.40 × 2 × 75 s = 60 s` in Stage 2. The measured value is recorded in the review log; F01 is expected to
use well under 5% (< 7.5 s). `scripts/build.py --check` passes.

## 7. Acceptance criteria
- [ ] All tests in §6 pass; `pytest` is green.
- [ ] 0 notices and 0 forfeits in every engine run, including the chaos-bot runs.
- [ ] Stage 2 `--jobs 1` run: our `time used` (both legs summed) ≤ 60 s, i.e. ≤ 40% of the bank (§6E).
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
### Round 1: 2026-11-10 (Codex: 8 bugs; all accepted, all fixed in round 2)
| Bug | Severity | Finding (Codex) | Resolution (Claude) |
|---|---|---|---|
| B1 | major | `safe(brain.on_match_end, msg)` dereferences `brain` before `safe()` runs when construction failed. | **fixed:** §3.1 replaces `safe(fn, msg)` with `dispatch(brain, name, msg)`, which skips a `None` brain and does the handler lookup and call inside one `try`. §6B adds a constructor-failure script (requests + `match_end`, exit 0). |
| B2 | major | `discard(req)` updates only `hole_strs`; after a preflop all-in the flop first arrives in the discard request. | **fixed:** confirmed in `engine.py` (`betting_round` returns immediately when a stack is 0; `discard_request` carries `board`, `pot`, stacks). New `HandState.update_from_discard_request` syncs hole3, board, street, pot, stacks and rebuilds `dead` before the policy runs (§3.2, §3.5, edge cases 5–6). §6B adds the preflop-all-in test with replacement hole cards. |
| B3 | major | `make_legal_discard` accepts malformed cards on membership alone (`"2x"`). | **fixed:** §3.4 requires `str` + `is_valid` + membership; fallback is the engine's default over valid cards only (`"Kd"` in the example), tested in §6B. |
| B4 | major | The §6B "every reply parses against its request" assertion is impossible for missing `legal_actions` (`parse_action` raises `KeyError`) and for hands with no valid card. | **fixed:** §6B now asserts liveness + reply shape for every script, engine legality only for well-formed requests, and the exact documented fallback reply for each malformed class. |
| B5 | minor | `match.log` includes time used and paths, so line-for-line identity fails. | **fixed:** confirmed (`Match.summary` writes `time used` and the `Logs:` path into `match.log`). §6C2 compares per-hand records and result fields only, excluding timing, paths and labels. |
| B6 | minor | Design falls back to last known / initial bank on missing `time_left_ms`; tests demand panic. | **fixed:** one policy in §3.6 (finite value → use it, ≤ 0 → panic; absent/non-numeric → last known, else full bank), and §6D tests exactly that. Chose "last known" over "panic" because absence is an engine defect and permanent panic would cripple every later decision. |
| B7 | major | `Clock.start(req, leg, hand)` and `expired(budget)` change the contract without declaring it. | **fixed:** `start(req)` keeps its signature (the leg is passed once to `Clock(leg)`; the hand id is read from `req`). `expired(budget_ms)` is a declared change. Both, plus `Brain.on_match_end` and the new `HandState` methods, are listed in §2 for `INTERFACES.md`. |
| B8 | major | Stage 2 timing run omits `--jobs 1`, and there is no bank-use threshold. | **fixed:** §6E runs with `--jobs 1` and enforces `ourTmax ≤ 0.40 × 2 × 75 s = 60 s` (the engine's `time used` is summed over both legs); added to §7. |

### Round 2: 2026-11-11 (Codex: 5 bugs; all accepted, all fixed in round 3)
| Bug | Severity | Finding (Codex) | Resolution (Claude) |
|---|---|---|---|
| B1 | major | Non-list `legal_actions` (e.g. `7`) makes the fallback membership checks raise; `fallback_action` ran in an unprotected exception handler; `make_legal` returned `{"action":"check"}` without `type`. | **fixed:** new never-raising `legal_list(req)` normalises `legal_actions` (list of `str`, else `None`) and is the only membership path in every layer (§3.1, §3.4). `make_legal` itself calls `fallback_action` for a `None`/unknown intent, so the fallback runs inside the protected layer; layer 3 has its own `try` ending in a constant reply. All returns are complete dicts with `"type"`. §6B sends missing/`null`/`7`/string/`[]` through the protocol loop, with and without a raising `act`. |
| B2 | major | `t in HANDLERS` raises `TypeError` for an unhashable `type` (`[]`, `{}`), outside any guard. | **fixed:** non-`str` types are skipped before lookup (§3.1). Also added an outer per-message `try` with a `replied` flag that sends a constant reply if anything escapes before a request's `send`, so no single message can stop the loop. §6B tests both examples followed by a valid request. |
| B3 | major | `update_from_discard_request` leaves `hand.hole` stale when the request replaces the `new_hand` cards. | **fixed:** `hole_strs`, `hole3` and `hole` are all set from the request (§3.2); the state test asserts all three. |
| B4 | minor | `3,000 < 1.25 × 2,400` is false (both are 3,000), and with `hand_id = 200` the tier is normal. | **fixed:** §6D now has a table where every case states `hand_id` and derives the tier from both panic conditions: 2,999 @ 200 → panic (bank), 3,000 @ 200 → normal (boundary), 3,000 @ 100 → panic (per-hand), 6,000 @ 101 → throttle, absent after 2,999 → panic. |
| B5 | minor | "Rebuild `dead` if the board grew" misses a same-length board replacement. | **fixed:** `dead` is rebuilt unconditionally at the end of every update (§3.5; it costs microseconds), and `update_from_request` always replaces `board`. §6B adds a same-length replacement test. |

### Round 3: 2026-11-11 (Codex: no bugs)
Approved. Implementation follows this revision exactly; any design change goes back through review.
