# Gemini research report: digest and review

A digest of Gemini's report ("Strategic and Engineering Architecture for an Autonomous Discard
Hold'em Agent"), produced from `research/gemini_research_prompt.md` on 9 Nov 2026. The pasted
original had broken math rendering, so this keeps every actionable number in a readable form.
Ideas have been merged into files 00–09; tags like **→ 03/D3** show where.

## ⚠️ Verification notes (checked by Claude, 9 Nov)

| Claim | Verdict |
|---|---|
| "1,833 canonical 3-card hands" | **WRONG: 1,755.** Its own breakdown sums to 1,755 (1,430 unpaired + 312 paired + 13 trips); brute-force check confirms. |
| Split base-5 evaluator "~300 KB RAM, builds in 0.25 s" | **WRONG.** The table is 3,180 × 1,548 = 4.9M int32 ≈ **20 MB RAM**, and the naive build loops 4.9M pairs in Python (seconds, which risks the 5 s start-up). The idea is sound; build only the ~49k valid 7-card rank multisets, or precompute offline and ship it compressed. |
| River bluff fraction = B/(P+3B) (25% for a pot bet) | **WRONG.** Indifference gives bluff share = **B/(P+2B)** (33% for pot, ~29% for ⅔ pot). MDF = P/(P+B) is correct. |
| P(pair or trips dealt) 17.18%, rolled-up trips 0.24%, flop pairs a hole card 46.37% | Correct (recomputed). |
| BB calling a 200 shove needs 49.5% | Correct. |
| `jeffelin/CFR_pokerbot`: MIT 2026 CFR bot with a 7-archetype Bayesian classifier | Repo exists (updated 2026-06-22). Details unverified. A candidate rival. |
| River LP via `scipy.optimize.linprog` "20.62 ms", vectorised evaluator "4.5M evals/s", σ_dup ≈ 10 bb per pair, all bb/100 impact estimates | **Unverified.** Suspiciously precise; measure before relying on them. |
| MIT variant history (2017 discard, 2021 three-board Blotto, 2023 River of Blood, 2024 Auction) | Plausible, partially confirmed (2024 Auction, 2026 Toss'em). Not important. |

## 1. Gemini's top 10 (ranked by impact per hour), with our verdicts

| # | Recommendation | Hours | Our verdict |
|---|---|---|---|
| 1 | Build the fast 7-card evaluator in RAM during the uncharged 5 s start-up | 3–4 | **Adopt the idea, fix the build** (see notes) → 02/E2 |
| 2 | Canonical preflop table (1,755 hands) with equities vs several ranges and position thresholds | 3–4 | **Adopt** → 02/E4, 04/P2 |
| 3 | Rollout discard optimiser: all 3 keeps vs the weighted range, common random numbers | 4–5 | **Adopt** (= our D1/D2) → 03 |
| 4 | Inverse-discard Bayesian range filter | 5–6 | **Adopt with a softmax model** → 03/D3 |
| 5 | Beta-Binomial stats + archetype classifier + exploit gears | 5–6 | **Adopt** → 06 |
| 6 | Exception wrapping + time controller with degradation tiers | 2–3 | **Adopt** → 01, 02/E5 |
| 7 | Pot odds, MDF, street-cap-aware sizing | 4–5 | **Adopt** → 05, 07/G2 |
| 8 | Duplicate match-win variance modulator | 2–3 | P3; we can't see the other leg → 00/F6 |
| 9 | River subgame LP (scipy HiGHS) | 6–8 | P3, benchmark first → 07/G5 |
| 10 | Deceptive / blocker-aware discard tie-breaking (ΔE < 1.2%) | 3–4 | P2 → 03/D4 |

## 2. Variant knowledge
- **Crazy Pineapple** = our game, but with a face-down discard. Lazy Pineapple discards at showdown; Irish
  poker uses 4 cards and discards 2.
- **Preflop value comes from 3-card synergy.** Trash third cards ("danglers", e.g. A♠K♥2♦ rainbow) are worth
  much less than three cards that work together.
- **Premium hands:**
  - high pair + suited broadway kicker (A♠A♥K♠, K♦K♣Q♦);
  - two-suited broadway wraps (A♠K♠Q♦, K♥Q♥J♣);
  - suited connected wraps (T♠9♠8♦, J♥T♥8♣).
- **Trap hands → 04:**
  - **Monotone** (3 of a suit): flush-draw flop 10.18% vs 12.24% with 2 suited (unverified), and it kills
    one of our own outs.
  - **Rolled-up trips** (0.24%): we must discard one, leaving a pair with a single out to a set.
    Never 4-bet shove low or medium trips.
- **Context-dependent discard examples → 03:**
  - A♠K♠Q♦ on J♦T♣2♠: toss the A, keep KQ (open-ended straight draw).
  - A♠K♠Q♦ on 9♠4♠2♦: toss the Q, keep the nut flush draw.
  - A♦Q♦9♣ on A♠9♥4♣: toss the Q, keep two pair.
- **Variant math (some unverified):**
  - pair-or-trips dealt 17.18% (vs 5.88% in Hold'em);
  - after the discard, one pair with a weak kicker is below median;
  - 3-card connectors (e.g. 7-8-9) flop a straight or 8+-out draw ~70% of the time (vs ~28% for 8-9);
  - coordinated middle boards hold made straights about 8× more often than in Hold'em.

## 3. Game theory
- **The CFR state space is large.** The face-up discard creates up to 2,652 public discard pairs, which
  multiplies the turn and river information sets. A full CFR solve isn't feasible in days in Python.
- **Storage is not the obstacle.** 300k information sets × 3 probabilities stored as uint8 ≈ 900 KB,
  ~400–550 KB after `savez_compressed`.
- **Recommendation:** restrict CFR to preflop and flop charts (~25k information sets); use range equity
  plus an LP for the turn and river → 07.
- **Discard theory:**
  - total EV = equity EV + information EV;
  - information EV is 0 when all-in, or against opponents who don't read discards;
  - in both cases pure max-equity keeping is strictly optimal;
  - deception is only worth it within ~1.2% equity → 03/D4.
- **Information leaks from a discard:** card removal; a rationality bound (the kept pair must be worth at least
  any pair that includes the tossed card); and suit-abandonment signals. Example: tossing a K on a K-high flop means
  they kept a set, two pair or a strong draw.
- **Thresholds:**
  - pot odds C/(P+C);
  - equity-realisation factor ~1.08 in position, ~0.92 out of position;
  - call margin +2–5% on non-river streets;
  - MDF = P/(P+B) → 05, 07.

## 4. Exploitation → 06
- **Stats (prior mean, prior strength in hands):**
  - VPIP 0.65 (12), PFR 0.35 (12), 3-bet/shove 0.12 (10);
  - big blind fold-to-steal 0.40 (10), postflop fold-to-bet 0.42 (12), aggression factor 1.5 (15);
  - bet-size → strength correlation (8 showdowns);
  - **discard rationality τ** (0.90, 6 showdowns).
- **Archetypes (prior):** Random 30%, Fish/Station 25%, TAG 10%, LAG 10%, GTO 10%, Nit 10%, Maniac 5%.
  A log-posterior update after each action concentrates the posterior in 15–25 hands.
- **Counters:**
  - **Station:** no bluffs; value-bet when E ≥ 0.52; size 1–2× pot when E ≥ 0.68; 0.6× pot for thin value.
  - **Shove bot:** call with E ≥ ~56.5% (about the top 34%). EV-max would be 49.5%, but the tighter gate cuts
    variance while staying hugely +EV.
  - **Nit / equity-threshold bot:** min-open 100% of buttons; c-bet 25–33% of pot on every flop (it only
    needs 23% folds); fold one pair to their raises.
  - **Random:** value-only; call their raises with E ≥ 55%; raise to the cap with E ≥ 68%.

## 5. Engineering → 01, 02
- **Evaluator:** rank-count lookup (split base-5 index) for non-flush hands, plus a 13-bit suit mask →
  `FLUSH_LOOKUP[8192]`, vectorised over batches with numpy fancy indexing. (Fix the table build; see notes.)
- **Monte Carlo:**
  - SE ≤ 1/(2√N) (N=250 → 3.2%);
  - common random numbers across the 3 keeps (claims ~6× efficiency);
  - **exact turn → river enumeration** (≤ 44 river cards) × the top-K weighted opponent hands, vectorised;
  - a preflop table vs 4 ranges (random / loose / TAG / 3-bet), ~15 KB.
- **Time controller:**
  - reserve 2.5 s;
  - per-hand budget = (time remaining − reserve) / hands remaining × 1.35;
  - tiers: Normal (budget ≥ 100 ms), Throttle (40–100 ms: halve samples, no LP), Panic (< 40 ms or < 3 s
    left: tables only).
  - Split: preflop ≤ 2 ms, flop 25%, discard 15% (reuse the flop rollouts), turn 25%, river 35%.
- **Pitfalls:**
  - discard request while all-in (stack = 0, avoid dividing by zero);
  - warm up numpy/scipy during start-up;
  - an explicit `dead_cards[52]` mask that includes the opponent's discard;
  - range-weight collapse when the opponent's discard looks irrational (softmax floor ε = 0.02, add 1e-9 before normalising);
  - never write files (read-only filesystem);
  - min-click raise wars lock us out of shoving (size the 4th bet to all-in).

## 6. Testing → 08
- **Paired-difference testing:** run the candidate and the baseline on identical seeds and compare per deal.
  Where actions coincide the difference is 0, cutting SE by 2.5–4× (claimed).
- **Sample sizes** if σ_dup ≈ 10 bb per pair (unverified): 2,500 pairs → SE 20 bb/100; 10,000 pairs → SE 10 bb/100.
  **Measure our own σ.**
- **Gauntlet:** CheckCallStation, AlwaysShove, NitThreshold (MC vs random: fold < 0.48, call to 0.68,
  bet ½ pot above), LinearSizingTell (bet ∝ equity), DeceptiveDiscardLAG, MinClickAnnoyance,
  PreviousMilestone.

## 7. Gemini's roadmap (two developers)
- **v0 (day 1):** wrapper, legality, time controller, evaluator, canonical mapper, heuristic discard,
  pot-odds play; must beat random, check/call and all-in bots.
- **v1 (days 2–3):** preflop table, common-random-number flop rollouts shared by flop betting and the discard,
  turn enumeration, MDF sizing.
- **v2 (day 4):** inverse-discard filter, classifier, exploit gears, variance modulator.
- **v3 (day 5):** river LP, flop texture charts, testing under a 3× CPU slowdown, zip audit.
- **Split:** Dev A = engine, evaluator, time, LP; Dev B = tables, discard, range filter, exploits.
