# rivals/: sparring opponents (local only)

Third-party MIT Pokerbots 2026 bots, run under **our** engine through `mit_adapter.py`.
They exist only to test against. **Never import anything here from `bot/`**, never copy their
code into our bot (Rulebook 10.1: copying from public bot repos is prohibited and similarity
checks are run), and never commit `rivals/_src/` or the generated launchers (gitignored).

No official MIT 2026 results are public, so none of these is a confirmed winner. See
`rivals.json` for what each repo claims (e.g. `camello_cfr` = the team's final CFR bot,
`jlam_agent_1_2` = a top-25% team).

## Setup

    uv venv --python 3.11 .venv-rivals
    uv pip install --python .venv-rivals/Scripts/python.exe numpy scipy pkrbot
    .venv/Scripts/python.exe rivals/fetch_rivals.py        # clones into rivals/_src/, writes rivals/<name>/bot.py

## Run matches

    # one match through the official local engine
    python3.11 starter_kit/engine.py bot/bot.py rivals/mit_ref3_monte_carlo/bot.py --python .venv-rivals/Scripts/python.exe

    # many seeds vs many rivals, summarised (logs in logs/arena/)
    .venv/Scripts/python.exe scripts/arena.py --seeds 8
    .venv/Scripts/python.exe scripts/arena.py --rivals camello_cfr jlam_agent_1_2 --seeds 20

## Fidelity caveat

MIT 2026's game is not ours. Their flop is 2 cards, the discards are **sequential** (BB first) and
**become board cards**, there is no betting before the discard, and stacks are 400. The adapter
translates as follows:
- **Preflop:** MIT street 0.
- **Flop betting:** the bot's discard logic is asked first; then flop betting is shown as MIT street 4 with the 2 kept cards.
- **Discard:** the discard chosen above.
- **Turn / river:** MIT streets 5 / 6.

Their skeleton's `STARTING_STACK` is patched to 200. Their stdout is redirected to stderr, and any
exception in their code becomes check/fold, counted in `opp_err` in the arena table. Their equity
maths and CFR abstractions were built for a different game, so treat them as **realistic,
varied student-bot sparring**, not as a measure of how the real winners would play Discard Hold'em.

## Safety

This is unreviewed third-party code running unsandboxed on your machine. A static scan of the
selected bots found no subprocess, network, `eval`/`exec` or file-write calls. However
`camello_cfr`, `camello_3_1` and `rebeccax_mccfr` **`pickle.load` data files from their repos,
and unpickling can execute arbitrary code.** Skip those three if that is a concern.
