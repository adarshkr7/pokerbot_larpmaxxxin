# GPT-astra research report: digest and review

A digest of GPT-astra's report (from the same prompt as Gemini's), received 9 Nov 2026. Its
headline: **"Build a range-aware heuristic bot with correct discard simulation, conservative
opponent adaptation, and strict time control. Treat a full CFR blueprint as optional."**
Ideas are merged into files 00–09; tags like **→ 03/D1** show where.

## ✅ Verification (checked by Claude, 9 Nov)
All numeric claims we checked are **correct**:
- 1,755 canonical classes = 13 + 13·12·2 + C(13,3)·5;
- flop matches one of 3 / 2 distinct hole ranks: 46.37% / 32.43%;
- any repeated rank among visible cards, 3 vs 2 hole cards: 65.48% / 49.29% (matches our simulation: 65.5% / 49.1%);
- exactly two / three flop cards of our suit:
  - 2-suited hand: 11.34% / 0.896%;
  - monotone hand: 9.53% / 0.651%.
  Gemini's 12.24% / 10.18% are the "two or more" sums of these, so both reports agree;
- ≤ 903 candidate river holdings (C(43,2));
- shove-call thresholds 49.5% (BB) / 49.75% (SB);
- all 5-card combinations as uint16 = 5.2 MB (too big to ship raw).

Unverified: the "self-reported 2026 winner with a C++ CFR system" (no link in the pasted text).

## 🔑 The key correction it made to *our* plan
> "The largest strategic error to avoid is comparing your chosen pair against uniformly random
> two-card opposition. Opponents also select from three cards after seeing the flop."

Our discard study and plan D1 used a random 2-card opponent. **Re-run** (1,000 flops, 300 common samples, the
opponent dealt 3 cards and keeping its best made hand on the flop):

| Opponent model | "Toss lowest" is optimal | Equity lost by "toss lowest" |
|---|---|---|
| random 2 cards (old) | 59.5% | 5.15% |
| **3 cards, keeps its best pair** | **56.6%** | **6.10%** |

The discard edge is *larger* against realistic opponents. → 03/D1 now samples opponent **triples** and applies an
opponent discard policy.

## Top 10 (ranked by impact per hour), with our mapping

| # | Recommendation | Hours | Confidence | Where |
|---|---|---|---|---|
| 1 | Centralise legality, sizing, time limits, fallbacks | 4–8 | High | 01 |
| 2 | Simulate discards using only flop-time information (never peek at the future board) | 4–8 | High | 03/D1 |
| 3 | Exclude all dead cards, **including our own discard** | 1–2 | High | 01/R5b, 02/E3 |
| 4 | Duplicate-match test harness immediately | 6–10 | High | 08 (`scripts/arena.py` exists) |
| 5 | Common random samples across the 3 discard choices | 4–8 | High | 03/D1 |
| 6 | Pot odds vs a **betting-conditioned** range | 6–12 | High | 05/B1, B7 |
| 7 | Simple exploits: stations, over-folders, shovers | 4–8 | High | 06/M2 |
| 8 | Precomputed 3-card preflop equities *under a stated discard policy* | 6–12 | Med-high | 02/E4 |
| 9 | Exposed-discard range update with a **softened** discard model | 8–16 | Med-high | 03/D3 |
| 10 | River solver or CFR only after measured gains | 12–30+ | Medium | 07 |

## Ideas that are new or different vs Gemini
- **The opponent discard model may only use its own triple and public info,** never our hidden cards
  or the sampled future board → 03/D1.
- **Effective sample size** for weighted samples: `N_eff = (Σw)² / Σw²`. Concentrated weights mean
  far fewer effective samples → 02/E3.
- **Exact triple → index over all 22,100 triples** can be simpler than live canonicalisation → 02/E4.
- **Preflop tables under several opponent discard policies,** with each table's assumptions recorded → 02/E4.
- **Stats:** track opportunities (denominators); use separate bet / raise / call frequencies instead of
  the aggression-factor ratio (unstable when calls are rare); showdowns are a biased sample; prior strength κ ≈ 20;
  avoid sparse categories within 200 hands → 06/M1.
- **Against shovers:** EV-max calling is ~49.5% vs *their* range. "Wait for premiums" is not automatically best.
  This conflicts with Gemini's 56.5% gate; settle it in the arena → 04/P4.
- **Duplicate risk:** a lead in the visible leg may just be good cards that the twin leg gets back. Default to
  chip-EV; add risk adjustment only with a tested model. This **undercuts Gemini's variance modulator** → 00/F6.
- **River:** enumerate the ≤ 903 opponent holdings exactly. A river solver must solve for our whole *range*, not
  just our hand → 05, 07/G5.
- **Time:** target 100–110 ms of the 150 ms per hand. Discard 25–40 ms is the largest slice; flop / turn / river
  15–25 / 15–25 / 10–20 ms per street. We are more conservative (see 02/E5).
- **Evaluator order:** a transparent 5-card oracle → direct 7-card evaluator (rank counts + suit masks) → 8,192-entry
  mask tables → benchmark scalar vs numpy batches of 64/256/1024 → optimise the *whole* sampling pipeline
  (measure samples per ms, not evals per second) → 02/E1–E2.
- **CFR blueprint starting sizes** (if ever): 16 / 32 / 32 / 64 buckets for preflop / flop / turn / river; actions
  check/call, fold, ½ pot, pot, all-in; augment equity with draw / nut / texture / discard features before EMD → 07.
- **Statistics for testing:**
  - n ≈ 7.84·σ²/δ² duplicate pairs for 80% power;
  - for adaptive bots, use whole matches as units and bootstrap them;
  - ~384 matches for ±5 percentage points on match-win rate;
  - protocol: 20 smoke / 100 screen / 400+ finalist matches; keep fresh seeds for the final evaluation → 08.
- **Sparring additions:** always-fold/check, several threshold settings, a bot that **changes behaviour mid-leg**,
  and a loose-aggressive bot → 08.
- **Correctness test list:** wheel straights, board-only ties, full-house ordering, all 3 discard choices,
  all-in discard, raise caps, short all-ins, dead-card exclusion, seat-swapped replay → 08.
- **Pitfalls:**
  - discarding after looking at a simulated future board (too strong a policy);
  - letting a hand keep 3 hole cards at showdown (impossible straights or flushes);
  - forgetting our own discard (inflated outs);
  - uniform opponents (understate flop selection);
  - max-equity discard may give up betting value;
  - raw-equity thresholds vs betting-conditioned ranges;
  - an opponent model that becomes overconfident;
  - a visible-leg lead read as a match lead;
  - 150 ms average leaving no room for slow outliers → 01.

## Its 5-day split (dates shifted: we start Wed 11)
- **v0:** protocol, rules, fallbacks, clocks (A); evaluator oracle and harness (B).
- **v1:** preflop tables and discard simulation (A); pot odds, ranges, sizing (B).
- **v2:** exposed-discard inference (A); smoothed stats and exploits (B).
- **Validation:** profiling and stress tests (A); held-out duplicate tournaments (B).
- **Optional v3** behind a switch. **Freeze** a day early.

## Sources it cites
Asian Poker Tour Crazy Pineapple rules; MIT thesis (2011 winner, opponent modelling); Jeremy Rubin's
2013 account; the 2017 winner's description; Lanctot et al. (MCCFR); Brown & Sandholm (Discounted CFR); Ganzfried &
Sandholm (potential-aware abstraction); Brown, Sandholm & Amos (depth-limited solving); Cactus Kev's evaluator;
PokerHandEvaluator docs. (Links were in the original paste.)
