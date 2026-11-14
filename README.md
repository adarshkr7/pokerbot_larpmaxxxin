# Pokerbots — Discard Hold'em bot

Submission deadline: **15 November 2026, 23:59 IST**.

## Submission

**The submitted bot is `champion/bot/`** (its `bot.py` is the entry point, at the top level of that folder).
The submitted file is `submission.zip`: exactly the contents of `champion/bot/`, with `bot.py` at the zip's top
level. `scripts/promote.py` rebuilds it on every promotion; to rebuild it by hand:

    python scripts/build.py --src champion/bot          # -> dist/submission.zip

Run the submitted bot with the organiser engine:

    python3.11 starter_kit/engine.py champion/bot/bot.py starter_kit/example_bots/random_bot.py

`bot/` is our development copy; it becomes the champion only through `scripts/promote.py` (see `AGENTS.md`).
`champion/BEST.json` and `champion/history.jsonl` record which commit each champion version came from.

| Path | What |
|---|---|
| `champion/bot/` | **The submitted bot** (entry point `champion/bot/bot.py`) |
| `bot/` | Development copy of the bot (promoted to `champion/` when it beats the champion) |
| `starter_kit/` | Organiser-supplied engine, starter bot, random bot (do not edit) |
| `docs/` | Rulebook, Problem Statement, Protocol Specification |

## Setup

    uv venv --python 3.11 .venv
    uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
    .venv/Scripts/python.exe -m pytest
    .venv/Scripts/python.exe scripts/build.py     # validate + build dist/submission.zip

See `AGENTS.md` for the full working rules.

## Run a local match

    python3.11 starter_kit/engine.py bot/bot.py starter_kit/example_bots/random_bot.py
    python3.11 starter_kit/engine.py bot/bot.py starter_kit/example_bots/random_bot.py --stage 2

Logs go to `logs/` (gitignored). Debug output must go to stderr, never stdout.

## Hard constraints

- Python 3.11, stdlib + numpy + scipy only; single `bot.py` or zip with `bot.py` at top level, ≤ 5 MB
- 1 vCPU, 1 GB RAM, read-only FS, no network, no subprocesses
- Time bank 30 s/leg (Stage 1, 200 hands), 75 s/leg (Stage 2, 500 hands); 5 s per reply

## How we work

- [DEVELOPMENT.md](DEVELOPMENT.md): the development flow, promotion
  gate, daily sequence Wed 11 → Sun 15 Nov.
- [agents/](agents/): the agentic loop with **Claude Code + Codex**: roles, worktrees, module interfaces,
  workstream briefs W1–W7, review and coordinator prompts.
- [strategies/](strategies/): the strategy catalogue (P0–P3) plus the Gemini and GPT-astra research digests.
- [champion/](champion/): the current best bot (`BEST.json`), changed only by `scripts/promote.py`.
  `dist/submission.zip` is always built from it. **Upload only that.**
