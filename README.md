# Pokerbots IIITB — Discard Hold'em bot

Submission deadline: **15 November 2026, 23:59 IST** (upload on Unstop).

| Path | What |
|---|---|
| `bot/bot.py` | Our submission (currently the starter strategy) |
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
