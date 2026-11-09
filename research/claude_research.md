# Discard Hold'em: research notes (Claude)

Written 9 Nov 2026, 6 days before the deadline. It combines web research, our own measurements (section 2)
and analysis. Items marked **[analysis]** are reasoning, not sourced fact. Compare against the
Gemini report produced from `gemini_research_prompt.md`.

---

## 1. Key context from the web

### 1.1 This is the MIT Pokerbots 2026 variant (adapted)
MIT Pokerbots 2026's official engine describes "this year's poker variant, where you get 3 hole
cards pre-flop, and you choose a card to discard face up after the flop"
([mitpokerbots/engine-2026](https://github.com/mitpokerbots/engine-2026)). A team repo for that
variant reports heads-up no-limit, 1000 hands per match, **400-chip stacks**
([juanorbea/pokerbot](https://github.com/juanorbea/pokerbot)). Our competition differs: 200-chip
stacks (100 BB), simultaneous discard, 4-raise cap, duplicate legs.

- MIT shipped **three reference bots as a ladder**: *toss-smallest*, *good-cards*, *Monte Carlo*.
  Reference-1 "always tosses the card with the lowest rank" and still "beats the skeleton …
  >80% of the time" ([reference-1-2026](https://github.com/mitpokerbots/reference-1-2026)).
  **Takeaway:** even trivial improvements over check/call dominate weak bots. We should build our
  *own* equivalents of these three as sparring partners.
- ⚠️ **Rulebook 10.1:** copying code from public pokerbot repos is prohibited. Read for *ideas
  only*, and write everything ourselves. Reusing `starter_kit/` code is allowed.

### 1.2 Lessons from previous MIT Pokerbots winners and teams
- **2024 (Auction Hold'em, GTO Wizard's sponsor entry):** under "1000 hands in 30 s", they used
  depth-limited search with crude equity-based leaf values, and said in hindsight that **an
  abstraction plus MCCFR blueprint would likely have been better under that time limit**. Precomputed
  tables (a 1755×1326 equity matrix) beat live computation. A per-street **time manager** was
  important. A "draw boost" heuristic "does not seem to improve performance significantly"
  ([gtowizard-ai/mitpoker-2024](https://github.com/gtowizard-ai/mitpoker-2024)).
  - **1755** = the number of suit-isomorphic 3-card starting hands (22,100 raw). This is exactly the size of
    our preflop table.
- **2017 champion:** CFR-trained bot with offline-precomputed hand bucketing and *discard logic*
  ([Fro116/Pokerbots](https://github.com/Fro116/Pokerbots)). A CFR blueprint can win, but the
  author's team had a full IAP month.
- **2011 MIT competition:** "a simpler opponent-modelling agent was able to win" (cited in a
  survey; see the [Huang thesis](https://core.ac.uk/download/19880046.pdf)). The ACPC literature
  is mixed: ε-equilibrium bots beat modelling bots *among strong bots*, while modelling bots
  "won more from the weaker players than any other competitor" (AKI-RealBot, [TUD report](https://ke-tud.github.io/publications/reports/tud-ke-2009-02.pdf)).

### 1.3 Pineapple-poker strategy (closest human game)
Crazy Pineapple (3 hole cards, discard after flop betting, *face-down*) is our game minus the
exposed discard. The human literature is thin and qualitative: wait for the flop before
committing to two cards; hands are stronger on average, so value thresholds go up; three suited
cards are worse than they look because they kill one of your own flush outs
([DeucesCracked](https://www.deucescracked.com/learn/pineapple),
[PokerNews/Ankenman](https://www.pokernews.com/news/2007/02/other-games-ankenman-pineapple-3555.htm)).
No usable discard charts exist, so **we have to compute our own** (section 2).

---

## 2. Our own measurements (scratch benchmark, CPython 3.11, this laptop)

| Measurement | Result |
|---|---|
| Engine's `best_hand` (21× `rank5`) | **17.5k** 7-card evals/s, far too slow for Monte Carlo |
| Hand-written bitmask `eval7` (pure Python, verified vs engine on 20k showdowns) | **288k** evals/s (16× faster) |
| Flop pair-or-better (incl. board pairs), 2 vs **3** hole cards | 49.1% vs **65.5%** |
| Flop 4+ to a flush, 2 vs **3** hole cards | 4.5% vs **11.4%** |
| "Toss lowest rank" picks the max-equity discard | only **55.7%** of flops |
| Equity lost per hand by "toss lowest" | **≈5.5%** (slightly inflated by MC noise) |
| Equity spread best-vs-worst discard | median **22.5%**, p90 44.5%; >15% on **72%** of flops |

Discard study setup: 1,500 random flops, 300 MC samples per keep-pair, opponent modelled as random 2 cards.

> **Update (after GPT-astra's review):** a random-2-card opponent is unrealistic, because opponents also keep 2 of 3.
> Re-run with common random numbers and an opponent dealt 3 cards who keeps its best made pair on the flop:
> toss-lowest is optimal on **56.6%** of flops and loses **6.10%** equity (vs 59.5% / 5.15% with random-2 under
> the same method). The conclusion is unchanged and stronger. See `strategies/gpt_astra_report.md`.

**What the numbers mean [analysis]:**
- **The discard is a big decision.** Losing about 5.5% equity in every contested pot is huge. A correct
  equity-max discard is the cheapest large edge available, and many student bots will toss the lowest
  card or toss at random.
- **Hands connect much more often.** Showdown hand strength is noticeably higher than in Hold'em, so
  one pair is weaker and value/calling thresholds must be recalibrated. Hold'em intuition misleads.
- **Budget:** about 288k evals/s locally, so assume about 120k/s on the judge's vCPU. One MC sample = 2 evals,
  so ~60k samples/s. At ~150 ms/hand and ~3–5 decisions, and using ≤40% of the bank, that leaves
  **~10–15 ms per decision, which is ~600–900 samples** (equity SE ≈ 1.7–2%). This is enough for decisions; it is
  *not* enough for naive per-pair discard MC (3 pairs × 300 = 900 samples) plus range weighting.
  We need a faster evaluator (numpy-vectorised over many runouts, or precomputed 5/6-card
  lookup tables) and/or exact turn/river enumeration with caching.

---

## 3. Strategy analysis for this format [analysis]

### 3.1 What the field will look like and what beats it
Most entrants will be: starter check/call bots, random bots, rank-threshold bots, all-in maniacs,
and a few MC-equity bots. Free-money exploits:

| Opponent type | Exploit |
|---|---|
| Calling station (check/call) | Never bluff. Value-bet *thin* and *big* (pot-sized or larger) whenever ahead of their calling range (≈ any two cards). |
| Random bot | It folds about 20% to any bet and calls wide. Bet strong hands big, and bet small often with medium hands. |
| All-in / hyper-aggressive | Call off with equity > pot-odds threshold (vs an all-in, ~50% vs their *range*, which is wide). Never fold good hands to "pressure". Don't bluff. |
| Tight/weak-passive (folds too much) | Steal blinds, c-bet small, and fold to their rare raises unless strong. |
| MC-equity bots | Mostly honest bet sizes, so read their size as strength. Value-bet a bit thinner than them. |

Within a 200–500-hand leg we see enough hands to classify these types in about 30–60 hands.

### 3.2 Duplicate format and match-win scoring
- **Duplicate deals cancel card luck.** The score difference is purely *decision quality on identical
  cards*. A small consistent edge (e.g. a better discard) converts into match wins very reliably.
- **Win/loss per match.** Against weaker opponents, lowering variance raises match-win probability;
  against stronger ones, more variance helps. We can't see the other leg, so the effect is second-order.
  **Don't build anything for it before v2.**
- **Forfeit costs −C.** That is worse than any realistic chip loss, so robustness comes first, always.

### 3.3 The discard (biggest edge per hour of effort)
1. **v0:** choose the keep-pair that maximises equity vs a random opponent hand over turn and river.
   Exact enumeration of turn+river is C(45,2)=990 runouts × opponent samples, so use MC or a cached exact table.
2. **v1:** maximise equity vs the opponent's *range* given their preflop/flop betting (weighted
   sampling of their 3-card holdings → their likely keep).
3. **Use their exposed discard:**
   - It is removed from the deck, so remove it from the opponent's possible holdings.
   - It also tells us they valued their kept pair above this card on this flop. A high card tossed
     suggests they kept a pair, set or draw; a low card tossed carries little information.
   - Filter the sampled opponent holdings to those whose *(MC-max-equity or simple-rule) discard*
     would match the observed card. This is a cheap Bayesian update.
4. **Our own leak:** a strong opponent can read our discard too. Ignore this for now; at most add slight
   randomisation between near-equal keeps (within ~1–2% equity).

### 3.4 Betting
- **Preflop:** precompute equity of all **1755** canonical 3-card hands (vs a random 3-card hand, both
  making a sensible flop discard) offline and ship it as a small JSON/numpy table. Map it to
  open/3-bet/call/fold thresholds by position. 3-card hands run closer in equity than 2-card hands,
  so play wider than Hold'em.
- **Postflop:** compute equity vs the opponent's estimated range (sampled) and play by pot odds:
  - call if equity > to_call / (pot + to_call), with a margin for reverse implied odds;
  - value-bet when equity vs their *calling* range is > ~55–60%;
  - sizes from a small menu: ⅓, ⅔, 1× pot, all-in, clamped to [min_raise, max_raise].
- **Raise cap and stack depth:** with 100 BB and 4 raises, many pots go all-in by the turn, so equity
  realisation is high and simple equity-based play is closer to correct than in deep-stack poker.
- **Mixing:** randomise a little (e.g. bluff ~⅓ as often as value-bet on the river vs
  non-stations) so that bet-size-reading bots can't exploit us.

### 3.5 Is CFR worth it in 6 days?
Probably not as the core. A Python MCCFR blueprint with card abstraction (equity buckets ×
discard) and action abstraction would take most of the remaining time to build and train, would be
hard to debug, and its edge over a sound equity bot **plus exploitation** is unclear against a
weak field. The 2024 GTO Wizard note shows that even experts with a 100 MB limit leaned on heuristics.
**Possible later:** a small CFR for *preflop only* (1755 hands × a few actions) or a river
subgame, if v2 is done early.

### 3.6 Opponent modelling (v2)
- Track per leg, with Beta-prior shrinkage so early hands don't over-steer:
  - VPIP, PFR, 3-bet %;
  - fold-to-bet by street and size bucket;
  - aggression frequency (bets+raises / actions);
  - showdown strength vs bet size (bet-size → equity regression from `hand_result` when cards are shown);
  - all-in frequency.
- Classify into the 5 archetypes in 3.1 and switch parameter sets: bluff frequency, value-bet
  threshold, call-down threshold. Start at neutral defaults; adapt after about 30 hands.

---

## 4. Engineering notes
- **Evaluator:** our bitmask `eval7` design (rank counts + suit masks + straight masks) is a
  good v0. Faster options: numpy vectorised evaluation of N runouts at once; a precomputed rank
  lookup for 5-card rank-multisets (13^5 combos ~ 371k entries; flush handled separately).
  This must be **our own code**. The engine's evaluator may be reused, but it's slow.
- **Time manager:** budget = `time_left_ms / (expected remaining decisions)`, hard-capped (e.g.
  ≤ 300 ms per decision). Fall back to a cheap heuristic if under budget. Track elapsed time with `time.perf_counter`.
- **Start-up:** 5 s uncharged. Load tables and warm caches at import time.
- **Safety:** wrap every decision in `try/except`, with a fallback of check, else call if `to_call` is small, else fold.
  Clamp raise amounts to [min_raise, max_raise] and check membership in `legal_actions`.

## 5. Testing methodology
- The local engine already plays duplicate legs. Run many seeds in parallel, and report mean chips/hand
  and the match-win rate with standard errors.
- **Sparring ladder (our own code):**
  1. `random_bot` (kit) and the starter check/call bot (kit);
  2. toss-lowest + rank-threshold;
  3. all-in maniac;
  4. MC-equity bot (our v0);
  5. frozen copies of our previous versions.
- Accept a change only if it wins over ≥ ~20 seeds (2×200 hands each) against the previous
  version and doesn't lose to any ladder bot. Re-check timing with `--stage 2`.

## 6. Recommended plan

| Day | Deliverable |
|---|---|
| Nov 10 | **v0:** fast evaluator + MC equity-max discard + equity/pot-odds betting + safety wrapper. **Upload it** (a safe fallback is now on record). Arena script + sparring bots. |
| Nov 11 | Preflop 1755-hand table (offline), position-aware preflop thresholds, bet-size menu. |
| Nov 12 | Range-aware equity; use the opponent's exposed discard (Bayesian filter). |
| Nov 13 | Opponent modelling (stats + archetype switching). |
| Nov 14 | Tuning sweeps on the arena; Stage 2 timing; robustness fuzzing. Upload. |
| Nov 15 | Freeze. Final upload well before 23:59 IST. |

## Sources
- [mitpokerbots/engine-2026](https://github.com/mitpokerbots/engine-2026)
- [mitpokerbots/reference-1-2026](https://github.com/mitpokerbots/reference-1-2026)
- [juanorbea/pokerbot](https://github.com/juanorbea/pokerbot)
- [gtowizard-ai/mitpoker-2024](https://github.com/gtowizard-ai/mitpoker-2024)
- [Fro116/Pokerbots](https://github.com/Fro116/Pokerbots)
- [Huang thesis (opponent modelling)](https://core.ac.uk/download/19880046.pdf)
- [TU Darmstadt report on computer poker / AKI-RealBot](https://ke-tud.github.io/publications/reports/tud-ke-2009-02.pdf)
- [DeucesCracked: Pineapple](https://www.deucescracked.com/learn/pineapple)
- [PokerNews: Ankenman on Crazy Pineapple](https://www.pokernews.com/news/2007/02/other-games-ankenman-pineapple-3555.htm)
