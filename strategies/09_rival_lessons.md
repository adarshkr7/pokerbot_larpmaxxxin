# 09: Lessons from MIT Pokerbots 2026 teams (ideas only)

MIT 2026 played a related variant ("Toss'em Hold'em"). These notes come from the teams' **READMEs**.
We do not read or copy their code into our bot (Rulebook 10.1). No official 2026 results are public.

## Rule differences: what does NOT transfer

| MIT 2026 | Ours |
|---|---|
| 2-card flop | 3-card flop |
| No betting before the discard | Full flop betting round before the discard |
| Sequential discard (BB first, SB sees it) | Simultaneous discard |
| **Discards become BOARD cards (usable by both)** | **Discards are dead** |
| 400-chip stacks, 1000 hands, 1 leg | 200-chip stacks, duplicate 2 legs |

Consequence: any MIT discard insight about "not giving the opponent a good board card" is
irrelevant for us. Our discard is purely about our own hand, plus the information we leak.

## Lessons

1. **MIT reference ladder** (official): ref1 = toss-lowest with default betting, which beats the skeleton
   >80% of the time; ref2 = the same toss rule plus raising with high hole cards, which never lost to the skeleton in 100 games;
   ref3 = an MC discard, which did *slightly worse* than toss-lowest. That's most likely because in MIT a tossed high card
   helps the opponent's board. **For us, MC/equity discard should be strictly better** (our
   measurement: toss-lowest loses ~5.5% equity per contested flop).
   → Even trivial preflop selectivity plus a sane discard crushes default bots. Build v0 fast.
2. **Camello (fabianruiz3), iteration story:**
   - Week 1 bots "folded too much" and ignored discard information.
   - Then: proper 3-card preflop evaluation, pot odds/EV, dynamic sizing by street.
   - 3.x: MC strength estimates enumerating opponent holdings *accounting for the discard*, plus
     profiling (aggression factor, call frequency, fold-to-c-bet) adjusting thresholds; an
     opponent classifier (tight/loose/aggressive) that gates sizing and bluff frequency.
   - Final: CFR blueprint (buckets: preflop strength, flop texture, discard value) with an MC
     fallback for rare spots, with profiling layered on top.
   → Matches our plan: equity engine → discard-aware ranges → profiling. CFR came last.
3. **jlam901 team (top 25%), final bot:**
   - Preflop: simulated win-rate **charts split by suitedness** (offsuit / two suited / three suited) →
     betting tier with a raise target and a *call cap*.
   - Discard: keep cards forming a flush draw, open-ended straight draw or pair; toss the weakest remaining card.
   - Postflop: classify the made-hand category, then bet toward a **per-category target contribution**,
     and **adapt the targets based on whether the opponent folds to our raises**.
   → "Call cap" and "target contribution" are clean, robust ideas (see 06/M3). Top 25% with
     heuristics only shows that robust heuristics are competitive.
4. **rebeccax06 (MCCFR attempt):** action abstraction FOLD / CHECK-CALL / BET ⅓ / ⅔ / POT /
   ALL-IN; buckets by hand category plus board texture. A Python MCCFR trained in minutes is easily
   too coarse (category-only buckets). → It confirms that a quick CFR isn't a shortcut to strength.
5. **Aggressive all-in bots exist** (Charlarthebar's `all_in_bot*`). → Our pot-odds calling rule
   and maniac counter (06/M2) must be solid from v0.
6. **ckwong6599:** a transformer self-play model (JAX). That's out of scope for Python stdlib + numpy and 5 days.
7. **jeffelin/CFR_pokerbot** (found by Gemini; the repo exists, details unverified): reportedly CFR+ with
   150k–500k information sets, hand-category buckets (pairs, two pair, trips, draws) × board textures,
   and a 7-archetype Bayesian opponent classifier that switches from equilibrium play to exploitation.
   A candidate to add to `rivals/` as a sparring partner.
8. **General lessons from past MIT write-ups (via Gemini):**
   - speed and stability beat heavy models in Python;
   - precomputed tables are essential;
   - a tight-aggressive pot-odds baseline beats most of the student field;
   - **off-tree sizes** (min-bets, overbet shoves) break discrete abstractions, so map them through continuous
     pot-odds and MDF logic.

## Sources
- https://github.com/mitpokerbots/reference-1-2026, -2-2026, -3-2026 (READMEs)
- https://github.com/fabianruiz3/pokerbots-2026 (README)
- https://github.com/jlam901/pokerbots-1-2026 (README, main branch)
- https://github.com/rebeccax06/pokerbots_iap_2026 (README_MCCFR.md)
- https://github.com/Charlarthebar/Pokerbot, https://github.com/ckwong6599/pokerbots-2026
