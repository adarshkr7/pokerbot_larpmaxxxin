# 08: Testing and tuning methodology

## T1. Sparring ladder (P0)
Built-in: `random`, `starter` (check/call). Rivals (via adapter, approximate): MIT reference
bots 1–3, `jlam_agent_1_2`, `camello_*`, `charlar_all_in_v2` (maniac), etc. See `rivals/README.md`.
Add our own archetype bots (cheap, ~30 lines each, written by us):
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

Status: todo (archetype bots); rivals ready.

## T2. Arena protocol (P0)
`scripts/arena.py`: N seeds × opponents, W-D-L and chips/hand ± SE.
- Quick check: `--hands 100 --seeds 4 --jobs 6`.
- Acceptance run: `--seeds 20` full Stage 1 matches (8,000 hands per opponent).
- Timing check: `--jobs 1 --stage 2` (parallel runs distort timing).

## T3. Comparing versions (P0)
Freeze every uploaded or promising version as `versions/vN/bot.py` (our own code, allowed to commit).
Then run `arena.py --rivals versions/vN/bot.py` to play head-to-head.
- **Duplicate deals mean low variance.** A difference of ≥ 2 SE over ≥ 20 seeds is real.
- Accept a change only if it doesn't lose to the previous version and doesn't regress against any ladder bot.

**Paired-difference testing (Gemini):** run the candidate and the baseline against the same opponent on the
*same seeds* and compare per deal. Many deals play identically up to the change, so the variance of the
difference is far lower than comparing two independent arena runs. Gemini's sample-size table assumes
σ_dup ≈ 10 bb per deal pair (unverified). **Measure σ from our own arena logs** before deciding how many seeds
are enough.

**Statistics (GPT-astra):**
- Duplicate unit `Y_i = (x_leg1 + x_leg2)/2`; CI = Ȳ ± 1.96·s/√n. Pairs needed for 80% power: n ≈ 7.84·σ²/δ².
- **Our bot adapts within a leg**, so hands aren't independent. Treat **whole matches** as units and bootstrap
  them.
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
the reasoning (add a `DEBUG` env var that dumps our equity estimates to stderr).

Status: todo.
