# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## Project

A bot for the **Pokerbots IIITB** competition, playing **Discard Hold'em**: heads-up no-limit
Hold'em where each player gets **3 hole cards** and, after flop betting, both players
**discard one card simultaneously, face up**. Showdown uses the 2 remaining hole cards plus 5 board cards.

- Submission deadline: **15 November 2026, 23:59 IST** (Unstop). Only the last valid upload counts.
- The authoritative specs are in `docs/`. Read them before changing game logic:
  - `docs/problem_statement.pdf`: game rules and worked examples (prevails on game rules)
  - `docs/protocol_specification.pdf`: stdin/stdout JSON protocol, legality rules, error handling
  - `docs/rulebook.pdf`: tournament format, limits, scoring, conduct (prevails on everything else)

## Repository layout

| Path | Purpose | Edit? |
|---|---|---|
| `bot/` | Our submission. `bot/bot.py` is the entry point. | Yes |
| `champion/` | The current BEST bot (`champion/bot/`), its scores (`BEST.json`), promotion history and the gauntlet config. **Changed only by `scripts/promote.py`** | No (only via promote) |
| `scripts/promote.py` | Promotion gate: gauntlet + head-to-head vs champion; on success swaps the champion and rebuilds `dist/submission.zip` | Yes |
| `agents/` | Module interfaces (`INTERFACES.md`, the contract every implementation must match) and the earlier per-feature plans and reviews (design references only; see "Development flow") | Yes (interfaces via the orchestrator) |
| `DEVELOPMENT.md` | Workstreams, promotion gate, daily sequence. Its plan review loop is superseded by "Development flow" below | Yes |
| `strategies/` | Strategy catalogue: one file per area, with priorities (P0–P3), specs and status. **The spec that gets reviewed and implemented**; update the `Status:` lines as ideas are built | Yes |
| `scripts/build.py` | Validates `bot/` (imports, stray stdout prints) and builds `dist/submission.zip` | Yes |
| `tests/` | pytest: protocol tests (bot as subprocess) + a seeded engine match | Yes |
| `requirements*.txt`, `pyproject.toml` | Pinned deps (runtime: numpy, scipy; dev: pytest) and pytest config | Yes |
| `tests/*_bot.py` | Our own sparring bots (`shove_bot`, `station_bot`, `nit_bot`, `maniac_bot`, `potodds_bot`, `tag_bot`, `minraise_bot`, `checkraise_bot`, `sizetell_bot`, `overbet_bot`; the last five share `tests/_sparring.py`), stdlib only, used by `scripts/arena.py` | Yes |
| `starter_kit/` | Organiser-supplied `engine.py`, reference `bot.py`, `example_bots/random_bot.py` | **No.** Treat as read-only vendor code |
| `docs/` | Official PDFs | No |
| `logs/` | Engine output (gitignored) | Generated |
| `dist/` | Built submission zips (gitignored) | Generated |
| `.downloads/` | Original organiser zip (gitignored) | No |

If the organisers publish a corrected starter kit, replace `starter_kit/` wholesale. Don't patch it.

## Commands

Environment: a uv-managed Python 3.11 venv at `.venv/`. The `py -3.11` launcher does **not**
find the uv-installed interpreter on this machine. Use `.venv/Scripts/python.exe` (or activate the venv).

```bash
# One-time setup (recreate the venv)
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt

# Tests, then validate + package the submission
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe scripts/build.py            # -> dist/submission.zip
.venv/Scripts/python.exe scripts/build.py --check    # validate only
```

Engine runs (the examples use `python3.11`; with the venv active, `python` works too):

```bash
# Stage 1 match (2 legs x 200 hands) vs the random bot
python3.11 starter_kit/engine.py bot/bot.py starter_kit/example_bots/random_bot.py

# Reproducible, quick
python3.11 starter_kit/engine.py bot/bot.py starter_kit/example_bots/random_bot.py --hands 40 --seed 1

# Stage 2 timing check (2 legs x 500 hands, 75 s bank per leg)
python3.11 starter_kit/engine.py bot/bot.py starter_kit/example_bots/random_bot.py --stage 2

# Bots using the venv's numpy/scipy
python3.11 starter_kit/engine.py bot/bot.py starter_kit/example_bots/random_bot.py --python .venv/Scripts/python.exe
```

Engine flags: `--stage 1|2`, `--hands N` (even), `--seed S`, `--verbose`, `--log-dir DIR` (`''` disables),
`--python PATH`, `--no-time-limits` (debugging only; never use it to judge timing).

## Hard constraints on the bot (violating any of these loses matches)

1. **Python 3.11, stdlib + numpy + scipy only.** No other imports in anything under `bot/`.
   Dev-only tools (pytest, etc.) must never be imported by bot code.
2. **stdout is protocol-only.** Every reply is exactly one JSON line, flushed
   (`print(json.dumps(msg), flush=True)  # protocol`). The `# protocol` marker is required:
   `scripts/build.py` rejects every other `print()` that lacks `file=`. Any other stdout output while a request is pending is
   taken as the reply, so it becomes a malformed reply and the real one is ignored.
   **All debug output goes to `sys.stderr`** (capped at 64 KB per leg, so keep it terse).
3. **Never crash, never hang.** A crash, EOF on stdout, a reply over 5 s, an exhausted time bank or
   the wall-clock kill **forfeits the entire match** (scored as −400 in Stage 1, −1000 in Stage 2).
   Wrap strategy code so any exception falls back to a safe legal action (check if legal, else
   call/fold per a conservative rule) and a safe discard.
4. **Time budget.** The bank is 30 s per leg for 200 hands (Stage 1) and 75 s per leg for 500 hands (Stage 2),
   about **150 ms per hand** on average across all decisions. The judge has 1 vCPU and is likely slower than
   dev machines, so aim to use **≤ 40% of the bank** locally. Budget dynamically from
   `time_left_ms` in every request. Heavy precomputation belongs at start-up (5 s uncharged) or
   shipped as data files.
5. **Resources and sandbox.** 1 GB RAM, read-only filesystem, no network, no subprocesses, no
   threads that outlive a reply. The bot may *read* files inside its own submission (resolve paths
   relative to `__file__`), never write.
6. **Submission format.** A single `bot.py`, or a `.zip` with `bot.py` at its top level, **≤ 5 MB**.
7. **No cross-leg state.** Each leg is a fresh process. State may persist across hands *within* a leg
   only. Do not attempt to detect duplicate deals or pass information between legs (Rulebook 10.3).
8. **Exit after `match_end`.**

## Protocol cheat-sheet

- Engine to bot: `init`, `new_hand`, `action_request`, `discard_request`, `discard_result`,
  `hand_result`, `notice`, `match_end`. **Ignore unknown types and fields.**
- Reply only to `action_request` (with `{"type":"action","action":...}`) and `discard_request`
  (with `{"type":"discard","card":"Kd"}`).
- Cards are rank+suit strings: ranks `23456789TJQKA`, suits `shdc`.
- Raise amounts are **"to" amounts** (total committed on this street), with
  `min_raise <= amount <= max_raise`. An opening bet is sent as `raise`.
- **Always choose from `legal_actions`.** `raise` may be absent even when `raises_left > 0`
  (opponent all-in). Clamp amounts to `[min_raise, max_raise]` and send ints.
- The discard still happens when players are all-in. In that case there are no further action requests.
- A `notice` means the engine corrected us. Any notice in a local run is a bug to fix.

## Strategy-relevant facts

- Stacks reset to 200 every hand. There is no stack management across hands; each hand is independent.
- Scoring is **net chips over both legs** (win/draw/loss), tie-broken by capped chips per hand.
  Duplicate deals cancel card luck, so edges come from decisions, not variance.
- The opponent's exposed discard is information about which two cards they kept. Ours leaks
  information too.
- The 4-bets-per-street cap means preflop allows at most 3 voluntary raises after the big blind.
- Reusing code from `starter_kit/` (e.g. its hand evaluator) is explicitly allowed. **Copying
  from public pokerbot repositories or other teams is prohibited** (Rulebook 10.1). Implement
  published algorithms ourselves.

## Coding conventions

- Keep `bot/bot.py` a thin protocol loop. Put logic in separate modules under `bot/`
  (e.g. `cards.py`, `evaluator.py`, `equity.py`, `strategy.py`, `discard.py`), all stdlib/numpy/scipy.
- Pure functions for evaluation and decisions so they are unit-testable without the engine.
- Use fixed seeds for any randomness in tests. Randomness in live play is allowed.
- Prefer speed-conscious code in hot paths (hand evaluation, Monte Carlo). Measure before
  optimising, and measure on `--stage 2`.
- Don't add dependencies, build systems or frameworks beyond what is needed.

## Definition of done for any bot change

1. A full Stage 1 match vs `random_bot.py` completes with **0 notices** and no forfeit.
2. A `--stage 2` run stays well inside the time bank (check "time used" in the summary).
3. `python -m pytest` passes.
4. `python scripts/build.py` passes (allowed imports only, no stray stdout prints, ≤ 5 MB).
5. If the change is meant to improve strength, show results over many seeds against the
   previous version, not a single match.

## Development flow

Every implementing agent follows this protocol for every task:
1. **Restate the brief:** files you may touch, `strategies/` item IDs, measurable goal.
2. **Solve** it yourself; implementing subagents do not spawn further subagents.
3. **Check two ways** (e.g. evaluator vs engine `best_hand` + edge cases; Monte Carlo vs exact enumeration).
4. **Measure:** `pytest`, `scripts/build.py --check`, `scripts/arena.py`, `scripts/promote.py --dry-run`.
5. **Raise BEST only by winning:** `scripts/promote.py --note "..."`. Never edit `champion/` or
   `dist/submission.zip` by hand. Only the champion's zip is ever uploaded.
6. **Record:** update `Status:` lines in `strategies/`; commit on your workstream branch.

**Every strategy area follows the fix → review → fix → implement loop** (since Fri 13 Nov; it replaces the
per-feature plan loop in `agents/README.md`, which was too slow for the time left). The strategy file
`strategies/NN_*.md` is the spec; there is no separate plan document.

1. **Orchestrator (Claude Code, main session)** reads the strategy file and fixes its bugs: wrong rule facts
   (checked against `starter_kit/engine.py`), wrong arithmetic, contradictions with other strategy files, with
   `agents/INTERFACES.md` or with the code already in `bot/`. Numeric claims are recomputed or simulated.
2. **Codex reviews the fixed file once**: `codex exec`, model `gpt-6.1-sol`, reasoning effort `high`, read-only
   sandbox, one strategy file per call, reply = a numbered bug list ending in a `VERDICT:` line. (`gpt-6-astra`
   is no longer used: it burns the usage limit.) If Codex is rate-limited, wait for the reset; do not skip the
   review.
3. **Orchestrator fixes** every reported bug in the strategy file, or rejects it with a reason that can be
   checked (a rule, an engine line, a measurement). One review round, not a loop until clean.
4. **An Opus 5.5 subagent (effort `high`) implements** that strategy area in `bot/` from the corrected file,
   one area at a time in dependency order: 02 → 03 → 04 → 05 → 06 → 07 → 08. Subagents work in the main
   checkout, never in parallel on `bot/`, leave their work uncommitted, and report signatures, test results,
   measured speeds and every deviation from the spec.
5. **Orchestrator verifies** the report against the definition of done above before starting the next area.

**No code for a strategy area before step 3 is finished for it.** Files 00 and 09 are reference only (nothing
to implement). The earlier feature plans in `agents/plans/` stay as design references (F02 for the evaluator
and equity, F03 for the sparring bots); where a plan and its strategy file disagree, the strategy file wins.
Real promotions happen only from committed code on `main` (`promote.py` refuses otherwise).
Commits carry no AI co-author or attribution trailers.

## Sparring bots

- We test only against bots we may rely on: `random` and `starter` (organiser kit), `champion` (the frozen
  champion) and **our own sparring bots** in `tests/` (`shove_bot.py`, `station_bot.py`, `nit_bot.py`,
  `maniac_bot.py`, `potodds_bot.py`, and the style bots `tag_bot.py`, `minraise_bot.py`, `checkraise_bot.py`,
  `sizetell_bot.py`, `overbet_bot.py`; add more there, stdlib only). `scripts/arena.py` runs them (many seeds, W-D-L,
  chips/hand ± SE); with no `--opps` it uses that whole pool.
- **The MIT Pokerbots 2026 bots were removed from the repo on Fri 13 Nov** (the `rivals/` directory, its adapter
  and its separate virtualenv). They were written for a different game and only played ours through an adapter,
  so results against them were unreliable. Do not re-add third-party bots.
- **Never copy code from public pokerbot repositories or other teams into `bot/`** (Rulebook 10.1; organisers
  run similarity checks). `strategies/09_rival_lessons.md` keeps ideas taken from READMEs only.

## Git

- Default branch `main`. Work on feature branches; commit only when asked.
- Never commit `logs/`, `dist/`, `.venv/`, or `.downloads/`.
- Keep `starter_kit/` and `docs/` byte-identical to the organiser versions.
