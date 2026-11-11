# F03: Deterministic sparring bots + gauntlet

**Status:** in review (round 1)
**Workstream:** W7 · **Strategy items:** 08/T1 (archetype bots), 08/T3 (deterministic comparison) · **Owner:** Claude (implements) · **Reviewer:** Codex

## 1. Goal
Seven deterministic archetype bots (our own code) that play legally, never forfeit, and give **bit-identical match
logs when re-run with the same seed**, added to the promotion gauntlet in place of the unseeded `random_bot`, so that
`promote.py` measures a candidate against the expected field with no noise from the opponents themselves.
**No change to `bot/`.**

## 2. Scope
**In:** `scripts/sparring/_common.py` (shared protocol loop, legality clamp, state, evaluator, equity),
`scripts/sparring/{maniac,nit_threshold,nit_threshold_tight,min_click,linear_sizing,lag,switcher,always_fold}.py`,
`scripts/arena.py` (opponent lookup), `scripts/promote.py` (gauntlet hash covers opponent code; default opponent list),
`champion/gauntlet.json` (opponent list only, with coordinator approval as the W7 brief allows),
`tests/test_sparring.py`, `tests/engine_util.py` (shared `deterministic_view`), `strategies/08_*` status.
**Out:** anything under `bot/`; rival bots (`rivals/` stays as is); new statistics in `promote.py` (08/T3 bootstrap is
a later feature).

**Not built from the brief's list:** `station.py`. As specified (check if free, else call; toss lowest rank) it is
exactly the kit's `starter` bot, which stays in the gauntlet. A separate copy would only double-count it.

**Interface changes:** none to `agents/INTERFACES.md` (no `bot/` module changes). Tool changes:
- `arena.resolve(name)` lookup order becomes: builtin (`random`, `starter`) → **sparring** (`scripts/sparring/<name>.py`,
  names not starting with `_`) → rival (`rivals/<name>/bot.py`) → path. A test asserts no sparring name collides with
  a builtin or a registered rival.
- `promote.gauntlet_hash(g)` also covers the **code** of every opponent (§3.6).

## 3. Design

### 3.1 Independence and freezing
Sparring bots must not import anything from `bot/`: the candidate's code changes between runs, and a shared module
would let a candidate change its own opponents. They import only the stdlib and `_common.py` (in the same folder;
the engine starts each bot with `cwd` = its folder and the script's folder on `sys.path`). They must run under any
Python 3.11 the arena uses (`promote.py` uses `.venv-rivals` when it exists), so **stdlib only, no numpy**.
`_common.py` contains its own small 7-card evaluator (re-typed from our research prototype
`research/bench_discard.py`, our own code), validated against `engine.best_hand` in §6A, so the sparring bots stay
fixed even when `bot/evaluator.py` changes.

### 3.2 `_common.py`: protocol loop and state
`run(policy)` where `policy` has `act(req, st, rng) -> (action, amount_or_None)` and `discard(req, st, rng) -> card`.
- Reads stdin line by line (`errors="replace"`), ignores malformed JSON, non-dicts, unknown types; replies only to
  `action_request` and `discard_request`, exactly once each, as one JSON line with `flush=True`; exits on
  `match_end` or EOF. Never writes anything else to stdout.
- State `st`: `NAME`, `hand_id`, `seat`, `hole` (3 strings from `new_hand`, replaced by `discard_request.hole_cards`
  and then by the 2 kept cards from `discard_result`), `opp_discard`, `board` (from each request).
- **Firewall:** the policy call is wrapped in `try`; on any exception the intent is `check`-else-`fold` / the
  toss-lowest discard. Every intent goes through `legalize(intent, req)`: the same mapping table as F01's
  `make_legal` (raise → clamp to `[min_raise, max_raise]`, or call/check if raise is illegal; call → check if not
  legal; check → fold if not legal; fold → check if free), re-implemented here (no `bot/` import). Discards not in
  the hole cards become the toss-lowest card.
- **Determinism:** every decision gets a fresh `random.Random(seed_str)`, where
  `seed_str = f"{NAME}|{hand_id}|{street}|{len(history)}|{' '.join(hole)}|{' '.join(board)}"` (for discards,
  `street = "discard"`). `random.Random(str)` seeds deterministically (SHA-512 of the string, unaffected by
  `PYTHONHASHSEED`). So a bot's choice depends only on what it has seen, the same seed and deal give the same play,
  and leg 2 (swapped cards) is still deterministic. No wall-clock, `id()` or set-ordering input reaches a decision.

### 3.3 `_common.py`: helpers
- `toss_lowest(hole)`: the engine's `default_discard` rule (lowest rank, ties `s < h < d < c`).
- `eval7(cards)`: same encoding as F02's plan (category << 20 | 5 rank nibbles), on card strings converted to ints.
- `category(cards)`: `eval7(cards) >> 20`.
- `equity(st, req, n=200)`: our expected keep vs a **uniformly random** opponent 2-card hand, Monte Carlo with `n`
  samples, seeded from the decision seed. Keep = `st.hole` if it has 2 cards, else `st.hole` minus `toss_lowest`.
  Excluded cards: all our hole cards seen this hand (original 3), the board, `opp_discard` if known. Each sample
  draws the opponent's 2 cards and the missing board cards from the rest; value 1 / 0.5 / 0.
  Cached per `(hand_id, street)` within a process, so each bot computes at most 4 equities per hand
  (≈ 0.4 ms each at ~300k evals/s).
- `raise_to(req, f)`: `opp_bet + max(2, round(f * (pot + to_call)))`, clamped to `[min_raise, max_raise]` (a bet of
  fraction `f` of the pot after calling).

### 3.4 The bots (each a ~20–40 line file: `NAME`, `act`, `discard`, `run(...)`)
"Facing" means `to_call > 0`. `r` is `rng.random()`. All sizes go through `legalize`.

| Bot | `act` | `discard` |
|---|---|---|
| `maniac` | If raise is legal and `r < 0.7`: raise — size by a second draw: `< 0.5` → `min_raise`, `< 0.8` → `raise_to(1.0)`, else `max_raise` (all-in). Otherwise call if facing, else check. Never folds. | uniformly random card |
| `nit_threshold` | `e = equity`. Facing: `e < 0.48` fold, `e < 0.68` call, else raise `raise_to(0.5)`. Not facing: `e ≥ 0.68` → `raise_to(0.5)`, else check. | toss lowest |
| `nit_threshold_tight` | Same with thresholds 0.55 / 0.75 (imports `nit_threshold`'s policy with other constants). | toss lowest |
| `min_click` | Raise to `min_raise` whenever raise is legal; else call if facing, else check. | toss lowest |
| `linear_sizing` | `e = equity`. Not facing: `e ≥ 0.55` → `raise_to(f)` with `f = clamp(4·(e − 0.5), 0.25, 2.0)`, else check. Facing: `e ≥ 0.70` → `raise_to(f)`; else call iff `e ≥ to_call / (pot + to_call) + 0.05`; else fold. | toss lowest |
| `lag` | Preflop facing: `r < 0.25` fold, `r < 0.60` `raise_to(1.0)`, else call. Preflop not facing: `r < 0.5` `raise_to(1.0)`, else check. Postflop not facing: `r < 0.65` `raise_to(0.66)` (barrel), else check. Postflop facing: `e ≥ 0.55` and `r < 0.3` → `raise_to(0.75)`; elif `e ≥ 0.30` or `r < 0.3` → call; else fold. | **deceptive:** for each of the 3 discards, `category(keep + flop)`; if any keep makes two pair or better, toss the **highest** card among those discards (by rank, then suit `c > d > h > s`); else toss lowest |
| `switcher` | `hand_id ≤ 100`: check if free, else call (the starter style). `hand_id > 100`: the `maniac` policy. Per leg (hand ids restart in leg 2). | ≤ 100: toss lowest; > 100: maniac's |
| `always_fold` | Check if free, else fold. | toss lowest |

### 3.5 `arena.py`
`SPARRING = ROOT / "scripts" / "sparring"`; `resolve` gains the sparring step (§2). `all_rivals()` is unchanged (it
lists rivals only). The module docstring lists the sparring names.

### 3.6 `promote.py`: the gauntlet hash covers opponent code
Today the champion's cached gauntlet score is keyed by `(stage, hands, seeds, opponent names)`. If an opponent's code
changes, the cache is silently stale and the candidate is compared with an outdated champion score. New:
`gauntlet_hash(g)` also includes, for each opponent in order, a SHA-1 over the sorted `(name, bytes)` of every
`*.py` file in the **opponent's own folder** (non-recursive): `scripts/sparring/` for sparring bots (covers
`_common.py`), `starter_kit/` for `starter` (covers `engine.py`), `starter_kit/example_bots/` for `random`,
`rivals/<name>/` for rivals. Changing any of these files re-measures the champion on the next run. (This also
changes v0's hash once, so the champion is re-measured on the first run after F03, as it would be anyway because
the opponent list changes.)
`DEFAULT_GAUNTLET["opponents"]` is updated to the new list (used only if `gauntlet.json` is missing).

### 3.7 The new gauntlet
`champion/gauntlet.json` `opponents`: `["starter", "maniac", "nit_threshold", "nit_threshold_tight", "min_click",
"linear_sizing", "lag", "switcher", "always_fold"]`. `random` is **removed** from the gauntlet (unseeded, so its
results vary run to run) but stays available for `arena.py` smoke runs. Seeds, hands, stage, `min_z`,
`max_bank_share`, `jobs` and `h2h_seeds` are unchanged. This is an edit to one field of `champion/gauntlet.json`,
approved by the coordinator through this plan (W7 brief: "champion/gauntlet.json (opponent list only, coordinator
approval)"); `BEST.json`, `history.jsonl` and `champion/bot/` are not touched. Size: 9 × 12 = 108 matches per side,
each ~1 s, run 5 in parallel.

## 4. Edge cases
1. Raise not in `legal_actions` while `raises_left > 0` (opponent all-in) → `legalize` maps raise to call.
2. Short all-in (`min_raise == max_raise`) → the clamp gives that amount.
3. Preflop all-in → no further action requests; the discard request still arrives; the discard rules use
   `discard_request.hole_cards` and `board`.
4. `lag` discard when two or three discards make two pair+ → highest card among those discards; when none → lowest.
5. `switcher` in Stage 2 (500 hands per leg) → still switches at hand 101 of each leg.
6. `equity` with `opp_discard` unknown (flop, before the discard) → excluded set without it.
7. `pot + to_call` small (preflop) → `raise_to` at least `opp_bet + 2`, then clamped.
8. A policy exception → firewall fallback, logged to stderr (terse, at most 20 lines per process).
9. Messages the bot does not expect (notice, unknown types) → ignored; a `notice` is logged to stderr.

## 5. Failure handling and time
- Every reply goes through the firewall and `legalize`; there is no code path to stdout except the reply line.
- Time: at most 4 equities of 200 samples per hand (~2 ms per hand) plus parsing; ~0.4 s per 200-hand leg. Limit for
  §6C: each sparring bot's engine-reported time in a Stage 2 `--jobs 1` run must be ≤ 10% of the bank (≤ 15 s summed
  over both legs). A forfeit by a sparring bot would award us +cap and corrupt the gauntlet, so §6C also asserts 0
  forfeits for both sides in every run.

## 6. Tests (check two ways), `tests/test_sparring.py`
**A. Building blocks.**
1. `_common.eval7` vs `engine.best_hand` on 30,000 random head-to-head showdowns (sign of the comparison), plus the
   wheel / flush-vs-straight / board-tie cases.
2. `legalize` vs `engine.parse_action` on the F01 request generator (`tests/test_legal.py::gen_request`, reused) ×
   a set of intents including out-of-range and illegal ones: every reply passes with no error code.
3. `toss_lowest` equals `engine.default_discard` on 5,000 random hands.
4. `equity` sanity: AA-keep on a dry board ≫ 72o-keep (e.g. > 0.8 vs < 0.4); same seed string → same value.

**B. Policies as pure functions** (each bot module is importable; `act`/`discard` called on generated requests, with
`equity` replaced by a stub returning a chosen value):
1. `maniac`: over 5,000 requests with raise legal, raise frequency 0.70 ± 0.03, size split 50/30/20 ± 4 points;
   never folds.
2. `nit_threshold` / `_tight`: the decision table at e = 0.47, 0.48, 0.67, 0.68 (and 0.54/0.55, 0.74/0.75), facing and
   not facing.
3. `min_click`: every raise equals `min_raise`.
4. `linear_sizing`: raise size non-decreasing in `e`; the pot-odds call rule at its boundary.
5. `lag`: frequencies within ± 0.03 of the table; the deceptive discard on hand-built cases (two pair+ available →
   highest card tossed; none → lowest).
6. `switcher`: hand 100 behaves as starter; hand 101 as maniac on the same request and seed.
7. `always_fold`: never `call` or `raise`.

**C. Engine runs** (via `tests/engine_util.run_match`).
1. Each bot vs `starter`, 400 hands (Stage 1 layout), seed 7: completes, **0 notices for both sides**, 0 forfeits.
2. **Determinism, independent check:** the same match run twice gives identical `deterministic_view(match.log)`
   (moved from `test_engine_runs.py` into `engine_util.py` so both tests share it). Also each bot vs our `bot/bot.py`
   (deterministic v0) twice → identical.
3. Protocol: each bot as a subprocess on a scripted stdin (init, new_hand, requests, an unknown message, a notice,
   match_end) → exactly one legal reply per request, exit 0; and exit 0 on EOF without `match_end`.
4. Timing (not in `pytest`; run once and recorded in the review log): `scripts/arena.py --bot <sparring bot>
   --rivals starter --stage 2 --seeds 2 --jobs 1` for each bot: time used ≤ 15 s, 0 notices, 0 forfeits.

**D. Tooling.**
1. `arena.resolve` returns `scripts/sparring/<name>.py` for each sparring name; no sparring name equals a builtin or
   a key in `rivals/rivals.json`; `_common` is not resolvable as an opponent.
2. `gauntlet_hash` changes when one byte of `scripts/sparring/_common.py` changes (test on a temp copy of the hash
   function's inputs, not by editing the real file), and is stable otherwise.

**E. Gauntlet re-measure.** `promote.py --dry-run` on the new gauntlet: v0 (champion) and the unchanged `bot/`
both re-measured, 0 notices, 0 forfeits for every opponent; head-to-head exactly 0 (no promotion, as expected).
Points and capped/hand per opponent for v0 recorded in the review log as the new baseline.

## 7. Acceptance criteria
- [ ] §6A–D pass; `pytest` green; `scripts/build.py --check` passes (no `bot/` change).
- [ ] §6C4 timing recorded for every sparring bot (≤ 15 s, 0 notices, 0 forfeits).
- [ ] §6E done: the new gauntlet runs clean; v0 baseline recorded.
- [ ] `champion/gauntlet.json` has the new opponent list and nothing else changed under `champion/`.
- [ ] `strategies/08_testing_and_tuning.md` T1 `Status:` updated.

## 8. Risks and open questions (for the reviewer)
1. **Dropping `random` from the gauntlet** removes the only opponent that plays arbitrary legal sequences. Our own
   robustness is covered by F01's chaos tests and fuzzers; `maniac` and `lag` cover aggression. Alternative: a
   seeded random bot. Chosen: drop it (fewer, more realistic opponents).
2. **A duplicated evaluator** in `_common.py` (vs F02's `bot/evaluator.py`). Deliberate: the opponents must not change
   when the candidate does. Both are checked against the engine.
3. **Gauntlet weighting:** every opponent counts equally in points. Some (always_fold, min_click) are easy wins and
   carry little information; they still catch regressions (e.g. a bot that folds too much to min-raises).
4. **Not a model of real opponents.** These are caricatures with fixed rules; rival bots (`rivals/`) remain the more
   realistic sparring and can be added to the gauntlet later (they need `.venv-rivals`).

## Review log
### Round 1: 2026-11-11
_Awaiting Codex review._
