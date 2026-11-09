# W4: Preflop (tiers → offline table)

**Agent:** Codex · **Branch:** `ws/W4` · **Day:** Wed (tiers) → Thu (table)

## Goal
Wed: a heuristic tier preflop (04/P1). Thu: an **offline-computed** equity table for all 1,755 canonical
3-card hands (vs random, plus narrower ranges if time allows), shipped as `bot/data/preflop.json`, driving
position-aware open / 3-bet / call / fold. This is our "solve offline, ship a table, live fallback" step.

## Owns
`bot/preflop.py`, `bot/data/preflop.json`, `scripts/offline/build_preflop_table.py`, `tests/test_preflop.py`,
`# --- W4 ---` in `bot/params.py`.

## Interfaces
`strength`, `decide` per `agents/INTERFACES.md`. Offline script uses `bot/evaluator.py` and `bot/equity.py`
(W2) and `discard.opp_discard_policy` (W3) for both players' flop discards. **Record these assumptions in
the JSON header.**

## Strategy items
04/P1 (synergy, danglers, monotone and rolled-up-trips traps), P2, P3, P4 (shove-call gate: test 49.5% vs
56.5% in the arena), 02/E4.

## Check two ways
1. Table sanity: canonicalisation covers 22,100 → 1,755; known orderings hold (AAK suited > AAx rainbow >
   KQJ two-suited > 722 rainbow); MC error per entry is reported (≥ 20k samples each).
2. Arena: tier/table preflop vs v0 preflop, with everything else fixed, head-to-head via `promote.py --dry-run`.

## Done when
- [ ] the table is ≤ 100 KB, loads during start-up (time measured), and has a live fallback if the file is missing
- [ ] it beats the champion head-to-head
