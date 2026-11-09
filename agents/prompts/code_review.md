# Prompt: diff review before merge (paste into the other model)

Review the diff of branch `ws/<id>` against `main` (`git diff main...ws/<id>`) for our Discard Hold'em bot.
Read `AGENTS.md` and the brief `agents/briefs/<id>*.md` first.

Check:
1. **Correctness** against the brief and `agents/INTERFACES.md` (signatures unchanged).
2. **Forfeit risks:** any exception path not caught by the `Brain` firewall; time loops without clock checks;
   stdout writes outside `bot.py`; file writes; imports outside stdlib/numpy/scipy.
3. **Poker logic:** dead cards (our discard, the opponent's discard, the board) excluded everywhere; amounts are
   raise-to totals; the flop has 3 hole cards, later streets 2; no future-board information in the discard.
4. **Tests:** do they check the behaviour two independent ways, as the brief requires?
5. **Simplicity:** dead code, duplication, unnecessary abstractions.

Reply with numbered findings: severity (blocker / major / minor), file:line, problem, fix. The author answers
each with *fixed* or *rejected because …* before the coordinator merges.
