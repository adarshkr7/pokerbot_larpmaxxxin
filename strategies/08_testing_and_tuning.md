# 08: Testing and tuning methodology

## T1. Sparring ladder (P0)
Built-in: `random`, `starter` (check/call), `champion` (the frozen champion). The MIT 2026 bots we used at
first were removed from the repo on Fri 13 Nov (written for a different game, played through an adapter, so
results against them were unreliable); we no longer test against third-party bots.
Our own archetype bots (cheap, ~30 lines each, written by us):
- `station.py`: always call, never raise;
- `maniac.py`: raise or shove ~70% of the time;
- `nit.py`: plays the top 20% only, folds to any bet without top pair+;
- `toss_lowest_mc.py`: a reasonable equity bot that tosses the lowest card (a typical "good student" bot).
- From Gemini's gauntlet:
  - `nit_threshold.py`: MC equity vs random; fold < 0.48, call 0.48–0.68, bet ½ pot above (the
    "lecture template" student bot);
  - `linear_sizing.py`: bet size ∝ equity (tests our bet-size-tell tracker);
  - `deceptive_lag.py`: VPIP ~75%, barrels 65%, tosses high cards with two pair or better (tests the discard filter's
    robustness);
  - `min_click.py`: always min-raises up to the cap (tests off-tree sizes and cap handling).

Status: partly done: `tests/shove_bot.py`, `station_bot.py`, `nit_bot.py`, `maniac_bot.py` exist and are used in the arena; they are **not yet in `champion/gauntlet.json`** (the promotion gauntlet is still random + starter). The other bots in this list are not written. No third-party rivals.

## T2. Arena protocol (P0)
`scripts/arena.py`: N seeds × opponents, W-D-L and chips/hand ± SE.
- Quick check: `--hands 100 --seeds 4 --jobs 6`.
- Acceptance run: `--seeds 20` full Stage 1 matches (8,000 hands per opponent).
- Timing check: `--jobs 1 --stage 2` (parallel runs distort timing).

## T3. Comparing versions (P0)
The frozen reference is the **champion** (`champion/bot/`, changed only by `scripts/promote.py`; the earlier
`versions/vN/` idea was replaced by it). `scripts/promote.py --dry-run` plays the gauntlet plus a head-to-head
vs the champion; a real promotion needs committed code on `main`.
- **Duplicate deals mean low variance,** but "≥ 2 SE over 20 seeds" is not proof (two-sided p ≈ 0.06 at n = 20,
  and repeated parameter picking inflates false positives). Screening runs are exploratory. To call a change an
  improvement, take a 95% confidence interval of the paired whole-match differences on **held-out seeds** and
  require its lower bound to be above zero.
- Accept a change only if it doesn't lose to the previous version and doesn't regress against any ladder bot.

**Paired-difference testing (Gemini):** run the candidate and the baseline against the same opponent on the
*same seeds* and compare per deal. Many deals play identically up to the change, so the variance of the
difference is far lower than comparing two independent arena runs. Gemini's sample-size table assumes
σ_dup ≈ 10 bb per deal pair (unverified). **Measure σ from our own arena logs** before deciding how many seeds
are enough.

**Statistics (GPT-astra):**
- **Our bot adapts within a leg**, so hands (and deal pairs) inside a match aren't independent. The unit is the
  **whole match**: for seed s, `D_s` = candidate chips/hand − baseline chips/hand against the same opponent.
  Bootstrap the `D_s`. Matches needed for ~80% power at two-sided α = 0.05: `n ≈ 7.85·σ_D²/δ²`, with `σ_D`
  measured across matches.
- **Keep both versions' logs.** `scripts/arena.py` names the log directory by opponent and seed only, and the
  engine opens `match.log` for writing, so a second run on the same seeds overwrites the first. Copy
  `logs/arena/` to a per-version directory before running the other version, then pair records by opponent,
  seed, leg and hand id.
- Match-win rate near 50%: ~384 matches for ±5 points.
- Protocol: **20 matches smoke → 100 screening → 400+ finalists**, same seeds for both versions, and a
  **held-out seed range** for the final pick.

**More sparring bots:** always-fold/check, several threshold settings of `nit_threshold`, a loose-aggressive bot,
and a bot that **switches style mid-leg** (tests that our adaptation recovers).

**Correctness test list:**
- wheel straights, board-only ties, full-house ordering;
- all 3 discard choices, discard while all-in;
- raise cap, short all-ins (min_raise = max_raise);
- dead-card exclusion, including our own discard;
- seat-swapped replay.

## T4. Parameter sweeps (P1)
Expose thresholds as constants in one `params.py` (call margins, value thresholds, bluff
frequencies, sizes, preflop tier cut-offs). Sweep one at a time against a fixed opponent mix.
Overnight runs are fine because the arena is cheap.

## T5. Log review (P1)
`logs/arena/<opp>/seed*/match.log` has one line per hand. Grep for our biggest losses and replay
the reasoning (`POKERBOT_DEBUG=1` makes `bot/log.py` dump our equity estimates to stderr; it is off by
default and capped at 48 KB).

Status: todo.
