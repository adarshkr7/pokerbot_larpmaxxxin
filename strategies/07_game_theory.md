# 07: Game-theoretic options

## G1. Light mixing (P2)
Randomise between near-equal options (within ~2% EV) so bet-size-reading bots can't model us: sizes and bluff
selection. Mixing in a lower-EV option gives up that EV difference every time, so it needs a compensating
benefit: against opponents who don't model us, just take the best option.
- **Discards:** when all-in, always the maximum-equity discard, no mixing (03/D5). While betting remains, mix
  discards only under 03/D4's conditions (within ~1.2 points of equity, opponent shown to read discards).

Status: partly done (borderline preflop hands and bluff selection are randomised; no size mixing; no discard mixing).

## G2. Minimum defence frequency (P1)
Facing a bet b into pot P (**P = the pot before their bet**), a range that continues less often than
`MDF = P / (P + b)` lets a zero-equity bluff of that size profit immediately.
- In request terms, for an opening bet: `b = to_call` and `P = pot − to_call`, so `MDF = (pot − to_call) / pot`.
  (Using the request's `pot` as P makes the bet look smaller than it is.)
- **MDF is a diagnostic, never an override of 05/B1.** It says nothing about one hand: on the river or facing
  an all-in, fold whenever the call is −EV against their betting range (shove 150 into 100: a hand with 20%
  equity loses 70 chips by calling, whatever its percentile). On earlier streets the decision is continuation
  EV (B1 with `R_pos`).
- **How we use it:** track how often we fold to opening bets, per street. If our fold rate vs an *aggressive*
  archetype (06/M2) runs clearly above `1 − MDF` over ≥ 20 such bets, the likeliest cause is that our estimate
  of their betting range is too strong: widen that range (lower the B7 shift for this opponent), which makes B1
  call more. Do not force individual calls.
- A percentile against uniformly random hands is only a strength heuristic. It does **not** measure our share
  of our own arrival range (which is conditioned on our earlier actions and discard), so it must not be used
  to "enforce" MDF.

Status: done as the diagnostic (`mdf_tilt` in `bot/opponent.py`, read by `bot/betting.py`).

## G3. Preflop-only CFR (P3)
1755 canonical hands × a short action tree (fold / call / raise 3× / shove, ≤ 3 raises). Terminal values must
come from **matchups**: sample two disjoint physical triples, play out board and discards under a stated
policy, and give both players chip utilities from that one outcome and their actual commitments. The E4 table
(equity vs a *fixed* range) is not enough: two premium hands would both get > 50% and the game would stop
being zero-sum. Non-all-in leaves also need a stated continuation value (e.g. realised equity × pot).
Solvable offline in Python in minutes to hours; it would give balanced open/3-bet/call ranges.
- Value: moderate. The heuristic tiers from 04/P2 tuned in the arena may get most of it.
- Do only if v2 is done by Sat.

Status: not built (no time).

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
- **Recommendation:** if any CFR, **preflop + flop only**; turn and river via range equity. Gemini's "~25k
  information sets" does not follow from its own abstraction: 1,755 hand classes × 50–120 flop texture buckets
  is 88k–211k combinations before betting histories and seats. Count reachable information sets explicitly.

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
