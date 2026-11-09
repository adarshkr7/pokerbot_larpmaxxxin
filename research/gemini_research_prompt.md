# Research prompt: strategy and techniques for a Discard Hold'em poker bot

> Paste everything below the line into Gemini. It is self-contained.

---

You are a research assistant helping a two-person team build a poker bot for a programming
competition. The deadline is **15 November 2026** (about 6 days away), so practicality matters
more than theoretical elegance. Research thoroughly using the web, then write a structured
report. Cite a source (URL) for every non-obvious factual claim, and clearly label anything that
is your own reasoning rather than sourced.

## 1. The game: Discard Hold'em

Heads-up (2-player) no-limit Texas Hold'em with exactly two changes:

1. **Three hole cards.** Each player is dealt 3 hole cards instead of 2.
2. **Simultaneous exposed discard.** After the flop betting round (if nobody folded), each player
   secretly chooses one hole card to discard. Both choices are made at the same time, then **both
   discarded cards are revealed to both players** and removed from play. This happens even if
   players are all-in. The rest of the hand is played with 2 hole cards.

Other rules:
- Showdown: best 5 cards from the 2 remaining hole cards plus 5 board cards (standard rankings, A-2-3-4-5 is the lowest straight).
- Blinds 1/2. **Both players start every hand with 200 chips (100 big blinds), and stacks reset every hand.**
  Hands are independent; there is no tournament or ICM dynamic.
- No-limit with a **cap of 4 bets or raises per street**. Preflop, the big blind counts as the first, so 3 voluntary
  raises are possible. The minimum raise equals the previous raise size, never less than 2 chips.
- Button posts the small blind and acts first preflop, last postflop. Seats alternate every hand.
- The board (flop, turn, river) is fixed before any action and does not depend on discards.

## 2. Tournament and scoring

- **Duplicate format.** A match is 2 legs. Leg 2 replays every deal with hole cards and seats
  swapped between the bots. A fresh bot process plays each leg, with no memory carried across legs.
  Results are summed over both legs, so card luck largely cancels.
- **Match result:** whoever has more net chips over the match wins (1 point), a draw is 0.5, a loss 0.
  The tie-break is capped chips per hand (each match's net is clipped to ±400 in Stage 1 and ±1000 in Stage 2).
  So the objective is primarily **winning many individual matches**, secondarily average chip margin.
- **Stage 1:** a Swiss of about 6 rounds, each match 2×200 hands. **Stage 2 (finals):** the top 32 play a full round
  robin, each match 2×500 hands.
- Opponents are other teams' bots, mostly students (likely a wide skill spread: random bots,
  check/call bots, simple equity-threshold bots, some aggressive or all-in bots, and a few strong ones).
  Within a leg a bot may track opponent statistics across 200–500 hands.

## 3. Technical constraints (very important)

- **Python 3.11, standard library + numpy + scipy only.** No other packages, no compiled extensions.
- 1 vCPU, 1 GB RAM, read-only filesystem, no network, no subprocesses.
- Submission: a single `bot.py`, or a zip of **at most 5 MB** (so precomputed tables must fit in about 5 MB).
- **Time bank: 30 s per 200-hand leg (Stage 1), 75 s per 500-hand leg (Stage 2)**, about 150 ms per hand
  for *all* decisions in that hand, on a likely slow vCPU. Any single reply must take under 5 s. 5 s of uncharged start-up per leg.
- A crash or timeout forfeits the whole match, so robustness beats sophistication.
- **Conduct rule:** copying code from public pokerbot repositories is prohibited; published
  *algorithms and ideas* are allowed. Describe techniques. Do not hand us code to copy from other bots.

## 4. Research questions

Answer each, with concrete, actionable recommendations for *this* game under *these* constraints.

### A. Closest known games and existing strategy knowledge
1. Which known poker variants are closest? (e.g. **Pineapple / Crazy Pineapple / Lazy Pineapple**,
   Irish poker, other 3-hole-card or discard variants). What does their strategy literature say about
   **preflop 3-card hand values**, which starting hands are strong, and **which card to discard**
   given a flop?
2. Has any university pokerbot competition used a 3-hole-card or discard variant
   (e.g. **MIT Pokerbots**, CMU, Stanford, Princeton, or similar events)? What variants did they use
   in recent years, and what did winning teams' published write-ups or post-mortems say worked?
   Summarise the general lessons from MIT Pokerbots winners across years.

### B. Game-theoretic techniques that fit the budget
3. Is **CFR / MCCFR / CFR+ / Discounted CFR** with card abstraction (equity buckets, E[HS²],
   potential-aware/EMD bucketing) and action abstraction realistic to train offline in a few days
   on a laptop for this variant, and compress into ≤ 5 MB of numpy tables? How do past
   student teams size abstractions? What does it buy versus a well-tuned heuristic bot?
4. How should the **simultaneous exposed discard** be modelled game-theoretically (it is a
   simultaneous-move node with public outcomes)? Is a mixed discard strategy ever useful, or is
   "keep the max-equity pair" near-optimal? How much information do discards leak?
5. Cheap real-time techniques: Monte Carlo equity vs. a range, range-weighted equity, pot-odds and
   MDF (minimum defence frequency) based play, simple **subgame / endgame** solving on the river
   within about 50 ms in Python.

### C. Exploitation of a weak, heterogeneous field
6. In bot competitions against mostly weak student bots, what wins more: near-equilibrium play or
   **exploitative** play? Which opponent statistics (VPIP, PFR, aggression factor, fold-to-bet,
   showdown frequencies, bet-size tells) are most useful to track over 200–500 hands, and how
   should a bot adapt (e.g. Bayesian updates, regularised frequency estimates, switching between
   preset strategies)?
7. Specific counter-strategies for common naive bots: always-call, random, always-all-in,
   tight-passive equity-threshold bots. What are the "free money" exploits?
8. How does **duplicate scoring** plus **match-win (not chip-total) scoring** change optimal risk
   taking? E.g. should a bot that is ahead late in a leg reduce variance? (It cannot see the other
   leg's results.)

### D. Engineering under Python constraints
9. Fastest **pure-Python / numpy hand evaluators** for 5–7 cards (lookup-table approaches like
   Cactus Kev, perfect hashing, prime products, bitmask straight/flush detection, vectorised numpy
   evaluation of many runouts at once). Expected throughput in evaluations per second in CPython.
   What precomputed tables fit in ≤ 5 MB?
10. How many Monte Carlo samples are needed for usable equity estimates (error vs. sample count),
    and tricks to cut cost: variance reduction, caching preflop equities, precomputed flop tables,
    isomorphism / suit canonicalisation for 3-card hands (how many strategically distinct 3-card
    starting hands are there?).
11. Time-bank management strategies for a fixed per-leg budget.

### E. Variant-specific math
12. Estimate or find: how much stronger is a 3-card hand than 2-card on average? Probability of
    flopping a pair or better, flush and straight draws with 3 hole cards; how equity distributions
    shift versus standard Hold'em; how preflop hand rankings change (e.g. value of suitedness,
    connectedness, pairs, and "trips in hand").
13. After the discard, each player has a 2-card hand chosen from 3 *conditioned on the flop*. How
    should **post-discard ranges** be built for the opponent (given their exposed discard and their
    betting), and how should our own discard choice account for what it reveals?

## 5. Output format

Produce a report with these sections:

1. **Executive summary:** the 10 most important, actionable recommendations, ranked by
   expected impact per hour of implementation effort.
2. **Findings** for each research question A–E (with citations).
3. **Recommended architecture** for a bot that can be built and tested in about 5 days by two people:
   components, data precomputed offline vs. computed live, per-decision time budget.
4. **Phased plan:** v0 (safe, robust baseline, day 1), v1 (strong heuristic), v2 (opponent
   modelling / exploitation), and optional v3 (abstraction + CFR blueprint), with what each
   should beat.
5. **Testing methodology:** how to measure improvements with statistical confidence given
   duplicate deals (number of hands needed, variance estimates), and what sparring opponents to build.
6. **Pitfalls and risks** specific to this format.
7. **Source list** with URLs.

Be concrete: give numbers, thresholds, formulas and pseudo-code where useful. Prefer ideas that
are proven in practice over speculative ones, and say how confident you are in each recommendation.
