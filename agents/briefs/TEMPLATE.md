# Wn: <title>

**Agent:** Claude Code / Codex · **Branch:** `ws/Wn` · **Worktree:** `../pokerbots_wt/Wn`

## Goal
<one sentence, measurable>

## Owns (may edit)
- `bot/<module>.py`, `tests/test_<module>.py`, `# --- Wn ---` section of `bot/params.py`

## Must not edit
Everything else (ask the coordinator). Never `champion/`, `dist/`, `starter_kit/`, `docs/`, `rivals/`.

## Interfaces
Implements: <from agents/INTERFACES.md>. Depends on: <modules; stub them if not merged>.

## Strategy items
`strategies/NN_*.md`: <IDs>, in priority order.

## Check two ways
1. <independent check 1>
2. <independent check 2>

## Measure
`pytest` · `scripts/build.py --check` · `scripts/arena.py --rivals random starter --seeds 8` ·
`scripts/promote.py --dry-run`

## Done when
- [ ] tests pass, build check passes, 0 notices
- [ ] <workstream-specific criterion>
- [ ] the other model reviewed the diff; findings fixed or rebutted
- [ ] `Status:` lines updated in `strategies/`
