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

Cost: 2 h (prototype exists). Status: prototype in research/.

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
`equity(hero_cards, board, opp_range, n)` samples the opponent's holding plus the remaining board and returns win + tie/2.
- Standard error ≈ √(p(1−p)/n): n=400 → ±2.5%, n=1000 → ±1.6%.
- Use the same random runouts for all candidate keeps (common random numbers), so *differences*
  between options are far less noisy than their absolute values.
- Card removal: exclude our cards, the board and both exposed discards.
- Weighted samples: watch `N_eff = (Σw)² / Σw²` (GPT-astra). If weights concentrate, add samples or
  resample; 1,000 weighted samples can carry the information of far fewer.
- 95% half-widths (worst case): 256 → ±6.1 points, 1,024 → ±3.1, 4,096 → ±1.5. These are only *sampling* error;
  a wrong range model is biased regardless of sample count.
- **River:** at most C(43,2) = 903 opponent holdings, so enumerate exactly with weights.
- **Turn decisions:** enumerate all ≤ 44 river cards exactly (no runout sampling) × the top-K weighted
  opponent pairs (K≈25), vectorised. **River:** exact vs the weighted range.
- **Reuse:** the flop rollouts computed for flop betting can be reused for the discard decision when no
  further raise happened.

Cost: 2 h. Status: todo.

## E4. Precomputed tables (P1)
- **Preflop:** equity of all **1755** suit-canonical 3-card hands vs a random 3-card hand (assuming a
  sensible flop discard). Compute offline with ~20k samples each and ship as JSON (~30 KB).
  Following Gemini, also store equity vs narrower ranges (loose ~60%, TAG ~35%, 3-bet ~15%) so we can
  look up "equity vs their likely range" by archetype. (Gemini says 1,833 hands; that's wrong, it's 1,755.)
  Canonicalise by sorting cards and relabelling suits in order of first appearance. Test that all 22,100 raw hands
  map to exactly 1,755 keys. (Simpler alternative from GPT-astra: index all 22,100 raw triples directly, e.g.
  a uint16 class id per triple ≈ 44 KB.)
  **Record the assumptions with each table** (the opponent's range, both players' discard policy), and if possible
  build it under 2 opponent discard policies (toss-lowest, best-made-hand).
- **Flop discard table (optional):** too many (hole, flop) combos to tabulate exactly; compute live
  instead (see [03_discard.md](03_discard.md)).
- **River:** exact enumeration vs a range is cheap (no runouts to sample).

Cost: 3 h compute + 1 h code. Status: todo.

## E5. Time budget (P0)
- Bank: 30 s / 200 hands = **150 ms per hand**, the same in Stage 2 (75 s / 500). The judge's vCPU is
  probably slower than our laptops, so **design for ≤ 40% of the bank locally (≈ 60 ms per hand)**.
  GPT-astra targets 100–110 ms per hand (discard 25–40 ms; flop / turn / river 15–25 / 15–25 / 10–20 ms per
  street). **Resolution:** because the budget is computed live from `time_left_ms` (measured *on the judge*), the
  controller self-calibrates. Aim to use ~60–70% of the bank via the controller, keep the reserve and panic
  tiers, and keep the *fixed* cost (parsing, preflop) tiny.
- Roughly 3–5 decisions per contested hand, plus the discard, so ~10–20 ms per decision → ~600–1200 MC
  samples with E1.
- Spend more where it matters: discard and big river or all-in decisions get more budget; preflop
  uses tables (≈ 0 ms); small pots get fewer samples.
- Dynamic budget: `budget = clamp(time_left_ms / max(remaining_hands, 1) * share, 2 ms, 300 ms)`.
- **Degradation tiers (Gemini):**
  - keep a **2.5 s reserve**;
  - per-hand budget = (time remaining − reserve) / hands remaining × 1.35 (most hands end early and cheaply);
  - **Normal** (≥ 100 ms per hand): full samples;
  - **Throttle** (40–100 ms): halve samples, no expensive solvers;
  - **Panic** (< 40 ms per hand or < 3 s left): tables and static evaluation only.
  - Rough split: preflop ≤ 2 ms, flop 25%, discard 15%, turn 25%, river 35%.
- Stress-test under an artificial slowdown (e.g. multiply measured time by 3, or run with `--jobs` high).

Status: clock, reserve and tiers done in F01 (`bot/timing.py`, constants in `bot/params.py`); budgets are used from
F02 on. Verify with `scripts/arena.py --jobs 1 --stage 2` (timing is only valid with jobs=1).
