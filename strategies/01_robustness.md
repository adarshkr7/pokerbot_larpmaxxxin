# 01: Robustness (never forfeit, never get corrected)

All items are **P0**, built on day 1 before any strategy.

## R1. Decision firewall
Wrap every `choose_action` / `choose_discard` in `try/except Exception`. On error:
- **action:** `check` if legal; else `fold` (what F01 implements). A "call small bets blind" fallback was
  considered and dropped: a fallback must not depend on state that may be the thing that is broken;
- **discard:** keep the pair with the highest static flop score `S` (03/D3) if that is safely computable;
  otherwise discard the lowest-ranked card, ties broken s, h, d, c (the engine's default rule). F01 implements
  only the second; the static-score fallback arrives with the discard policy (03/D1);
- log the traceback to stderr (trimmed; stderr is capped at 64 KB per leg).

Cost: 1 h. Status: done in F01 (`bot/bot.py` three-layer firewall; fallback = check, else fold).

## R2. Legality layer
Every outgoing action passes through one `make_legal(action, req)` function:
- the action must be in `legal_actions`; if not, take the first legal one of raise→call→check→fold after the
  requested action (a refused raise becomes a call when facing a bet, else a check; never a fold while `check`
  is legal);
- the raise amount: `int` (never `bool` or `float`; the engine rejects both as malformed), clamped to
  `[min_raise, max_raise]`. `min_raise`/`max_raise` exist only when `raise` is legal, and `min_raise` can equal
  `max_raise` (short all-in);
- if `max_raise - amount` is small (e.g. < 10% of pot), shove instead, to avoid silly leftover stacks;
- the discard card must be in our current 3 hole cards.

**Target: zero `notice` messages in every arena run.** Cost: 1 h. Status: done in F01 (`bot/legal.py`), except the
shove-snap, which is a strategy decision deferred to F09.

## R3. stdout hygiene
Only the protocol loop writes to stdout (`# protocol` marker; `scripts/build.py` enforces this).
All debugging goes to `sys.stderr`. Status: enforced by the build script; since F01, `bot/bot.py` also redirects
`sys.stdout` to stderr, so a stray `print()` can never reach the engine.

## R4. Time guard
- Read `time_left_ms` on every request. The reserve is `max(1.5 s, 8% of the bank)` (2.4 s in Stage 1, 6 s in
  Stage 2; `bot/params.py`). When `time_left_ms < 1.25 × reserve`, or
  `max(0, time_left_ms − reserve) / remaining_hands < 25 ms`, the clock is in the **panic tier**: `budget_ms()` returns 0 and every policy must use its **zero-compute path** (table lookups and
  static evaluation only, no sampling loop).
- Cap any single decision at `MAX_DECISION_MS` = 400 ms regardless of bank (the hard limit is 5 s).
- Monte Carlo loops check the clock every N samples (N ≤ 64) and stop at the per-decision deadline. A loop that
  stops early must still return a usable answer from the samples it has (or the static fallback if it has none).
- The 5 s start-up allowance is counted **from process launch**, not from the first request. Imports, table
  loading and warm-up must finish well inside it (target < 1.5 s on the dev machine).

Cost: 2 h. Status: clock and tiers done in F01 (`bot/timing.py`); the zero-compute fallback strategy and
sample-loop deadlines come with the first heavy computation (F02+).

## R5. Message handling
- Ignore unknown message types and fields; never index a field without `.get` where it can be absent
  (`min_raise`/`max_raise` are only present when raise is legal).
- Exit cleanly on `match_end` and on EOF.
- Handle all-in states: discard requests still arrive when no betting is possible.

Status: done in F01 (`tests/test_protocol.py`, `tests/test_state.py`).

## R5b. Format-specific pitfalls (from Gemini)
- **Discard while all-in:** `my_stack == 0`. Never divide by the stack or pot without guards; the
  discard code must not depend on betting state.
- **Cold start:** warm up numpy (and scipy, if used) during the uncharged 5 s start-up with a dummy
  evaluation, so hand 1 isn't slow.
- **Dead cards:** keep one `dead[52]` mask per hand (our 3 cards, the board, and the opponent's discard once
  known). Samplers must never deal a dead card.
- **Range collapse:** weight normalisation needs a floor (ε) plus 1e-9, otherwise ZeroDivisionError (03/D3).
- **Read-only filesystem:** no `open(..., 'w')` anywhere. A `PermissionError` would be a crash.
- **Min-raise wars:** an opponent min-clicking can use up the 4-raise cap; when we hold the last raise with a
  strong hand, make it all-in (05/B4).

Status: F01 covers the stack-0 discard, the `dead[52]` mask (rebuilt after every update) and no file writes.
The numpy warm-up, the range floor and min-raise wars belong to F02, F10 and F09.

## R6. Fuzz and soak tests
- Before every upload: Stage 2 (2×500 hands) against every sparring bot with 0 notices and 0 forfeits.
- Fuzz **policy outputs** against valid engine requests and require a legal reply every time.
- For **malformed incoming messages** (missing fields, unknown types) require liveness and a well-formed
  reply; legality can only be required when enough valid information is left (without `hole_cards` no legal
  discard is knowable; without `legal_actions` the fallback `check` may be illegal).

Cost: 2 h. Status: F01 has the random policy-output fuzzing (`tests/chaos_bot.py`) and fixed malformed-message
tests; random mutation of incoming messages is still todo; the Stage 2 soak vs sparring bots waits for F03.
