# 02: Hand evaluation, equity and time budget

## E1. Fast 7-card evaluator (P0)
The engine's `best_hand` (21 × `rank5`) gives ~17.5k evals/s, too slow. Our bitmask design
(rank counts + suit masks + straight masks, returning a single comparable int) gives **~288k evals/s**
on this laptop and matched the engine on 20k random showdowns (`research/bench_discard.py`).
- Cards as ints `rank*4 + suit`. Precompute straight masks. Return an int `(category<<20) | kickers`.
- Unit-test it against the engine's `best_hand` (allowed reuse) on random hands.
- Build order (GPT-astra): transparent oracle → direct 7-card evaluator → mask tables → benchmark scalar vs
  numpy batches (64 / 256 / 1,024) → optimise the *whole* sampling pipeline. The metric is **samples per ms**
  including sampling and weighting, not raw evals per second.
- Correctness cases: wheel straights, board-only ties, full-house ordering, flush vs straight priority.

Cost: 2 h. Status: done (`bot/evaluator.py`; memoised by rank counts / flush mask, 1.2M evals/s warm, checked against the engine on all 7,462 five-card classes).

## E2. Faster options if needed (P1)
**Gemini's design (adopt the idea, fix the build):**
- non-flush strength from a **rank-count lookup** (split base-5 index: 7 low ranks + 6 high ranks);
- flush and straight-flush strength from a **13-bit suit mask → `FLUSH_LOOKUP[8192]`**;
- per-suit 3-bit counters detect a flush; fully vectorised over N hands with numpy fancy indexing.

Gemini's claims "~300 KB, 0.25 s build" are wrong. The dense table is 3,180 × 1,548 ≈ 20 MB, and a
naive Python build loops over 4.9M pairs (seconds, which risks the 5 s start-up). Fixes, either of:
- enumerate only the ~49k valid 7-card rank multisets and store them in a hash or sorted-key array; or
- precompute offline and ship as `.npz` (check it stays well under 5 MB), loaded at start-up.

Also measure the claimed ">4.5M evals/s vectorised" before designing around it.

Other options:
- **numpy vectorised evaluation:** evaluate N runouts at once (rank-count matrix N×13, suit masks).
  Expect a 5–20× speed-up for large N. Use it for discard decisions and range equity.
- **Lookup tables** shipped in the zip (≤ 5 MB): e.g. a 5-card rank-multiset → strength table
  (~6k distinct non-flush rank patterns, tiny), with flushes handled separately.

Cost: 3–5 h. Status: todo. Only if profiling shows we need it.

## E3. Monte Carlo equity (P0)
`equity(hero2, board, opp_weights, dead, budget_ms, rng) -> (eq, n_eff)` (the `agents/INTERFACES.md` contract):
`hero2` is exactly two cards, `dead` includes our own discarded card, the computation stops at `budget_ms`, and
`eq` = win + tie/2 over sampled (or enumerated) opponent holdings and remaining board cards.
- Standard error ≈ √(p(1−p)/n): n=400 → ±2.5%, n=1000 → ±1.6%.
- Use the same random runouts for all candidate keeps (common random numbers), so *differences*
  between options are far less noisy than their absolute values.
- Card removal: exclude **all 3 of our dealt cards** (the one we discarded stays dead), the board and the
  opponent's exposed discard. Unseen cards: 46 on the flop before the discard, 45 after it, 44 on the turn,
  43 on the river.
- Weighted samples: watch `N_eff = (Σw)² / Σw²` (GPT-astra). If weights concentrate, add samples or
  resample; 1,000 weighted samples can carry the information of far fewer.
- 95% half-widths (worst case): 256 → ±6.1 points, 1,024 → ±3.1, 4,096 → ±1.5. These are only *sampling* error;
  a wrong range model is biased regardless of sample count.
- **River:** exactly C(43,2) = 903 opponent holdings once their discard is known. Enumerate them all with
  weights **when that fits the decision budget** (≈ 3 ms with the scalar evaluator); otherwise sample holdings in
  proportion to their weights until the deadline. With a zero budget or no completed sample, use the static
  fallback.
- **Turn:** C(44,2) = 946 opponent pairs × 42 river cards ≈ 40k showdowns: exact only with the vectorised
  evaluator (E2). With the scalar evaluator, sample (pair, river) jointly, the pair drawn **in proportion to
  its weight**. Do **not** truncate to the "top-K weighted pairs": with a wide or uniform range the top K are
  arbitrary, and with a skewed one the estimate is biased towards the strong part of their range.
- **Reuse:** the flop "best keep" equity computed for flop betting can seed the discard decision only if the
  opponent's range weights have not changed since (no opponent action in between) and the keep-by-keep
  totals were stored. Otherwise recompute; correctness first.

Cost: 2 h. Status: done (`bot/equity.py`: weighted sampling on flop/turn, exact river when it fits the budget, common-random-number helpers; ~450-630 samples/ms, river enumeration ~1 ms).

## E4. Precomputed tables (P1)
- **Preflop:** equity of all **1755** suit-canonical 3-card hands vs a random 3-card hand (assuming a
  sensible flop discard). Compute offline with ~20k samples each and ship as JSON (~30 KB).
  Following Gemini, also store equity vs narrower ranges (loose ~60%, TAG ~35%, 3-bet ~15%) so we can
  look up "equity vs their likely range" by archetype. (Gemini says 1,833 hands; that's wrong, it's 1,755.)
  Canonicalise as the **minimum over all 24 suit permutations** of the sorted card tuple. (Sorting by rank and
  relabelling suits "in order of first appearance" is **not** canonical when two cards share a rank: A♠A♥K♥ and
  A♥A♠K♥ would get different keys depending on how the tie is ordered.) Test that all 22,100 raw hands map to
  exactly 1,755 keys: 286 × 5 unpaired + 156 × 2 paired + 13 trips. (Simpler alternative from GPT-astra: index
  all 22,100 raw triples directly, e.g. a uint16 class id per triple ≈ 44 KB.)
  **Record the assumptions with each table** (the opponent's range, both players' discard policy), and if possible
  build it under 2 opponent discard policies (toss-lowest, best-made-hand).
- **Flop discard table (optional):** too many (hole, flop) combos to tabulate exactly; compute live
  instead (see [03_discard.md](03_discard.md)).
- **River:** exact enumeration vs a range is cheap (no runouts to sample).

Cost: 3 h compute + 1 h code. Status: `canon3` done (`bot/equity.py`, 1,755 classes verified); the tables are todo.

## E5. Time budget (P0)
- Bank: 30 s / 200 hands = **150 ms per hand**, the same in Stage 2 (75 s / 500). The judge's vCPU is
  probably slower than our laptops.
- **One rule, no contradiction:** the acceptance criterion is the one in `AGENTS.md`: a local `--stage 2` run
  with `--jobs 1` uses **≤ 40% of the bank** (≤ 30 s of 75 s per leg, ≈ 60 ms per hand). The controller below is
  how we get there; `TARGET_USE` and the sample caps are tuned down until the measured figure meets it.
  (GPT-astra's 100–110 ms per hand and the earlier "use 60–70% of the bank" note are **rejected**: they leave
  no margin for a slower judge.) Because the budget is recomputed from `time_left_ms` on every request, a slow
  judge automatically gets fewer samples instead of a forfeit.
- The controller as implemented in F01 (`bot/timing.py`, constants in `bot/params.py`; Gemini's tier numbers
  were replaced by these):
  - reserve = `max(1.5 s, 8% of bank)`;
  - `per_hand = (time_left − reserve) / remaining_hands`;
  - `budget(kind) = per_hand × SHARE[kind] × TARGET_USE`, capped at `MAX_DECISION_MS` = 400 ms, where SHARE is
    preflop 0.02, flop 0.25, discard 0.30, turn 0.23, river 0.20. A street's share is granted per *decision*,
    so a street with several decisions can spend it more than once; that is safe only because most hands end
    early, so check it by measurement, not by arithmetic;
  - **Normal** (per_hand ≥ 80 ms): full budget;
  - **Throttle** (25–80 ms): half budget;
  - **Panic** (per_hand < 25 ms, or time_left < 1.25 × reserve): budget 0, tables and static evaluation only.
- Every sampling loop also has a **hard sample cap** (a fast machine must not burn the bank for no gain) and
  must cope with a budget of 0 (panic → static fallback).
- Spend more where it matters: the discard and big river or all-in decisions get more budget; preflop
  uses tables (≈ 0 ms); small pots get fewer samples.
- Rough capacity with the scalar evaluator (~288k evals/s on this laptop): a discard sample costs ~7
  evaluations (3 opponent keeps on the flop, then 3 of ours and 1 of theirs at showdown), so ~40 samples per ms;
  a 2-card equity sample costs 2 evaluations, so ~140 samples per ms *before* sampling overhead. Measure it.
- Stress-test under an artificial slowdown (e.g. multiply measured time by 3, or run with `--jobs` high).

Status: clock, reserve and tiers done in F01 (`bot/timing.py`, constants in `bot/params.py`); budgets are used from
F02 on. Verify with `scripts/arena.py --jobs 1 --stage 2` (timing is only valid with jobs=1).
