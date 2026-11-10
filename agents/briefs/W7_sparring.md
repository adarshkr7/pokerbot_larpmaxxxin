# W7: Sparring bots and gauntlet

**Plans + implements:** Claude · **Reviews plans:** Codex · **Branch:** `ws/W7` · **Day:** Wed (first batch) → ongoing

## Goal
Deterministic (seeded) sparring bots covering the expected field, added to `champion/gauntlet.json`, so
promotion measures what matters. The kit's `random_bot` is unseeded; that's noise we must not depend on.

## Owns
`scripts/sparring/*.py`, `tests/test_sparring.py`, and `champion/gauntlet.json` (opponent list only,
coordinator approval).

## Bots (our own code, protocol-compliant, each ~30–80 lines, seeded from `hand_id`)
1. `station.py`: always call or check, never raise; toss lowest.
2. `maniac.py`: raise or shove ~70%; random discard (seeded).
3. `nit_threshold.py`: MC equity vs random (cheap); fold < 0.48, call 0.48–0.68, bet ½ pot above. A
   parameterised variant `nit_threshold_tight.py`.
4. `min_click.py`: always min-raise to the cap.
5. `linear_sizing.py`: bet size ∝ equity.
6. `lag.py`: VPIP ~75%, barrels 65%, tosses high cards with two pair or better.
7. `switcher.py`: station for 100 hands, then maniac.
8. `always_fold.py`: check if possible, else fold.

## Check two ways
1. Each bot: `pytest` protocol test (legal replies; exits on `match_end`).
2. 2 × 200-hand runs vs `starter` with 0 notices, and identical results on rerun with the same seed (determinism).

## Done when
- [ ] all bots pass; the gauntlet updated; the champion re-measured on the new gauntlet (`promote.py --dry-run`)
- [ ] no bot behaviour change, so it merges without a promotion
