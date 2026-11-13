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
- **aggression frequency** = (bets + raises) / (bets + raises + calls + checks) (bounded, preferred), and the
  classic **aggression factor** = (bets + raises) / calls, computed as `(agg + 1.5·k) / (calls + k)` with k = 15
  so it never divides by zero;
- **all-in frequency**; **showdown hands vs their bet sizes** (from `hand_result`);
- **their discard rule:** at showdown we see their two kept cards and their discard, i.e. the full triple.
  Check whether the discard was their lowest card (toss-lowest detector) and whether the kept pair was the
  max-`S` pair of the triple (03/D3).

**Data source:** update the stats **once per hand from `hand_result.history`** (it holds the complete action
list even when we folded), never incrementally from `action_request.history` as well, or actions get counted
twice. `opp_hole_cards` is `null` unless the hand reached showdown; `opp_discard` is `null` if the hand ended
before the discard.

**Definitions (denominators are opportunities):**
- VPIP: hands where they voluntarily put chips in preflop (a call or raise; the big blind checking its option
  does not count) / hands dealt.
- PFR: hands with a preflop raise by them / hands dealt.
- Fold-to-steal: their big-blind folds **directly facing our first button raise** / times they had to answer
  our first button raise. A fold to a later raise (e.g. to our 4-bet) or postflop does not count.
- 3-bet %: hands where they re-raised our preflop raise / hands where they could (they faced our raise with
  `raise` legal).
- Fold-to-bet (postflop): folds / times they faced our bet or raise.
- Shove %: hands where they raised to `max_raise` preflop / hands where they had a legal preflop raise.
  3-bet % and shove % are **separate counters**: an open shove is not a 3-bet and a small 3-bet is not a shove.

Use Beta-prior shrinkage for the **binomial frequencies only**: `est = (count + N0·prior) / (n + N0)`, with
priors centred on "average player" and the strengths N0 in the table below, so early noise doesn't over-steer.
The aggression factor uses its own pseudo-count formula (above). The bet-size → strength figure is a Pearson
correlation `r` over n showdowns, shrunk as `n·r / (n + 8)`; it is 0 with fewer than two observations or when
either variable has zero variance.

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
| 3-bet % | 0.12 | 10 | > 0.30 → their 3-bets are wide; continue more (04/P2) |
| Shove % (preflop raise to `max_raise`) | 0.12 | 10 | > 0.50 → shove bot. With this prior the estimate first passes 0.50 after **8 shoves in 8 opportunities** ((8 + 1.2)/18 = 0.51), so "detectable in ~8–10 hands", not 5. Until then B1 pot odds vs a widening range already handle it |
| Big blind fold-to-steal | 0.40 | 10 | > 0.62 → open 100% of buttons |
| Postflop fold-to-bet | 0.42 | 12 | > 0.60 fit-or-fold (c-bet everything small); < 0.20 station (no bluffs) |
| Postflop aggression factor (bets+raises)/calls | 1.5 | 15 | < 0.6 passive (their raises = nuts); > 3.5 bluffer |
| Bet-size → showdown strength correlation | 0 | 8 showdowns | a linear-sizing bot turns its bets face-up |
| **Discard rationality τ** (share of showdowns where their kept pair was the max-`S` pair of their triple, 03/D3) | 0.90 | 6 showdowns | scales β in 03/D3 (β = β_max · clamp((τ − 0.55)/0.35, 0, 1)); τ ≤ 0.55 sets β = 0 **for the softmax branch only**. If the toss-lowest detector fires (their discard was their lowest card in ≥ 90% of ≥ 6 showdowns), use 03/D3's toss-lowest likelihood regardless of τ. A random discarder scores ≈ 1/3; a toss-lowest bot scores roughly a half (it matched the equity-max keep on 55.7% of flops in our measurement; its max-`S` rate is not measured yet) |

Cost: 3 h. Status: done (`bot/opponent.py`). As built: shove prior strength N0 = 4 (not 10) for a fast read; VPIP/PFR denominators are hands where they had a preflop decision; every count decays with a 70-hand half-life; no fold-to-bet by size bucket.

## M2. Archetypes and counters (P1)

Thresholds are the ones in the M1 table (one set of numbers; they apply to the *shrunk* estimates):

| Archetype | Detect (after ~30–50 hands) | Counter |
|---|---|---|
| **Calling station** | fold-to-bet < 0.20, aggression factor < 0.6 | No bluffs. Value-bet as in 05/B8b: from E = 0.52, 0.6× pot below E = 0.68, 1–2× pot or a geometric shove above. Call less vs their rare raises. |
| **Random / noise** | inconsistent sizes, calls and folds unrelated to showdown strength | Value-bet everything decent; don't bluff; call by 05/B1 against a random-hand range (their actions carry no information). |
| **Maniac / all-in** | PFR > 0.65 or shove % > 0.50 | Call down / call shoves with pot-odds equity vs their wide range; trap; never bluff. |
| **Nit / tight-passive** | VPIP < 0.35, fold-to-bet > 0.60 | Steal: open all buttons, c-bet small often, fold to their raises unless strong. |
| **Reasonable (MC/equity)** | balanced stats | Stay near the baseline. Exploit bet-size tells (05/B8); semi-bluff more if they fold to aggression. |

Implementation: one parameter set per archetype (bluff frequency, value threshold, call margin,
sizing multiplier), blended by a soft score instead of a hard switch to avoid flip-flopping.

**Bayesian classifier option (Gemini; reportedly used by `jeffelin/CFR_pokerbot`, an MIT 2026 bot):**
- 7 types with priors: Random 30%, Fish 25%, TAG 10%, LAG 10%, GTO 10%, Nit 10%, Maniac 5%.
- Update `log P(type) += log P(action | type, state)` after each of their actions, then normalise.
- Use the posterior as the blend weights above. This needs a hand-written action-likelihood model per type.
  More work than thresholding the stats, so start with the stats (M1) and add this only if time allows (P2).

Cost: 4 h. Status: done as soft ramps on the shrunk stats (station, nit, random, maniac, neutral). "Random" needs irrational discards + no size/strength correlation + 6-15 showdowns; nit tops out near 0.5 from VPIP alone. The Bayesian classifier is not built.

## M3. Adaptive targets (P2)
Idea from the MIT 2026 top-25% team README: bet toward per-hand-category target pot contributions
and **raise or lower the targets depending on whether the opponent folds to our raises**. That's a cheap,
robust adaptation that needs no archetype classification.

Status: not built.

## M4. Safety rails (P1)
- Exploits must be bounded: never deviate further from the baseline than the evidence supports (shrinkage).
- Re-check every ~50 hands; opponents may be adaptive too.
- Against unknown or strong opponents, fall back to the baseline.

Status: done (shrinkage, blended overrides, 70-hand forgetting; a style switch is tracked in ~80-150 hands).
