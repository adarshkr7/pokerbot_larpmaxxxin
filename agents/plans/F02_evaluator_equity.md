# F02: Cards, evaluator, equity (scalar)

**Status:** in review (round 1)
**Workstream:** W2 · **Strategy items:** 02/E1, 02/E3, 02/E4 (`canon3` only) · **Owner:** Claude (implements) · **Reviewer:** Codex

## 1. Goal
A pure-Python library that later features (F04 discard, F05/F06 betting) call for hand strength and equity:
`eval7` orders every 5–7-card hand **exactly as the engine's `best_hand` does** at ≥ 250k evals/s, and `equity`
returns a budget-bounded estimate of win + tie/2 against a weighted opponent range that is **unbiased** (exact on the
river when the budget allows) and agrees with exact enumeration within 4 standard errors. **No bot behaviour change.**

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
- `equity.py`: `equity(...)` and `canon3(...)` as in the contract, plus two new functions for common random
  numbers: `deal_samples(board, opp_weights, dead, n, rng) -> list[tuple]` and
  `equity_vs_samples(hero2, board, samples) -> float`.
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

**Range preparation** `_range(opp_weights, X) -> (pairs, cum, total)`: every pair `(a, b)` with neither card in `X`,
weight `w = float(weight)`; non-finite or negative weights count as 0; pairs with `w = 0` are dropped. If nothing is
left (all weights 0 or all pairs blocked), fall back to **uniform over the valid pairs** and log a warning once. If no
valid pair exists at all (impossible with ≤ 10 excluded cards), `equity` returns `(0.5, 0.0)`. `cum` is the running
sum for weighted sampling (`bisect` on `rng.random() * total`).

**Showdown value** `v(hero, opp) = 1` if `hero > opp`, `0.5` if equal, else `0`, from `eval7` on the full 7 cards.

**River (`len(board) == 5`): exact weighted enumeration.** Hero's value is evaluated once. The valid pairs (≤ 903
in a real hand: 52 − 3 − 5 − 1 = 43 cards) are visited in a random order (`rng.shuffle` of the index list), and the
estimate is `Σ w·v / Σ w` over the pairs visited. If the budget runs out first (checked every `CHECK_EVERY` pairs,
never before `MIN_SAMPLES` pairs), the result is that weighted average over a uniformly random subset: still unbiased
for uniform weights and consistent otherwise. Typical full cost: 903 evals ≈ 3–4 ms. `n_eff = (Σw)² / Σw²` over the
visited pairs (= the count for a uniform range).

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

**Budget.** `deadline = perf_counter() + budget_ms / 1000`, checked every `CHECK_EVERY` samples. At least
`MIN_SAMPLES` samples are always taken (even with `budget_ms <= 0`, so a panic-tier caller still gets a usable
answer for ≈ 0.3 ms), and at most `MAX_SAMPLES`. Overshoot is at most `CHECK_EVERY` samples (≈ 0.2 ms).

**Common random numbers (for F04's keep comparison).**
- `deal_samples(board, opp_weights, dead, n, rng)`: `n` samples `(opp_pair, runout)` drawn exactly as above, with
  `X = dead ∪ board` (no hero cards: for our own discard, `dead` already holds all 3 of our hole cards).
- `equity_vs_samples(hero2, board, samples)`: the mean showdown value of `hero2` over those samples (runout cache as
  above). Calling it for each of our 3 candidate keeps on the same samples gives low-noise *differences*.
- No budget inside: the caller sizes `n` (e.g. from a timed first batch). Returns 0.5 for an empty sample list.

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
`MIN_SAMPLES = 64`, `MAX_SAMPLES = 20000`, `CHECK_EVERY = 32`.

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
10. Duplicate or out-of-range ids passed by a caller → not validated in `eval7` (hot path); `equity` builds its
    excluded set itself and never deals a card twice. Documented as a caller contract.
11. `budget_ms` 0, negative or NaN → `MIN_SAMPLES`; huge → capped by `MAX_SAMPLES` (and by exhaustion on the river).
12. `rng=None` → module default generator; tests always pass a seeded `random.Random`.

## 5. Failure handling and time
- All functions are pure; nothing touches stdout or files. They can raise only on caller contract violations (e.g.
  a hero card id of 52). Callers in F04+ run inside the F01 firewall, which falls back on any exception.
- Time per `equity` call is bounded by `budget_ms` plus one `CHECK_EVERY` block, with a floor of `MIN_SAMPLES`
  (≈ 0.3 ms) and a ceiling of `MAX_SAMPLES` (≈ 100 ms at worst; callers pass budgets ≤ 400 ms per the F01 clock).
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
   `engine.best_hand` (different evaluator, different loop). Uniform and non-uniform weights; equal within 1e-12.
2. *Turn MC vs exact:* exact = full enumeration of (pair, river) with weights, computed in the test. MC with a large
   budget (≥ 8,000 samples): `|mc − exact| ≤ 4 · sqrt(p(1−p)/n)`. Uniform range and a 3-pair range.
3. *Flop MC vs exact on a small range:* opponent range of 3 pairs, exact = all pairs × all C(45, 2) runouts. Same
   4-SE tolerance.
4. *Sampling hygiene:* over 20,000 `deal_samples`, no dealt card is in `dead ∪ board`, no card repeats within a
   sample, and pair frequencies match the weights (chi-square, p > 0.001, seeded).
5. *Weights formats:* `None`, a 1,326 list, a dict, and a numpy array give identical results with the same seed;
   NaN / negative / all-zero / fully blocked ranges fall back to uniform.
6. *CRN:* `equity_vs_samples` on the same samples is deterministic, and for a dominated keep (e.g. 72o vs AA on
   a low board) the difference has the expected sign.
7. *Budget:* `budget_ms = 0` → exactly `MIN_SAMPLES` on the turn; a 5 ms budget returns within 5 ms +
   2 ms slack and `n ≥ MIN_SAMPLES`; `MAX_SAMPLES` caps a huge budget; river with a huge budget visits every pair.

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

## 7. Acceptance criteria
- [ ] §6A–D pass; `pytest` green; `scripts/build.py --check` passes.
- [ ] `eval7` ≥ 250k evals/s locally; equity throughput recorded.
- [ ] §6E: head-to-head vs v0 exactly 0, no notices, no forfeits.
- [ ] `agents/INTERFACES.md` updated with the §2 changes; `strategies/02_*` E1, E3, E4 `Status:` lines updated.

## 8. Risks and open questions (for the reviewer)
1. **Monte Carlo vs exact on the turn.** Chosen: joint sampling with a hero cache (unbiased, best variance per eval).
   The alternative (enumerate rivers for the top-K pairs) is biased by the truncation.
2. **River partial enumeration** with a non-uniform range: the weighted average over a random subset is consistent
   but slightly biased (ratio estimator) for small subsets. Acceptable: a full river enumeration costs ~3–4 ms,
   so partial results occur only in the throttle/panic tiers.
3. **3-card hero equity** (flop betting before the discard) is not in F02. F04/F06 will compose it from
   `deal_samples` + `equity_vs_samples` (max over the 3 keeps on common samples), so no new primitive is needed.
4. **`eval_batch` deferred** to F08; scalar speed (~300k evals/s ≈ 200 samples/ms) supports ~4,000 samples in a
   20 ms decision, ±0.8 points standard error.

## Review log
### Round 1: 2026-11-11
_Awaiting Codex review._
