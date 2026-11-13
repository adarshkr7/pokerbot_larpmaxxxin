# Strategy catalogue

Collected ideas for our Discard Hold'em bot, written before building starts (**build starts
Wed 11 Nov 2026; deadline Sun 15 Nov 23:59 IST**). Each file is one area. Every idea has a
priority, a cost estimate and a concrete spec, so it can be turned into code directly.

Sources: `research/claude_research.md` (web research + our measurements), rival teams'
READMEs (ideas only, never code; Rulebook 10.1), our own analysis, and Gemini's report
([gemini_report.md](gemini_report.md), a digest with verification notes; its ideas are merged into the files below).

**Gemini errors to remember:**
- there are **1,755** canonical 3-card hands, not 1,833;
- the river bluff share is **B/(P+2B)**, not B/(P+3B);
- its evaluator table needs **~20 MB** and a slow build, not 300 KB / 0.25 s.

Several of its precise figures (LP timings, evals/s, σ, bb/100 impacts) are unverified.

## Suggested split between the two of us (from Gemini's roadmap)
- **Dev A (engine):** protocol and legality (01), evaluator and equity (02), time controller, arena and
  sparring bots (08), river solver if ever (07).
- **Dev B (strategy):** preflop table and tiers (04), discard and inverse-discard filter (03), betting
  rules (05), opponent stats and archetypes (06).

## Priorities

- **P0:** must have before the first upload. Wins against most weak bots and never forfeits.
- **P1:** strong edge for moderate effort. Target: by Fri 13 Nov.
- **P2:** nice to have if time allows; only if P0/P1 are stable.
- **P3:** only after everything else, or never.

## Index

| # | File | Area | Key ideas (priority) |
|---|---|---|---|
| 00 | [00_format_and_scoring.md](00_format_and_scoring.md) | What the scoring rewards | Duplicate cancels luck; forfeit = −C; win the match, not chips (P0 awareness) |
| 01 | [01_robustness.md](01_robustness.md) | Never forfeit | try/except fallbacks, legal clamping, stdout hygiene, time guard (P0) |
| 02 | [02_evaluation_and_equity.md](02_evaluation_and_equity.md) | Engine | Fast evaluator, MC equity, preflop/flop tables, time budget (P0/P1) |
| 03 | [03_discard.md](03_discard.md) | The discard | Equity-max keep (P0), vs opponent range (P1), reading their discard (P1) |
| 04 | [04_preflop.md](04_preflop.md) | Preflop | 1755-hand equity table, position-aware tiers, sizing (P0/P1) |
| 05 | [05_postflop_betting.md](05_postflop_betting.md) | Flop/turn/river | Pot odds + equity vs range, value/bluff thresholds, size menu, raise cap (P0/P1) |
| 06 | [06_opponent_modelling.md](06_opponent_modelling.md) | Exploitation | Stats with priors, 5 archetypes, per-archetype counter-strategies (P1/P2) |
| 07 | [07_game_theory.md](07_game_theory.md) | GTO options | Mixing, balance, small CFR (preflop/river) (P2/P3) |
| 08 | [08_testing_and_tuning.md](08_testing_and_tuning.md) | Process | Arena, sparring ladder, significance, tuning sweeps (P0/P1) |
| 09 | [09_rival_lessons.md](09_rival_lessons.md) | What MIT 2026 teams did | Ideas from their READMEs only (no code, and their bots are not in this repo), and what does NOT transfer to our rules |
| — | [gemini_report.md](gemini_report.md) | Gemini research digest | Top-10 list with our verdicts, verified/unverified claims, formulas, thresholds |
| — | [gpt_astra_report.md](gpt_astra_report.md) | GPT-astra research digest | Its key correction: realistic opponent discard simulation; stats and testing rigour; all its maths verified |

## Where all three research sources agree (highest-confidence plan)
1. **Robustness and legality first.** One legality boundary, fallbacks, time controller.
2. **Discard by simulation:** all 3 keeps, common random samples, *opponents dealt 3 cards who discard
   too*. It's the largest cheap edge (toss-lowest loses ~6% equity per contested flop vs realistic opponents).
3. **Precomputed 1,755-hand preflop table** (both Gemini and GPT-astra confirm the number via the formula once corrected).
4. **Pot odds vs a betting-conditioned range;** read the opponent's exposed discard with a *softened* model.
5. **Conservative, regularised opponent stats** plus simple exploits (stations, over-folders, shovers).
6. **CFR / river solver optional,** only after the above is measured and stable.

**Open disagreements to settle in the arena:** the shove-calling gate (pot-odds EV-max, 49.5%, vs ~56.5%); the
stats prior strength (12 vs 20). **Settled:** the time target is ≤ 40% of the bank measured locally (02/E5).

## Build timeline (revised Fri 13 Nov: only F01, the skeleton, is built)

| Day | Goal | Strategy items |
|---|---|---|
| **Fri 13** | Engine + first real bot | 02 E1, E3 (evaluator, equity), 03 D1 + D5 (discard), 04 P1 + P3 (tiers, sizing), 05 B1–B4 |
| **Sat 14** | Ranges + exploitation, **upload** | 03 D3 (read their discard), 05 B5–B7, 06 M1–M2 + M4, 07 G2, 08 T1 sparring bots; Stage 2 timing |
| **Sun 15** | Tune, then freeze | Parameter sweeps (08/T4), soak runs; final upload by evening (not 23:59) |

Dropped for lack of time unless everything above is stable: 02 E2 (numpy evaluator), 02 E4 / 04 P2 (1,755-hand
table; P1 tiers stand in), 03 D4, 05 B8–B9, 06 M3, 07 G3–G5.

## Status tracking

Mark each idea's `Status:` line in its file as `todo`, `wip`, `done (vX)` or `rejected (why)`
as we go, so this folder stays the single source of truth for strategy decisions.
