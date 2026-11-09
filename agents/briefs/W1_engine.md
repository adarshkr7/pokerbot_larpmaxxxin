# W1: Engine (protocol, legality, fallbacks, time controller)

**Agent:** Claude Code · **Branch:** `ws/W1` · **Day:** Wed (first; others build on it)

## Goal
A bot skeleton that never forfeits and is never corrected by the engine: 0 notices and 0 forfeits over
Stage 2 runs against every gauntlet opponent, using the time controller.

## Owns
`bot/bot.py`, `bot/brain.py`, `bot/legal.py`, `bot/timing.py`, `bot/state.py`, the stub `bot/opponent.py`
(neutral `OppModel` until W6), `tests/test_legal.py`, `tests/test_timing.py`, `tests/test_protocol.py`,
`# --- W1 ---` in `bot/params.py`.

## Interfaces
Implements `bot.py`, `brain.py`, `legal.py`, `timing.py`, `state.py` from `agents/INTERFACES.md`. `Brain` calls
`preflop.decide`, `betting.decide`, `discard.choose_discard`. Until those merge, call placeholder functions that
reproduce the current champion's behaviour (check/call, toss lowest).

## Strategy items
01/R1–R6, 01/R5b; 02/E5 (clock: reserve, per-hand budget, tiers).

## Check two ways
1. Unit tests of `make_legal` over generated requests: every action ∈ `legal_actions`; raises are ints in
   [min_raise, max_raise]; short all-ins (min = max); raise absent while `raises_left > 0`.
2. Engine runs: `scripts/arena.py --stage 2` vs random/starter with 0 notices; a fuzz test feeding malformed or
   unknown messages to `bot.py` (it still answers legally and exits on `match_end`/EOF).

## Done when
- [ ] all of the above, plus `scripts/promote.py --dry-run` shows 0 notices, 0 forfeits
- [ ] behaviour is identical to v0 (so W3–W5 changes are measurable in isolation)
