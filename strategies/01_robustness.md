# 01: Robustness (never forfeit, never get corrected)

All items are **P0**, built on day 1 before any strategy.

## R1. Decision firewall
Wrap every `choose_action` / `choose_discard` in `try/except Exception`. On error:
- **action:** `check` if legal; else `call` if `to_call` ≤ 10% of our stack and we have no info; else `fold`;
- **discard:** the lowest-equity card if computable, else the lowest rank (the engine's default rule);
- log the traceback to stderr (trimmed; stderr is capped at 64 KB per leg).

Cost: 1 h. Status: todo.

## R2. Legality layer
Every outgoing action passes through one `make_legal(action, req)` function:
- the action must be in `legal_actions`; if not, map raise→call→check→fold in that order;
- the raise amount: `int`, clamped to `[min_raise, max_raise]`;
- if `max_raise - amount` is small (e.g. < 10% of pot), shove instead, to avoid silly leftover stacks;
- the discard card must be in our current 3 hole cards.

**Target: zero `notice` messages in every arena run.** Cost: 1 h. Status: todo.

## R3. stdout hygiene
Only the protocol loop writes to stdout (`# protocol` marker; `scripts/build.py` enforces this).
All debugging goes to `sys.stderr`. Status: enforced by the build script.

## R4. Time guard
- Read `time_left_ms` on every request. If it drops below a reserve (e.g. 3 s, or 20% of the bank),
  switch to a **zero-compute fallback strategy** (table lookups only).
- Cap any single decision at ~300 ms regardless of bank (the hard limit is 5 s).
- Monte Carlo loops check `perf_counter()` every N samples and stop at the per-decision deadline.

Cost: 2 h. Status: todo.

## R5. Message handling
- Ignore unknown message types and fields; never index a field without `.get` where it can be absent
  (`min_raise`/`max_raise` are only present when raise is legal).
- Exit cleanly on `match_end` and on EOF.
- Handle all-in states: discard requests still arrive when no betting is possible.

Status: partly covered by `tests/test_protocol.py`.

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

## R6. Fuzz and soak tests
- Before every upload: Stage 2 (2×500 hands) against every sparring bot with 0 notices and 0 forfeits.
- A random-message fuzzer: mutate engine messages (missing fields, unknown types) and assert that the bot still
  answers legally.

Cost: 2 h. Status: todo.
