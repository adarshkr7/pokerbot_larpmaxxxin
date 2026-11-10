# W3: Discard

**Plans + implements:** Claude · **Reviews plans:** Codex · **Branch:** `ws/W3` · **Day:** Wed (D1) → Fri (D2, D3)

## Goal
Wed: an equity-max discard against **realistic opponents** (dealt 3 cards, discarding by `opp_discard_policy`),
using common random numbers, within the clock budget. Fri: the range-aware version and the inverse-discard
posterior used on the turn and river.

## Owns
`bot/discard.py`, `tests/test_discard.py`, `# --- W3 ---` in `bot/params.py`.

## Interfaces
`choose_discard`, `opp_discard_policy`, `posterior_after_discard` per `agents/INTERFACES.md`. Uses `equity.py`,
`evaluator.py` (W2), `Clock` (W1), `OppModel.range_weights` (W6 stub).

## Strategy items
03/D1, D5 (all-in), then D2, D3 (softmax filter with β scaled by τ, floor ε, 1e-9 normalisation), D4 later.
**Never pick our discard by looking at a sampled future board;** the opponent policy may use only its own
cards and public info.

## Check two ways
1. The worked examples in `strategies/03_discard.md` (A♠K♠Q♦ on J♦T♣2♠ → toss A; on 9♠4♠2♦ → toss Q;
   A♦Q♦9♣ on A♠9♥4♣ → toss Q) as unit tests.
2. A simulation: on 1,000 random flops, equity lost vs the best keep (from 5,000-sample offline estimates)
   is < 1% on average within the live budget; toss-lowest loses ~6%.

## Done when
- [ ] checks pass; `promote.py --dry-run` beats the champion head-to-head (z ≥ 2)
- [ ] the discard stays within its `budget_ms` on Stage 2 timing runs
