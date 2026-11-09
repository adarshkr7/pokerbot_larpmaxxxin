# W5: Postflop betting

**Agent:** Codex · **Branch:** `ws/W5` · **Day:** Wed (B1–B3) → Thu (B4–B6) → Fri (B7)

## Goal
Equity- and pot-odds-based flop/turn/river decisions with a small size menu, cap-aware raises and controlled
bluffing. Flop betting happens with **3 hole cards before the discard**: use the equity of our best keep.

## Owns
`bot/betting.py`, `tests/test_betting.py`, `# --- W5 ---` in `bot/params.py`.

## Interfaces
`decide(req, hand_state, opp, clock, rng)` per `agents/INTERFACES.md`. Uses `equity.py` (W2), `discard.py`
(W3: best-keep equity on the flop; posterior on later streets), `OppModel` (W6 stub), `make_legal` (W1).

## Strategy items
05/B1 (call rule with R_pos and margin; continuous pot odds handle off-tree sizes), B2, B3 (amount = raise-to
total), B4 (last raise → all-in when strong), B5, B6 (bluff share B/(P+2B), only vs folders), B7, B8b
(archetype thresholds, once W6 lands). 07/G2 (MDF floor vs aggressive opponents).

## Check two ways
1. Unit tests on constructed requests: call/fold boundaries at exact pot odds; sizes clamped and legal; no
   bluffs when the opponent model says "station".
2. Arena vs station / maniac / nit sparring bots (W7): beats each, and head-to-head vs the champion.

## Done when
- [ ] checks pass; 0 notices; within the per-street budget
- [ ] beats the champion head-to-head (z ≥ 2) without losing gauntlet points
