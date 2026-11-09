# 07: Game-theoretic options

## G1. Light mixing (P2)
Randomise between near-equal options (within ~2% EV) so bet-size-reading bots can't model us:
sizes, bluff selection and near-tie discards. Cheap, and it doesn't hurt vs weak bots.

Status: todo.

## G2. Minimum defence frequency (P1)
Facing a bet b into pot P, defend (call or raise) at least `P / (P + b)` of our range when the opponent
is capable of bluffing. That stops aggressive bots from profiting with any two cards. Implement it as a lower
bound on our continue range in the call rule (05/B1) vs aggressive archetypes.

Status: todo.

## G3. Preflop-only CFR (P3)
1755 canonical hands × a short action tree (fold / call / raise 3× / shove, ≤ 3 raises) with
equity-based terminal values (all-in equity from the E4 table). Small enough to solve offline in
Python in minutes to hours. It gives balanced open/3-bet/call ranges.
- Value: moderate. The heuristic tiers from 04/P2 tuned in the arena may get most of it.
- Do only if v2 is done by Sat.

Status: todo.

## G4. Full MCCFR blueprint (P3, probably rejected)
MIT 2026 Camello's *final* bot was CFR with card buckets (strength × texture × discard value)
plus an MC fallback plus profiling. The 2017 MIT champion was also CFR-based. But:
- they had a month; we have 5 days; and Python training is slow;
- abstraction bugs are hard to detect, and the edge over a tuned equity bot plus exploitation vs a weak field is
  unclear; GTO Wizard (MIT 2024) used heuristic leaves even with ample resources.
Decision: **don't build** unless everything else is done and stable.

Status: rejected for now (time).

Gemini's sizing analysis:
- **The discard blows up the tree.** The face-up discard multiplies the turn and river information sets
  (up to 2,652 public discard pairs), so a full-game CFR needs very lossy buckets.
- **Storage is not the obstacle.** A 300k-information-set strategy as uint8 (3 stored probabilities, the 4th
  implied) is ~900 KB raw, ~400–550 KB compressed.
- **Recommendation:** if any CFR, **preflop + flop only** (~25k information sets with 1,755 hand classes ×
  ~50–120 flop texture buckets); turn and river via range equity.

GPT-astra (agrees CFR is optional):
- If we try a blueprint, start with **16 / 32 / 32 / 64** buckets (preflop / flop / turn / river) and actions
  check/call, fold, ½ pot, pot, all-in. Count reachable information sets before training.
- Augment equity buckets with draw type, nut potential, texture and discard features before trying EMD
  clustering.
- Model the simultaneous discard as one player's hidden choice followed by the other's, revealing both afterwards.
- Against a fixed opponent with no later betting, a pure best-response discard exists. Mixing only matters
  for signalling.
- Discounted CFR beats CFR+ in published tests if we ever train.

## G5. River subgame solving (P3)
On the river with a sampled range for both players, a tiny bet/call game could be solved in ~10–30 ms.
Gemini proposes a sequence-form LP with `scipy.optimize.linprog(method="highs")`: 20 equity buckets per player and
check / bet ⅔ / all-in, claimed ~20 ms. **Unverified, so benchmark before committing.** Warm up scipy at
start-up. GPT-astra: a solver must model our whole *range* (so value bets and bluffs support each other),
not just our actual hand. A restricted game with 8–16 buckets and 1–2 bet sizes might fit in 50 ms. 05/B6 polarised heuristics capture most of the value vs this field.

Status: todo (unlikely).
