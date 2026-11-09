# 05: Postflop betting (flop, turn, river)

Base engine: **equity vs the opponent's estimated range** (02/E3, 03/D2) combined with **pot odds**.

Notes for the flop: we hold 3 cards during flop betting (the discard comes after). Flop equity should
be "equity of our best keep" (the D1 calculation), not 3-card equity.

## B1. Calling rule (P0)
Call if `R_pos · equity > to_call / (pot + to_call) + margin`.
- margin ≈ +2–5% on the flop and turn (reverse implied odds, our weaker equity realisation out of position),
  ≈ 0 on the river.
- `R_pos` = equity-realisation factor (Gemini): ~1.08 in position (button postflop), ~0.92 out of position
  (big blind postflop), 1.0 on the river.
- **Handle off-tree sizes:** opponents may min-bet 2 chips or overbet-shove. Always use the
  continuous pot-odds formula, never a lookup keyed on "their size bucket".
- Facing all-in: margin 0 (no future streets).

Status: todo.

## B2. Value betting (P0)
Bet or raise when equity vs their *calling* range > ~55–60% (calling ranges are stronger than their
whole range). Against calling stations use their whole range, since they call with anything.

Status: todo.

## B3. Size menu (P0)
Only a few sizes, clamped to `[min_raise, max_raise]`:
- **⅓ pot:** thin value or probes, dry boards;
- **⅔ pot:** standard value or semi-bluffs;
- **1× pot:** strong value on wet boards, or vs stations;
- **all-in:** when the stack-to-pot ratio after betting would be ≤ ~1, or vs stations with the nuts.

Remember amounts are *raise-to* totals on the street: `amount = opp_bet + size`.

Status: todo.

## B4. Raise-cap awareness (P1)
At most 4 bets or raises per street. With `raises_left == 1`, our raise ends the raising, so the opponent can only
call or fold. With strong hands, size that last raise big (or shove), because it can't be re-raised.

Status: todo.

## B5. Semi-bluffs (P1)
Flush or straight draws with ~30–40% equity: bet or raise on the flop/turn when the opponent folds often
(fold-to-bet stat > ~45%). Never vs stations. Use the 3-card advantage: on the flop we can hold
draws *and* made hands across our 3 cards.

Status: todo.

## B6. River bluffs (P1)
Polarised river: bet value with the top of the range and bluff with the bottom (no showdown value).
Bluff share of the betting range = bet/(pot + 2·bet): **~29% for ⅔ pot, 33% for pot** (Gemini's
B/(P+3B) is wrong). Bluff *only* vs opponents who fold enough. Bluff 0% vs stations or random bots.

Status: todo.

## B7. Range-aware equity (P1)
Replace "vs random" with "vs range" (03/D2 machinery) on every street after the opponent shows
aggression. A bet or raise from a passive opponent is strong, so shift their range heavily.

Status: todo.

## B8. Bet-size tells (P2)
Weak bots often size proportionally to strength. Record (size/pot → showdown strength) pairs per leg
and condition their range on their size once ≥ ~10 showdowns are observed.

Status: todo.

## B8b. Archetype thresholds (P1, starting values from Gemini; tune them)
- **Station:** value-bet when E ≥ 0.52 vs their (wide) range; size 0.6× pot for 0.52–0.68 and 1–2× pot (or a
  geometric shove) above 0.68; zero bluffs; bet draws only when E ≥ 0.55.
- **Nit / equity-threshold bot:** c-bet ~30% of pot on every flop (break-even is 23% folds); when it raises,
  its range is roughly E ≥ 0.65–0.75 vs random, so fold one pair and continue only with E ≥ 50% vs its top ~15%.
- **Random:** value-only; call its raises when E ≥ 0.55; raise to the cap when E ≥ 0.68.

## B9. Check-raise and slow-play (P3)
With monsters vs aggressive opponents, check to induce bets. Only after archetype detection (06).

Status: todo.
