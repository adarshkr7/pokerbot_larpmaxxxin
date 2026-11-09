# 06: Opponent modelling and exploitation

Expected field: mostly student bots, i.e. starter check/call bots, random bots, rank-threshold bots,
all-in maniacs, some MC-equity bots, and a few strong ones. Literature: modelling bots "won more
from the weaker players than any other competitor" in the ACPC, while equilibrium bots did better among
strong bots. A *simple* opponent-modelling agent won MIT Pokerbots 2011. Camello (MIT 2026)
layered profiling on top of CFR. See `research/claude_research.md`.

## M1. Statistics with priors (P1)
Track per leg (reset each leg; no cross-leg memory is allowed):
- **VPIP** (voluntarily put chips in preflop), **PFR** (preflop raise), 3-bet %;
- **fold-to-bet** by street (and by our size bucket: small/medium/big);
- **aggression frequency** = (bets + raises) / (bets + raises + calls + checks);
- **all-in frequency**; **showdown hands vs their bet sizes** (from `hand_result`);
- **their discard rule:** at showdown, check whether their discard was their lowest card (toss-lowest
  detector) and whether it was equity-optimal.

Use Beta-prior shrinkage: `est = (count + a) / (n + a + b)`, with priors centred on "average
player" and a strength of ~10–15 hands, so early noise doesn't over-steer.

Rules from GPT-astra:
- **Track opportunities** (denominators), not just counts.
- Prefer separate **bet / raise / call frequencies** over the aggression-factor ratio (unstable when calls are rare).
- **Showdowns are a biased sample** (only hands that reached showdown).
- Prior strength **κ ≈ 20** (Gemini says 10–15; tune).
- Few broad categories: pool sparse street- or size-specific stats towards the overall rate.

Starting priors from Gemini (prior mean / strength in hands; tune them):

| Stat | Prior | N0 | Use |
|---|---|---|---|
| VPIP | 0.65 | 12 | < 0.35 nit, > 0.85 fish |
| PFR | 0.35 | 12 | VPIP − PFR > 0.40 passive fish; PFR > 0.65 maniac |
| 3-bet / shove % | 0.12 | 10 | shove % > 0.50 → shove bot (detectable in 5–8 hands) |
| Big blind fold-to-steal | 0.40 | 10 | > 0.62 → open 100% of buttons |
| Postflop fold-to-bet | 0.42 | 12 | > 0.60 fit-or-fold (c-bet everything small); < 0.20 station (no bluffs) |
| Postflop aggression factor (bets+raises)/calls | 1.5 | 15 | < 0.6 passive (their raises = nuts); > 3.5 bluffer |
| Bet-size → showdown strength correlation | 0 | 8 showdowns | a linear-sizing bot turns its bets face-up |
| **Discard rationality τ** (kept pair beat the tossed card on the flop) | 0.90 | 6 showdowns | scales β in 03/D3; < 0.55 → treat their discard as random |

Cost: 3 h. Status: todo.

## M2. Archetypes and counters (P1)

| Archetype | Detect (after ~30–50 hands) | Counter |
|---|---|---|
| **Calling station** | fold-to-bet < 20%, low aggression | No bluffs. Value-bet thinner and bigger (pot or more). Call less vs their rare raises. |
| **Random / noise** | inconsistent sizes, calls and folds unrelated to showdown strength | Value-bet everything decent; don't bluff; pot-odds calls. |
| **Maniac / all-in** | aggression > 60%, all-in % high | Call down / call shoves with pot-odds equity vs their wide range; trap; never bluff. |
| **Nit / tight-passive** | VPIP < 30%, fold-to-bet > 55% | Steal: open all buttons, c-bet small often, fold to their raises unless strong. |
| **Reasonable (MC/equity)** | balanced stats | Stay near the baseline. Exploit bet-size tells (05/B8); semi-bluff more if they fold to aggression. |

Implementation: one parameter set per archetype (bluff frequency, value threshold, call margin,
sizing multiplier), blended by a soft score instead of a hard switch to avoid flip-flopping.

**Bayesian classifier option (Gemini; reportedly used by `jeffelin/CFR_pokerbot`, an MIT 2026 bot):**
- 7 types with priors: Random 30%, Fish 25%, TAG 10%, LAG 10%, GTO 10%, Nit 10%, Maniac 5%.
- Update `log P(type) += log P(action | type, state)` after each of their actions, then normalise.
- Use the posterior as the blend weights above. This needs a hand-written action-likelihood model per type.
  More work than thresholding the stats, so start with the stats (M1) and add this only if time allows (P2).

Cost: 4 h. Status: todo.

## M3. Adaptive targets (P2)
Idea from the MIT 2026 top-25% team README: bet toward per-hand-category target pot contributions
and **raise or lower the targets depending on whether the opponent folds to our raises**. That's a cheap,
robust adaptation that needs no archetype classification.

Status: todo.

## M4. Safety rails (P1)
- Exploits must be bounded: never deviate further from the baseline than the evidence supports (shrinkage).
- Re-check every ~50 hands; opponents may be adaptive too.
- Against unknown or strong opponents, fall back to the baseline.

Status: todo.
