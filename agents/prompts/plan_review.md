# Prompt: plan review (paste into the reviewing model)

You are reviewing a design plan for our Discard Hold'em bot. Read `AGENTS.md`, `DEVELOPMENT.md`,
`agents/INTERFACES.md` and the relevant `strategies/` files first. Then review the plan below.

Look for, in order:
1. **Bugs and wrong assumptions** about the rules (`docs/`, `starter_kit/engine.py` is the reference).
2. **Failure modes that forfeit a match:** crashes, timeouts, illegal actions, file writes, unhandled
   messages, numeric edge cases (all-in, min = max raise, zero weights).
3. **Information leaks / impossible information:** e.g. a discard chosen using a future board; an opponent model
   using our hidden cards.
4. **Interface conflicts** with other workstreams.
5. **Rule compliance:** stdlib/numpy/scipy only; no code from public bot repos; no cross-leg state.
6. **Simplicity:** anything that can be cut without losing measurable strength.

Reply with a numbered list of findings. Each one: severity (blocker / major / minor), the exact plan text it
refers to, why it is a problem, and a concrete fix. Say "no material findings" only if there are none.

--- PLAN ---
<paste plan here>
