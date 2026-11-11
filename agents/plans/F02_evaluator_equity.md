# F02: Cards, evaluator, equity (scalar)

**Status:** in review (round 5)
**Workstream:** W2 · **Strategy items:** 02/E1, 02/E3, 02/E4 (`canon3` only) · **Owner:** Claude (implements) · **Reviewer:** Codex

## 1. Goal
A pure-Python library that later features (F04 discard, F05/F06 betting) call for hand strength and equity:
`eval7` orders every 5–7-card hand **exactly as the engine's `best_hand` does** at ≥ 250k evals/s, and `equity`
returns a budget-bounded estimate of win + tie/2 against a weighted opponent range: exact enumeration on the river
when the budget allows it, otherwise the plain mean of i.i.d. samples drawn in proportion to the weights. The choice
between the two never looks at sampled values, so there is **no selection bias**. The only remaining bias comes from
stopping at a wall-clock deadline when evaluation cost correlates with the outcome. It is quantified and bounded
(§3.3 *Bias*, §6B9). Results agree with exact enumeration within 4 standard errors. **No bot behaviour change.**

## 2. Scope
**In:** `bot/cards.py` (additions), `bot/evaluator.py` (`eval7`), `bot/equity.py` (`equity`, sampling helpers,
`canon3`), the `# --- W2 ---` section of `bot/params.py`, `tests/test_evaluator.py`, `tests/test_equity.py`,
`scripts/bench_equity.py` (benchmark, not shipped: it lives outside `bot/`).
**Out (later features):** `eval_batch` and numpy (F08); the preflop table that uses `canon3` (F07); 3-card hero
equity before the discard, keep selection and opponent discard modelling (F04, F10); any use in decisions (F04–F06).
Nothing in `brain.py` or `placeholder.py` changes, so bot behaviour is identical to v0 (§6E).

**Interface changes to `agents/INTERFACES.md`, applied on approval:**
- `cards.py`: adds `deck_without(dead) -> list[int]`, `pair_index(a, b) -> int`, `PAIRS: list[tuple[int, int]]`
  (1,326 entries), `dead_mask(cards) -> bytearray`.
- `evaluator.py`: `eval7` as in the contract. `eval_batch` stays in the contract but is **not** implemented until
  F08 (the module does not define it before then, so a premature caller fails at import time in tests, not at runtime).
- `equity.py`: `equity(...)` and `canon3(...)` as in the contract, plus three new functions for common random
  numbers: `deal_samples(board, opp_weights, dead, n, rng) -> list[tuple]` (post-discard: the opponent holds 2),
  `deal_triple_samples(board, dead, n, rng, keep_fn) -> list[tuple]` (pre-discard: the opponent holds 3 and
  discards one) and `equity_vs_samples(hero2, board, samples) -> float`.
- `opp_weights` format is pinned down (it was "dict or array"): `None` (uniform), a sequence of 1,326 numbers
  indexed by `pair_index`, or a `dict` `{(a, b): w}` with `a < b`.

## 3. Design

### 3.1 `cards.py` additions
- `pair_index(a, b)`: for card ids `a != b`, with `lo, hi = min, max`: `hi * (hi - 1) // 2 + lo`, a bijection onto
  `0..1325`. `PAIRS[i]` is the inverse `(lo, hi)`, built once at import (1,326 tuples).
- `dead_mask(cards)`: `bytearray(52)` with the given ids set (ints outside `0..51` are ignored).
- `deck_without(dead)`: `[c for c in range(52) if not dead[c]]`, where `dead` is any length-52 sequence of
  flags (`HandState.dead`, a `bytearray`, a list of bools).

### 3.2 `evaluator.py`: `eval7(cards) -> int`
Input: 5, 6 or 7 **distinct** ids in `0..51` (callers guarantee this; no validation in the hot path). Output: an int,
higher is better, equal iff the engine's `best_hand` tuples are equal.

Encoding: `cat << 20 | k1 << 16 | k2 << 12 | k3 << 8 | k4 << 4 | k5`, ranks `0..12` (`2..A`), unused nibbles 0.

| cat | Hand | k1..k5 |
|---|---|---|
| 8 | straight flush | high card of the straight (wheel A-2-3-4-5 → rank of 5 = 3) |
| 7 | quads | quad rank, highest other rank present |
| 6 | full house | trips rank (highest trips), pair rank = highest *other* rank with count ≥ 2 (a second trips counts as a pair) |
| 5 | flush | top 5 ranks **of the flush suit** |
| 4 | straight | high card (wheel → 3) |
| 3 | trips | trips rank, top 2 other ranks |
| 2 | two pair | high pair, second pair, highest other rank present (**including a third pair's rank**) |
| 1 | pair | pair rank, top 3 other ranks |
| 0 | high card | top 5 ranks |

Algorithm (one pass, from our own prototype `research/bench_discard.py`): per-rank counts `cnt[13]` and per-suit
rank bitmasks `smask[4]`. If some suit has ≥ 5 cards (at most one can, with ≤ 7 cards): straight flush if that suit's
mask contains a straight, else remember the flush value. Then, from the rank counts (high to low): quads → full house
→ flush → straight (on the OR of all rank bits) → trips → two pair → pair → high card. Straights use 10 precomputed
masks, checked from the highest (`A-K-Q-J-T`) down to the wheel (`A-5-4-3-2` = `0x100F`).

Why this matches the engine: `engine.rank5` compares tuples `(category, …)` with the same category order and the same
tie-breaking groups (`by_group` sorted by count then rank; flush/high by all 5 values; straights by high card, wheel =
5). `best_hand` takes the max over all 5-card subsets; the table above picks exactly the best 5 cards per category.
§6A checks this exhaustively on 5-card classes and statistically on 7-card showdowns.

### 3.3 `equity.py`
**Inputs.** `hero2`: 2 ids. `board`: 3, 4 or 5 ids. `dead`: length-52 flags (normally `HandState.dead`: our 3
original hole cards, the board and the opponent's exposed discard). `opp_weights`: see §2. `budget_ms`: float.
`rng`: a `random.Random` (or `None` → a module-level `random.Random()`).

**Excluded cards** `X = dead ∪ hero2 ∪ board` (the union is taken defensively, so a caller that forgets to mark
something dead still gets a consistent deal). The opponent's pair and the runout never contain a card of `X`.

**Range preparation** `_range(opp_weights, X) -> (pairs, w, cum, total)`: every pair `(a, b)` with neither card in
`X`, raw weight `float(weight)`; non-finite or negative weights count as 0; pairs with weight 0 are dropped. The kept
weights are then **rescaled by their maximum** (`w_i = raw_i / max raw`, so `w ∈ (0, 1]` and the largest is exactly
1). Because there are ≤ 1,326 pairs, `total = Σw ≤ 1326` and `Σw² ≤ 1326` can neither overflow nor be 0, whatever
the input scale (1e308 or 1e-300). Relative weights below ~1e-154 may square to 0; their contribution is negligible
and `Σw² ≥ 1` from the maximum, so `n_eff` stays finite. If nothing is left (all weights 0 or all pairs blocked), fall
back to **uniform over the valid pairs** and log a warning once. If no valid pair exists at all (impossible with ≤ 10
excluded cards), `equity` returns `(0.5, 0.0)`. `cum` is the running sum for weighted sampling (`bisect` on
`rng.random() * total`).

**Showdown value** `v(hero, opp) = 1` if `hero > opp`, `0.5` if equal, else `0`, from `eval7` on the full 7 cards.

**River (`len(board) == 5`): exact enumeration when it fits, otherwise weighted i.i.d. sampling. The choice uses
only rng-free work.** Hero's value is evaluated once. Let `P` be the number of valid pairs (≤ 903 in a real hand:
52 − 3 − 5 − 1 = 43 cards). `PAIRS` order (canonical) is the enumeration order. Two estimators exist; neither is ever
replaced by a truncated mix of the two:
- *i.i.d.:* pairs drawn `∝ w` with replacement (from `cum`); estimate = the **plain mean** of `v`. For a fixed sample
  count this is unbiased for any weights (`E[v] = Σ w·v / Σ w`); `n_eff = n`.
- *exact:* all `P` pairs; estimate `Σ w·v / Σ w`; `n_eff = (Σw)² / Σw²`.

**Selection rule (Codex round 3, B1).** The decision between the two must not depend on any sample that the returned
estimate uses. Round 3 calibrated on the first `MIN_SAMPLES` i.i.d. samples and then either kept their mean or
replaced it with the exact value. If evaluation cost depends on the hand, that choice correlates with the sample
values, and the result is biased: Codex's example gives an expected 0.4829 against a true 0.5. Now calibration
uses the **first pairs of the deterministic enumeration**, which consume no randomness. The selection is then a
function of the inputs and machine timing only, so it is independent of the rng draws behind any i.i.d. estimate.
The calibration work is never wasted: if the upgrade goes ahead, those pairs are already part of the enumeration.

Procedure, with the deadline formed at function entry (§Budget):
1. **`b = +inf`:** exact enumeration, nothing else (deterministic; used by tests and by callers that want exactness).
2. **`b = 0`** (after normalisation): straight to i.i.d., exactly `MIN_SAMPLES` samples, with no calibration. This
   depends on `b` alone.
3. **Calibration (finite `b > 0`):** enumerate the first `CAL = min(MIN_SAMPLES, P)` pairs in canonical order,
   checking the deadline every `CHECK_EVERY` pairs. If `CAL == P`, the enumeration is complete: return exact. If
   the deadline passes during calibration, go to step 5 (fallback). Otherwise `t_pair = calibration elapsed / CAL`.
4. **Upgrade decision:** if `remaining = deadline − _now() ≥ RIVER_SAFETY · (P − CAL) · t_pair`
   (`RIVER_SAFETY = 1.5`), continue the enumeration, checking the deadline every `CHECK_EVERY` pairs. If it
   **completes**, return the exact result. If the deadline passes first (the machine slowed down after
   calibration), **discard the partial enumeration** and go to step 5. If the upgrade does not fit, go to step 6.
5. **Fallback (deadline already passed):** exactly `MIN_SAMPLES` fresh i.i.d. samples, a fixed count with no deadline
   checks. Return their plain mean. No randomness was consumed before this step, and the event that led here depends
   only on rng-free work, so this mean is unbiased.
6. **No upgrade:** i.i.d. sampling to the deadline (same rules as the turn/flop: at least `MIN_SAMPLES`, deadline
   checked every `CHECK_EVERY`, `MAX_SAMPLES` cap). Return the plain mean.

A partial enumeration is never returned: with concentrated weights it is badly biased (Codex round 1, B1: one winning
pair of weight 1e6 among 127 losing pairs of weight 1, exact 0.999873, a 64-pair subset averages 0.5). Locally a full
enumeration costs ~3–4 ms, so budgets of ≥ ~6 ms get exact rivers; a slower judge self-adjusts through step 3. The
canonical-order prefix may be cheaper or dearer than the average pair. `RIVER_SAFETY` absorbs moderate mismatch,
step 5 handles the rest, and step 5 is never biased.

**Bias (all streets).** With a fixed sample count, the i.i.d. and Monte Carlo means are unbiased. Every finite
budget stops at a wall-clock deadline, though, and if a sample's evaluation cost correlates with its value, the
stopping point correlates with the running mean. This is a small bias that **is not eliminated** (it would need a
sample count fixed in advance, and then a hard deadline would be impossible). It is bounded instead.

*Decomposition.* Let the checkpoints be `n_0 = 64`, `n_{j+1} = n_j + 32`, let `N` be the checkpoint where sampling
stops, `m_n` the mean of the first `n` samples, `μ` the true value, and `σ² ≤ 1/4` the per-sample variance (values
lie in [0, 1]). The 32 samples after `n_j` are independent of the event `{N > n_j}`, which is decided at `n_j`. So:

  `E[m_N] − μ = Σ_j 32/(n_j + 32) · E[1{N > n_j} · (μ − m_{n_j})]`

and each term is at most `32/(n_j + 32) · E|m_{n_j} − μ| / 2 ≤ 32 / ((n_j + 32) · 4√n_j)`. This **per-checkpoint
cap** holds for any values and any stopping rule. It is 0.0104 at 64 samples, 0.0064 at 96, 0.0033 at 160, 0.0013
at 320, 0.00025 at 1,000, and it falls like `n^(−3/2)`. Summed over every checkpoint up to `MAX_SAMPLES`, it gives a
distribution-free ceiling of 0.057. That ceiling only applies if an adversary could make the stop/continue decision
uncertain at every checkpoint at once.

*A deadline rule.* Elapsed time only grows, so `{N > n_j} = {C(n_j) < deadline}`, where `C(n)` is the cumulative
cost. Only checkpoints whose cumulative cost straddles the budget contribute. A block costs about 32 × the mean cost,
much more than the spread of `C(n)`, so for a given budget one or two checkpoints dominate.

*Exact computation (corrects round 3, Codex round 4 B1).* The closed form above was evaluated exactly with Binomial
probabilities and matches a brute-force dynamic program, including Codex's case (1.2×, B = 70.4 → −0.0082789). The
scan covered:
- values Bernoulli(p), p ∈ {0.1, 0.3, 0.5};
- cost ratios 1.05, 1.1, 1.2, 1.5, 2 and 3, with the win either cheaper or dearer;
- every budget on a 0.05–0.1-unit grid, from 0 up to 1,400 samples (4,000 samples for ratios 1.2, 2 and 3).

| budgets that give at least … samples | 64 | 96 | 160 | 320 | 640 | 1,000 | 2,000 |
|---|---|---|---|---|---|---|---|
| sup \|bias\| (any ratio scanned, p = 0.5) | 0.0083 | 0.0051 | 0.0026 | 0.0010 | 0.0004 | 0.0002 | 0.0001 |
| per-checkpoint cap | 0.0104 | 0.0064 | 0.0033 | 0.0013 | 0.0005 | 0.00025 | 0.0001 |

The **cost ratio does not change the worst case**; my round 3 claim that a 1.2× ratio is negligible at every budget
was wrong. The ratio only sets how narrow the budget window is in which the worst case occurs, which is near
`n × mean cost`. For p = 0.3 and p = 0.1 the worst case is lower (0.0076 and 0.0050).

*Claim.* No selection bias. For a deadline-stopped mean whose first checkpoint is at `n` samples, |bias| is at most
the per-checkpoint cap at `n` (≤ 0.0104 overall). The exact scan above confirms ≤ 0.0083 over the stated range. The
bias is always a small fraction of the Monte Carlo standard error at the same sample count: the ratio is at most
`≈ 16/(n + 32)`, which is 17% at 64 samples, 8% at 160 and 1.6% at 1,000, so the mean squared error grows by ≤ 3%.
§6B9 checks it with a cost-dependent fake evaluator, at budgets placed on the checkpoint transitions.

**Turn and flop (`len(board) in (3, 4)`): Monte Carlo, sampling the range.** Each sample draws the opponent pair
`∝ w` from `cum`, then the `5 − len(board)` missing board cards uniformly from the cards not in `X` and not in
the pair (rejection: draw from the `X`-free deck, redraw on a collision with the pair; ≤ 2 cards, so rejections are
rare). Every sample has weight 1, so the estimate is the plain mean and `n_eff = n`. Hero's 7-card value depends only
on the runout, so it is cached per runout in a dict (key: the sorted runout tuple; ≤ 44 keys on the turn, ≤ 990 on the
flop), roughly halving the evals.

Why not the strategy note's "turn: all 44 rivers × top-K pairs": truncating to the top K pairs biases the estimate,
and for a fixed number of evals, independent joint samples of (pair, river) have lower variance than enumerating all
rivers for fewer pairs (the per-pair variance is multiplied by ~44 evals per pair). The hero cache gives the main
saving of the enumeration idea without the bias.

**Budget.** First normalise: `b = budget_ms` if it is a real number (not bool), else 0; NaN, 0 and negatives → 0;
`+inf` stays `+inf`. Then, **at function entry, before range preparation** (so preparation time counts against the
budget), `deadline = _now() + b / 1000` (`+inf` when `b` is infinite). `_now` (= `time.perf_counter`) and `_eval`
(= `evaluator.eval7`) are module attributes that `equity.py` calls through, so tests can substitute a fake clock and
a slow evaluator. The deadline is checked every `CHECK_EVERY` samples (or enumerated pairs). A sampling loop never
stops before `MIN_SAMPLES` samples. So: `b = 0` → exactly `MIN_SAMPLES` (a panic-tier caller still gets a usable
answer for ≈ 0.3 ms); `b = +inf` → exactly `MAX_SAMPLES` on the turn/flop and exact enumeration on the river.
**Time bound** for every finite-budget call: `elapsed ≤ max(b, prep) + one CHECK_EVERY block + MIN_SAMPLES samples`.
On the turn and flop, and on the river's no-upgrade path, this tightens to the round 3 form
`max(b, prep + MIN_SAMPLES samples) + one block`. The extra `MIN_SAMPLES` term only applies to the river fallback
(step 5), which runs after an interrupted calibration or upgrade.

**Common random numbers.** A sample is a tuple `(opp_pair, runout)`: the opponent's 2 final hole cards and the
`5 − len(board)` missing board cards.
- `deal_samples(board, opp_weights, dead, n, rng)` — **post-discard states only** (the opponent already holds 2 and
  their discard is known and in `dead`): `n` samples drawn exactly as above, with `X = dead ∪ board`.
- `deal_triple_samples(board, dead, n, rng, keep_fn)` — **pre-discard states** (our discard decision on the flop, and
  flop betting before the discard): the opponent still holds 3 cards and discards one simultaneously with us. A
  marginal pair weighting cannot represent this, because the discarded third card depends on the triple and must be
  excluded from that sample's runout. Each sample: draw the opponent triple uniformly from the cards not in
  `X = dead ∪ board` (`rng.sample` of 3), call `keep_fn(triple, board) -> pair` (F04 supplies the opponent discard
  policy; it sees only the triple and the public board), then draw the runout from the cards not in `X` and **not in
  the triple** (all three opponent cards are excluded, the discarded one included). If `keep_fn` raises or returns
  something that is not 2 distinct cards of the triple, that sample keeps the two highest-rank cards (the inverse of
  the engine's default discard) — so a broken policy degrades, never crashes. Non-uniform triple priors are F10's job.
- `equity_vs_samples(hero2, board, samples)`: the mean showdown value of `hero2` over the samples (runout cache as
  above), whichever generator produced them. Calling it for each of our 3 candidate keeps on the same samples gives
  low-noise *differences*. Contract: no sample card overlaps `hero2` or `board` (both generators guarantee it when our
  hole cards are in `dead`).
- No budget inside these three: the caller sizes `n` (e.g. from a timed first batch). `equity_vs_samples` returns 0.5
  for an empty sample list.

**`equity(hero2, board, opp_weights, dead, budget_ms, rng) -> (eq, n_eff)`** dispatches to the river or Monte Carlo
path. `eq` is in `[0, 1]`.

### 3.4 `canon3(cards3) -> int` (in `equity.py`, per the contract)
The suit-isomorphism class of a 3-card hand, an index in `0..1754`. Class key from the cards' ranks and which cards
share a suit:
- three distinct ranks `r1 > r2 > r3`: suit pattern ∈ {all same, r1=r2≠r3, r1=r3≠r2, r2=r3≠r1, all different}
  (286 × 5 = 1,430 classes);
- a pair `p` plus kicker `k`: kicker suited with one pair card, or not (13 × 12 × 2 = 312);
- trips: 13.

Total 1,755. The index is the position of the key in the **sorted** list of all keys, built once at import from the
1,755 keys (no enumeration of the 22,100 triples at runtime). F07's table is indexed by this order, so it is part of
the contract and pinned by a test (§6D).

### 3.5 `params.py` (`# --- W2 ---`)
`MIN_SAMPLES = 64`, `MAX_SAMPLES = 20000`, `CHECK_EVERY = 32`, `RIVER_SAFETY = 1.5`.

## 4. Edge cases
1. Wheel (`A2345`) and steel wheel (straight flush to 5): high card 3; `A2345` loses to `23456`.
2. Six or seven cards of one suit: flush value uses the top 5 of that suit only; a straight flush inside that suit
   beats a higher non-flush straight.
3. Two trips in 7 cards: full house, trips = higher, pair = lower trips.
4. Three pairs: two pair with the best two, kicker = max(third pair rank, single).
5. Quads + trips or quads + pair: kicker = highest other rank.
6. Board plays (both players' best five are the board): equal values → tie → 0.5.
7. Straight on board vs flush in hand, flush vs full house: category order.
8. 5- and 6-card inputs (flop and turn showdown values for F04).
9. Opponent range entirely blocked by dead cards or all-zero / NaN / negative weights → uniform fallback.
   Extreme but finite scales (1e308, 1e-300) → rescaled by the maximum, finite results identical to ordinary scales.
10. Duplicate or out-of-range ids passed by a caller → not validated in `eval7` (hot path); `equity` builds its
    excluded set itself and never deals a card twice. Documented as a caller contract.
11. `budget_ms` 0, negative, NaN or non-numeric → normalised to 0 → `MIN_SAMPLES` (river: i.i.d. path); `+inf` →
    `MAX_SAMPLES` (river: exact enumeration).
12. `rng=None` → module default generator; tests always pass a seeded `random.Random`.
13. `keep_fn` raising or returning a bad pair → that sample keeps the two highest-rank cards of the triple.

## 5. Failure handling and time
- All functions are pure; nothing touches stdout or files. They can raise only on caller contract violations (e.g.
  a hero card id of 52). Callers in F04+ run inside the F01 firewall, which falls back on any exception.
- Every finite-budget `equity` call, on every street, satisfies `elapsed ≤ max(budget, prep) + one CHECK_EVERY block
  + MIN_SAMPLES samples`, measured from function entry (preparation included). The `MIN_SAMPLES` term is reached
  only by the river fallback, ≈ 0.3 ms locally. This holds on a slow machine too:
  nothing runs to completion unconditionally except the `budget_ms = +inf` paths, which callers use only offline or
  in tests. The `MIN_SAMPLES` floor is ≈ 0.3 ms locally; the `MAX_SAMPLES` ceiling is ≈ 100 ms (callers pass
  budgets ≤ 400 ms per the F01 clock).
- Import cost: `PAIRS` (1,326 tuples) + `canon3` keys (1,755) + straight masks: target < 20 ms, measured in §6F.

## 6. Tests (check two ways)
**A. `eval7` vs the engine (`tests/test_evaluator.py`).**
1. *Exhaustive 5-card ordering:* one representative 5-card hand per rank class — all 6,175 non-flush rank
   multisets (suits assigned so no flush) and all 1,287 flush rank sets (one suit) — evaluated by `engine.rank5`
   and by `eval7`. Sorting by `rank5` must give a non-decreasing `eval7`, with `eval7` equal iff `rank5` is equal,
   and exactly 7,462 distinct `eval7` values.
2. *Random 7-card showdowns:* ≥ 50,000 deals of 2 + 2 hole cards and a 5-card board (seeded): the sign of
   `eval7(h1 + b) − eval7(h2 + b)` equals the sign of the `engine.best_hand` comparison. Plus ≥ 10,000 random
   6-card and 5-card pairs (same board) the same way.
3. *Named edge cases* (§4 items 1–7), each with an expected comparison and, where useful, an expected category.

**B. Equity: Monte Carlo vs exact (`tests/test_equity.py`).**
1. *River exact vs an independent brute force:* the brute force iterates over all valid pairs with
   `engine.best_hand` (different evaluator, different loop). Uniform and non-uniform weights, `budget_ms = inf`
   (exact path); equal within 1e-12.
   - *River truncated budget, concentrated range (B1's case):* 128 positive-weight pairs (all others weight 0), one
   winning pair of weight 1e6 and 127 losing pairs of weight 1 (exact 0.999873); with `budget_ms = 0` (i.i.d. path, `MIN_SAMPLES`), the mean of the
   estimate over 200 seeds is within 0.005 of exact; and a uniform-range river with `budget_ms = 0` averages within
   4 SE of the exact value over 200 seeds.
2. *Turn MC vs exact:* exact = full enumeration of (pair, river) with weights, computed in the test. MC with a large
   budget (≥ 8,000 samples): `|mc − exact| ≤ 4 · sqrt(p(1−p)/n)`. Uniform range and a 3-pair range.
3. *Flop MC vs exact on a small range:* opponent range of 3 pairs, exact = all pairs × all C(45, 2) runouts. Same
   4-SE tolerance.
4. *Sampling hygiene:* over 20,000 `deal_samples`, no dealt card is in `dead ∪ board`, no card repeats within a
   sample, and pair frequencies match the weights (chi-square, p > 0.001, seeded).
5. *Weights formats and scale* (deterministic only: no wall-clock dependence).
   - **Formats, exact equality:** the same numeric weights as a 1,326 list, a dict and a numpy array (and `None` vs a
     list of all ones) give identical `deal_samples` with the same seed, and identical `equity` with
     `budget_ms = inf` (fixed `MAX_SAMPLES` count; river: exact). Same numbers in the same canonical order, so the
     rescaled values are bit-identical.
   - **Scale, tolerance:** rescaling by the maximum can change ratios in the last bit (Codex round 2, B2: weights
     [1, 3, 7] give 0.7727272727272727 at scale 1 and …728 at 1e-300). So the same range multiplied by 1, 1e300 and
     1e-300 is compared with `math.isclose(rel_tol=1e-12)` for the river exact equity and for `n_eff`, all values
     finite. For Monte Carlo (turn), each scale's estimate (`budget_ms = inf`) must be finite and within 4 SE of the
     exact value; no cross-scale equality is asserted for sampled results.
   - NaN / negative / all-zero / fully blocked ranges fall back to uniform.
6. *CRN:* `equity_vs_samples` on the same samples is deterministic, and for a dominated keep (e.g. 72o vs AA on
   a low board) the difference has the expected sign.
7. *Budget with a simulated machine:* `equity._now` returns a fake time, and `equity._eval` is replaced by a wrapper
   around `eval7` that advances the fake time by a configurable cost per call (other code takes zero fake time), so
   sample counts and elapsed fake time are exact.
   - `budget_ms` 0, −5, NaN, `"x"` → exactly `MIN_SAMPLES` (turn, flop and river); `+inf` → exactly `MAX_SAMPLES`
     (turn, flop) and a complete enumeration (river); a finite budget stops at the first `CHECK_EVERY` boundary past
     the deadline.
   - **River, fast machine** (3 µs/eval, 903 pairs, 10 ms budget): the calibration prefix runs, the enumeration fits,
     the result equals the exact value, and **the rng is untouched** (its state is unchanged after the call).
   - **River, slow machine** (20 µs/eval, 6 ms budget, Codex round 2 B1's case): calibration (64 pairs ≈ 1.3 ms) shows
     that the upgrade does not fit; the result is the i.i.d. mean, and fake elapsed ≤ 6 ms + one `CHECK_EVERY` block.
   - **River, slowdown after calibration** (3 µs/eval for the first `MIN_SAMPLES` evals after hero's, then 20 µs;
     10 ms budget, so 1.5 × 839 × 3 µs ≈ 3.8 ms fits but the real ~17 ms does not): the upgrade starts and is
     interrupted at the deadline. The call returns the step-5 fallback, which equals the mean of exactly
     `MIN_SAMPLES` i.i.d. samples recomputed in the test from a fresh generator with the same seed. Fake elapsed
     ≤ budget + one block + `MIN_SAMPLES` evals.
   - **River, deadline passes during calibration** (20 µs/eval, 0.5 ms budget): fallback with exactly `MIN_SAMPLES`
     samples; fake elapsed ≤ budget + one block + `MIN_SAMPLES` evals.
   - **River, `P ≤ MIN_SAMPLES`** (a 40-pair range, finite budget): calibration covers the whole range, so the result
     is exact.
   - Separately, **one real-time check**: a 5 ms budget returns within 5 ms + 2 ms slack (timing only, no equality
     assertions).
8. *Triple samples:* over 5,000 `deal_triple_samples` with a recording `keep_fn`: the kept pair is 2 distinct cards
   of the triple the policy was shown; **no runout card is any of the 3 opponent cards** (the discarded one
   included), nor in `dead ∪ board`; a `keep_fn` that raises or returns `(c, c)` / a card outside the triple yields
   the two highest-rank cards. Exactness: on a 5-card board (empty runout, so the test can enumerate all ~13,000 opponent
   triples exactly), `equity_vs_samples` over 20,000 triple samples with a deterministic `keep_fn` (keep the two
   highest ranks) agrees within 4 SE with the exact average over all triples, computed in the test with
   `engine.best_hand`. Exclusion on the flop is covered by the hygiene checks above.
9. *Cost-dependent evaluator (Codex round 3, B1):* same harness as 7. The fake `_eval` is memoised over `eval7` so the
   test stays fast. It advances fake time by **1 unit (10 µs) when the evaluated hand is below hero's value and 2
   units otherwise**, so cost is perfectly correlated with the sample's value, as in Codex's counterexample.
   - **Codex's exact case:** two equally weighted pairs, one losing to hero and one beating hero, budget 96 units.
     Since `P ≤ MIN_SAMPLES`, calibration completes the enumeration, and **every** seed (500 seeds) returns exactly
     0.5. The round 3 design's expectation was 0.4829.
   - **Selection is rng-free:** a 400-pair range (200 pairs below hero, 200 above, weight 1, true equity 0.5) at a
     budget where the upgrade does not fit. Asserted: the calibration's elapsed fake time and the upgrade decision
     are identical for every seed (they do not depend on the rng). A budget where the upgrade fits returns exactly
     0.5 for every seed.
   - **Deadline-stopping bias at the checkpoint transitions (Codex round 4, B1):** the losing-opponent cost stays
     at 1 unit and the winning-opponent cost is set to `r` units, for r ∈ {1.2, 2}. On the same 400-pair river range
     (Bernoulli(0.5) values, i.i.d. path), the budget is placed exactly on a transition:
     `B = calibration + hero cost + n · (1 + r)/2` for n ∈ {64, 160}. The calibration cost is deterministic and is
     measured by the previous bullet. Case r = 1.2, n = 64 is Codex's B = 70.4. Each configuration runs 3,000 seeds.
     The test asserts:
     - the empirical mean is within 4 SE of the **closed-form prediction**. A ~30-line helper in the test,
       `stopping_bias(c_win, c_lose, p, B)`, evaluates the §3.3 decomposition exactly with `math.comb`. For Codex's
       case it returns 0.4917211 within 1e-9, and a unit test checks it against a brute-force dynamic program.
     - |prediction − 0.5| is at most the per-checkpoint cap at that `n` (0.0104 or 0.0033).
   - **Turn:** a 3-pair turn range with the same cost rule (hero's own evaluations cost 0) and budgets near the
     64- and 160-sample transitions. The mean over 3,000 seeds is within `4 · SE + cap(n)` of the exact turn equity
     computed in the test.
   - **Scan reproduced:** `scripts/bench_equity.py --bias` prints the §3.3 table (every ratio, p and budget listed
     there). Its output is recorded in the implementation log.

**C. Cards.** `pair_index` is a bijection onto `0..1325` and `PAIRS` is its inverse; `deck_without(dead_mask(x))`
excludes exactly `x`.

**D. `canon3`.** All 22,100 triples map to exactly 1,755 indices covering `0..1754`; the index is invariant under
all 24 suit permutations and under card order; class sizes: 1,430 / 312 / 13 keys by type, and the sizes summed
over classes equal 22,100. Pinned values: `canon3` of `["2s","3s","4s"]`, `["As","Ah","Ad"]` and `["Ks","Kh","2s"]`
are checked against literal expected indices (so a later reordering is caught).

**E. No behaviour change.** `pytest` green; `promote.py --dry-run` reports head-to-head exactly 0 vs v0 (nothing
imports the new modules yet, but this proves it).

**F. Benchmarks (recorded in the review log, `scripts/bench_equity.py`).** `eval7` evals/s on random 7-card hands
(target ≥ 250k locally); `equity` samples/ms on flop, turn and river (river: ms per full enumeration); import time.
**Cost/value correlation:** the mean `eval7` time for opponent hands that beat hero vs hands that lose, over random
rivers, and the spread of cost by hand category. This is informational: the §3.3 bound does not depend on the
ratio. The ratio only sets how wide the budget window around each checkpoint transition is.

## 7. Acceptance criteria
- [ ] §6A–D pass; `pytest` green; `scripts/build.py --check` passes.
- [ ] `eval7` ≥ 250k evals/s locally; equity throughput recorded.
- [ ] §6E: head-to-head vs v0 exactly 0, no notices, no forfeits.
- [ ] `agents/INTERFACES.md` updated with the §2 changes; `strategies/02_*` E1, E3, E4 `Status:` lines updated.

## 8. Risks and open questions (for the reviewer)
1. **Monte Carlo vs exact on the turn.** Chosen: joint sampling with a hero cache (unbiased for a fixed sample count, best variance per eval).
   The alternative (enumerate rivers for the top-K pairs) is biased by the truncation.
2. **River: rng-free calibration, then exact or i.i.d.** The upgrade decision uses the cost of the enumeration's
   first `MIN_SAMPLES` pairs, measured on the running machine, and consumes no randomness, so it cannot correlate
   with any returned sample. The enumeration stays interruptible. An interrupted enumeration is discarded (its time
   is lost), and a fixed-count fallback of `MIN_SAMPLES` fresh samples is returned; this costs ≈ 0.3 ms beyond the
   deadline. With `RIVER_SAFETY = 1.5` this should be rare.
3. **3-card hero equity** (flop betting before the discard) is not in F02. F04/F06 compose it from
   `deal_triple_samples` (the opponent's discard modelled per triple, all three of their cards excluded from the
   runout) + `equity_vs_samples` (max over our 3 keeps on common samples).
4. **`eval_batch` deferred** to F08; scalar speed (~300k evals/s ≈ 200 samples/ms) supports ~4,000 samples in a
   20 ms decision, ±0.8 points standard error.
5. **Deadline-stopping bias is accepted, not eliminated** (§3.3 *Bias*). Removing it would need a sample count fixed
   in advance, which cannot coexist with a hard deadline on an unpredictable machine. The bound does not depend on
   the cost ratio: ≤ 0.0104 analytically and 0.0083 in the exact scan, both at the 64-sample checkpoint, falling like
   `n^(−3/2)`. It is ≤ 17% of the Monte Carlo standard error at any sample count. It is tested (§6B9) and the real
   cost/value correlation is measured (§6F).

## Review log
### Round 1: 2026-11-11 (Codex: 5 bugs; all accepted, all fixed in round 2)
| Bug | Severity | Finding (Codex) | Resolution (Claude) |
|---|---|---|---|
| B1 | major | A budget-truncated river enumeration (weighted average over a uniform random subset) can be severely biased with a concentrated range (exact 0.999873, expected estimate 0.5). | **fixed:** the river path is chosen up front and never truncated: exact enumeration iff `P · RIVER_US_PER_PAIR ≤ budget` (runs to completion, overshoot ≤ 990 evals), else i.i.d. samples drawn `∝ w` with a plain mean, which is unbiased for any weights (§3.3). §1 and §8.2 reworded. New test §6B1 (second bullet) uses exactly this concentrated range with a zero budget across 200 seeds. *(The fixed-cost upgrade rule was replaced in round 2, B1.)* |
| B2 | major | Finite weights can overflow the cumulative sum (two weights of 1e308 → inf) or underflow when squared. | **fixed:** positive finite weights are rescaled by their maximum before any sum (`w ∈ (0, 1]`, `Σw ≤ 1326`, `Σw² ≥ 1`), so totals, the bisect target, weighted means and `n_eff` stay finite (§3.3). §6B5 tests scale invariance at 1, 1e300 and 1e-300 with finite outputs. |
| B3 | major | A NaN budget makes the deadline NaN, so the loop runs to `MAX_SAMPLES`, not `MIN_SAMPLES`. | **fixed:** the budget is normalised before the deadline is formed: non-numbers, NaN, 0 and negatives → 0 (→ exactly `MIN_SAMPLES`); `+inf` → no deadline (→ exactly `MAX_SAMPLES`, river exact) (§3.3, edge case 11). §6B7 tests 0, −5, NaN, `"x"` and `+inf` with a fake `_now` and exact sample counts. |
| B4 | major | `deal_samples` + `equity_vs_samples` cannot model the opponent's pre-discard triple: the discarded card depends on the triple and must be excluded from that sample's runout. | **fixed:** new `deal_triple_samples(board, dead, n, rng, keep_fn)` draws the triple, applies the caller's discard policy to (triple, board) only, and excludes **all three** opponent cards from the runout; a broken `keep_fn` degrades to keeping the two highest ranks (§3.3, §2 interface list, edge case 13). §8.3 corrected: `deal_samples` is for post-discard states only. Tested now (§6B8: exclusion of the discarded card, kept pair ⊂ triple, policy failures, and exactness against a full triple enumeration on a 5-card board), not deferred to F04. |
| B5 | minor | Format-equivalence tests assert equality on a wall-clock-bounded function, so sample counts can differ. | **fixed:** equality assertions use only deterministic paths: `deal_samples` with a seed, `equity` with `budget_ms = inf` (fixed `MAX_SAMPLES` count; river exact), or a fake clock. The single real-time check asserts timing only (§6B5, §6B7). |

### Round 2: 2026-11-11 (Codex: 2 bugs; both accepted, both fixed in round 3)
| Bug | Severity | Finding (Codex) | Resolution (Claude) |
|---|---|---|---|
| B1 | major | The river's exact path runs to completion based on a fixed 6 µs/pair estimate; at 20 µs/eval a 6 ms budget takes ~18 ms, breaking the per-call deadline. | **fixed:** finite-budget river calls now start with `MIN_SAMPLES` i.i.d. weighted samples (a valid unbiased estimate), which also **measure the per-eval cost on the running machine**; exact enumeration is attempted only if `1.5 × P × measured cost` fits in the remaining time, stays interruptible, and if interrupted is discarded in favour of the i.i.d. estimate; otherwise i.i.d. sampling continues to the deadline. Only `budget_ms = +inf` enumerates unconditionally. The deadline is now formed at function entry, so preparation counts. Stated bound: `elapsed ≤ max(budget, prep + MIN_SAMPLES) + one CHECK_EVERY block` (§3.3, §Budget, §5, §8.2; `RIVER_US_PER_PAIR` replaced by `RIVER_SAFETY`). §6B7 adds a simulated-machine harness (fake `_now` advanced by a fake `_eval`) with fast, slow (B1's exact case) and slows-after-calibration river tests. |
| B2 | minor | Max-rescaling can change weight ratios in the last bit, so exact equality across scales can fail for a correct implementation. | **fixed:** §6B5 split: exact equality only for the same numbers in different formats (bit-identical after rescaling); across scales, `math.isclose(rel_tol=1e-12)` for river exact equity and `n_eff`, and for Monte Carlo each scale is checked against the exact value within 4 SE, with no cross-scale equality. |

### Round 3: 2026-11-11 (Codex: 1 bug; accepted, fixed in round 4)
| Bug | Severity | Finding (Codex) | Resolution (Claude) |
|---|---|---|---|
| B1 | major | The phase-1 samples both supply the fallback estimate and measure the cost that decides whether to replace it with exact equity. If evaluation cost depends on the hand, this selection correlates with the sample values. Codex's counterexample (pairs worth 1 and 0 costing 1 and 2 units, budget 96) gives an expected 0.4829 against a true 0.5. A mean stopped by outcome-dependent elapsed time also needs treatment. | **fixed:** (1) *Selection:* calibration now runs on the first `min(MIN_SAMPLES, P)` pairs of the deterministic enumeration, which consumes no randomness. The exact-vs-i.i.d. choice therefore depends only on the inputs and machine timing, never on a returned sample. The prefix counts towards the enumeration if the upgrade goes ahead. An interrupted calibration or upgrade falls back to exactly `MIN_SAMPLES` fresh i.i.d. samples (fixed count, so unbiased). `b = 0` skips calibration (§3.3 steps 1–6). The time bound becomes `max(b, prep) + one block + MIN_SAMPLES samples` (the extra term applies only to the river fallback) (§Budget, §5). (2) *Deadline stopping:* adopted as an approximate estimator with a quantified bound rather than claiming unbiasedness (§1, §3.3 *Bias*, §8.5). Exact dynamic programming over the stopping rule: worst case −0.0083 for a 2× perfectly correlated cost at a 96-unit budget, ≤ 0.0003 at ≥ 400 units, ≤ 1e-5 for a 1.2× ratio. *(The 1.2× claim was wrong: it came from testing a few budgets off the checkpoint transitions. It is corrected in round 5; see round 4, B1.)* (3) *Tests:* new §6B9 uses a cost-dependent fake evaluator. Codex's exact case now returns exactly 0.5 on every seed; the test asserts that the calibration time and upgrade decision are identical across seeds; and the deadline-stopping bias stays within `4·SE + 0.01` at 96, 200 and 400 units on the river and turn. §6B7's river cases were updated for the new calibration; two cases were added (deadline during calibration, `P ≤ MIN_SAMPLES`). §6F measures the real `eval7` cost/value correlation. |

### Round 4: 2026-11-11 (Codex: 1 bug; accepted, fixed in round 5)
| Bug | Severity | Finding (Codex) | Resolution (Claude) |
|---|---|---|---|
| B1 | minor | The claim "1.2× ratio: \|bias\| ≤ 1e-5 at every B" is false. With costs 1 and 1.2 and B = 70.4, the 64-sample checkpoint splits K at its mean, and the expected result is 0.4917211 (bias −0.0082789); B = 70 gives −0.00686. Correct the bound, add budgets near the checkpoint transitions to the exact calculation and the tests, and state the verified range. (This stays within the 0.01 allowance, so no redesign is needed.) The selection-bias fix was confirmed. | **fixed:** my round 3 numbers came from a handful of budgets that missed the transitions. §3.3 *Bias* now has: (1) an exact decomposition `E[m_N] − μ = Σ_j 32/(n_j+32) · E[1{N>n_j}(μ − m_{n_j})]` and a **per-checkpoint cap** `32/((n_j+32)·4√n_j)` that holds for any values and any stopping rule (0.0104 at 64 samples, 0.0033 at 160, 0.00025 at 1,000); (2) the observation that a deadline rule makes `{N > n_j}` = `{C(n_j) < B}`, so only transition checkpoints contribute; (3) a closed-form scan, validated against a brute-force DP and reproducing Codex's −0.0082789. It covers p ∈ {0.1, 0.3, 0.5}, ratios 1.05–3 in both directions, and every budget on a fine grid up to 1,400–4,000 samples. The sup is 0.0083 at the 64-sample transition **for every ratio**: the ratio only narrows the budget window. A table gives the sup by minimum sample count. The claim is now "≤ the cap at the first checkpoint, ≤ 17% of the standard error at any sample count" (§3.3, §8.5). §6B9 places budgets exactly on the 64- and 160-sample transitions for ratios 1.2 (including Codex's B = 70.4) and 2, and checks the empirical mean against an in-test closed-form predictor (itself checked against a DP) and the cap. `bench_equity.py --bias` reproduces the scan, and §6F's ratio measurement is now informational. The round 3 entry is annotated. |

### Round 5: 2026-11-11
_Awaiting Codex review._
