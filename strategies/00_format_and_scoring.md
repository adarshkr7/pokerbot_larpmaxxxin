# 00: What the format and scoring reward

Not strategies to code, but facts that should drive every design decision.

## F1. Duplicate deals cancel card luck
Each deal is played twice with hole cards and seats swapped (Rulebook 7.1). Over a match, the
chip difference comes almost entirely from **decision differences on identical cards**.
- A small but *consistent* edge (e.g. better discards on every contested flop) turns into match wins
  far more reliably than in a single-deal format.
- Duplication **reduces** card luck; it does not remove it. When the two bots play a deal differently the
  stakes differ (one shoves and is called for ±200 while its twin folds for −2), and the engine simply sums
  both legs, so residual variance remains. High-variance lines still carry luck; they just gain no *expected*
  benefit from it.

## F2. Match points first, chips second
Win 1 / draw 0.5 / loss 0, ranked by points. Ties are broken by **capped** chips per hand (each match's net is clipped to
±400 in Stage 1 and ±1000 in Stage 2).
- Crushing one opponent by 3000 chips counts no more than winning by 1000 in Stage 2.
- **Beating everyone narrowly beats destroying a few.** Prefer robust, broadly good play over
  aggressive exploits that can backfire against the wrong opponent type.

## F3. A forfeit is the worst possible outcome
A crash, timeout, 5 s reply or wall-clock kill loses the match with Δ = −C, the maximum loss, and the
opponent gets +C (C = 400 in Stage 1, 1000 in Stage 2). The only double-forfeit draw (Δ = 0) is when both bots fail during
the same simultaneous discard exchange; a failure on an action request forfeits the bot that was asked. No strategy edge is worth any forfeit risk. See [01_robustness.md](01_robustness.md).

## F4. Stacks reset every hand at 100 BB
No bankroll or tournament dynamics. Every hand is an independent 200-chip game (blinds 1/2). The cap is
**4 bets or raises per street, and the big blind counts as the first one preflop** (so 3 voluntary raises
preflop, 4 on later streets). Stacks are only 100 BB and each street can be raised four times, so big pots
often get all-in early; then **equity realisation is high** and equity-based play is closer to correct than
in deep-stack poker.

Seats (engine `betting_round`): the **button posts the small blind and acts first preflop; the big blind acts
first on the flop, turn and river**. So the button is in position on every postflop street.

## F5. No memory across legs
Each leg is a fresh process, so the opponent model starts from zero every leg (200 or 500 hands). Our
model must learn fast (useful after ~30 hands) and must start from good defaults.

## F6. Variance management [analysis, low priority]
We can't see the other leg, so leg-level score management is weak. Within a leg we could reduce
variance (fewer marginal all-ins) when far ahead of a clearly weaker opponent. **P3:** probably
not worth building.

Gemini's version ("variance modulator"):
- **Normal:** maximise EV.
- **Lead protection:** if ahead by > +800 (Stage 1) or > +1600 (Stage 2) after 65% of the leg, raise the all-in call
  threshold by ~4%.
- **Desperation:** if behind by > 1000 after 75% of the leg and our estimated edge ≤ 0, loosen shove thresholds
  by ~1%.

Cheap to add as two threshold offsets once the rest works. The simpler version of the same idea is the
tighter shove-calling gate vs all-in bots (04/P4).

**GPT-astra's critique (we agree):** a lead in the visible leg may simply be good cards that the twin leg
gives back to the opponent, so it is weak evidence that the *match* is won. Default to chip-EV; add
risk adjustment only with a tested model of the unseen leg. **Status: rejected for v0–v2.**

Status: reference only.
