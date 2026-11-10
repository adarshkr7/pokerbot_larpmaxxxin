# W2: Cards, evaluator, equity

**Plans + implements:** Claude · **Reviews plans:** Codex · **Branch:** `ws/W2` · **Day:** Wed (scalar) → Thu (numpy batches)

## Goal
Fast, verified hand evaluation and equity. Wed: the scalar `eval7` (≥ 250k evals/s locally) and Monte Carlo
`equity`. Thu: `eval_batch` with a measured speed-up in **samples per ms**, including sampling.

## Owns
`bot/cards.py`, `bot/evaluator.py`, `bot/equity.py`, `tests/test_evaluator.py`, `tests/test_equity.py`,
`# --- W2 ---` in `bot/params.py`.

## Interfaces
`cards.py`, `evaluator.py`, `equity.py` (+ `canon3`) per `agents/INTERFACES.md`.

## Strategy items
02/E1, E3 (common random numbers, N_eff, exact river enumeration over ≤ 903 pairs, exact turn → river
enumeration), E2 (numpy batches; Gemini's rank-count + flush-mask design, built correctly), E4 (`canon3`: test
that 22,100 triples map to exactly 1,755 classes).

Start from **our own** prototype `research/bench_discard.py:eval7`.

## Check two ways
1. `eval7` vs the engine's `best_hand` (`starter_kit/engine.py`; reuse is allowed) on ≥ 50k random head-to-head
   showdowns, plus edge cases: wheel, steel wheel, board-only ties, flush vs straight, two full houses.
2. `equity` Monte Carlo vs exact enumeration on river/turn cases; `eval_batch == eval7` row for row.

## Done when
- [ ] both checks pass; benchmarks are recorded in the PR description (evals/s, samples/ms)
- [ ] no bot behaviour change (library only), so it merges without a promotion
