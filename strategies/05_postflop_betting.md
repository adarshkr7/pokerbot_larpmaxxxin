# 05: Postflop betting (flop, turn, river)

Base engine: **equity vs the opponent's estimated range** (02/E3, 03/D2) combined with **pot odds**.

Notes for the flop: we hold 3 cards during flop betting (the discard comes after). Flop equity should
be "equity of our best keep" (the D1 calculation), not 3-card equity: **average each keep over the samples,
then take the max of the three averages**. (Taking the best keep inside each sample peeks at the runout and
overstates equity.) The opponent in those samples also holds 3 cards and discards by the D1 policy.

Seats: the big blind acts first on every postflop street, so the **button is in position** postflop.

## B1. Calling rule (P0)
Call if `R_pos · equity > to_call / (pot + to_call) + margin`.
- `pot` is the request's `pot` field: **all chips committed so far, including the bet we are facing** (engine:
  `sum(committed)`). Do not add the opponent's bet again.
- margin ≈ +2–5% on the flop and turn (reverse implied odds), ≈ 0 on the river.
- `R_pos` = equity-realisation factor (Gemini): ~1.08 in position (button postflop), ~0.92 out of position
  (big blind postflop), 1.0 on the river. Don't also put the positional penalty into the margin (count it once).
- **No future betting → plain pot odds:** when the call puts either player all-in (`to_call ≥ my_stack`, or
  `opp_stack == 0`), or on the river, use `R_pos = 1` and margin 0.
- **Handle off-tree sizes:** opponents may min-bet 2 chips or overbet-shove. Always use the
  continuous pot-odds formula, never a lookup keyed on "their size bucket".
- `equity` is vs the range that makes *this bet* (B7), never vs a random hand once they have bet or raised.

Status: done (`betting.calls`; R 1.08 / 0.92, margin 0.03 flop and turn, 0 river).

## B2. Value betting (P0)
Bet or raise when equity vs their *calling* range > ~55–60% (calling ranges are stronger than their
whole range). Against calling stations use their whole range, since they call with anything.

Status: done (value bet at 0.60 / 0.58 / 0.56 vs their calling range, raise at 0.66 / 0.64 / 0.62; untuned).

## B3. Size menu (P0)
Only a few sizes, clamped to `[min_raise, max_raise]`:
- **⅓ pot:** thin value or probes, dry boards;
- **⅔ pot:** standard value or semi-bluffs;
- **1× pot:** strong value on wet boards, or vs stations;
- **all-in:** when the stack-to-pot ratio after betting would be ≤ ~1, or vs stations with the nuts.

Amounts are *raise-to* totals for the street. For a pot fraction `f`:
- **opening bet** (`to_call == 0`): `amount = my_bet + round(f · pot)`;
- **raise over a bet:** first call, then raise by `f` of the pot after the call:
  `amount = opp_bet + round(f · (pot + to_call))`. (`opp_bet + f · pot` would under-size every raise.)
- Then clamp to `[min_raise, max_raise]` and send an `int`. `max_raise` is already capped by the shorter stack.
- **Shove-snap:** if the amount would leave less than ~⅓ of the new pot behind (`max_raise − amount` small),
  send `max_raise` instead.

Status: done (`betting.bet_amount`, incl. the shove-snap).

## B4. Raise-cap awareness (P1)
At most 4 bets or raises per street (postflop `raises_left` starts at 4; preflop at 3, because the big blind
counts). With `raises_left == 1`, our raise ends the raising, so the opponent can only call or fold. With strong
hands, size that last raise big (or shove), because it can't be re-raised. With `raises_left == 0` (they made
the last raise) we only call or fold, by pot odds (B1). `raise` can also be missing with `raises_left > 0`
(opponent all-in): always read `legal_actions`, never infer legality from `raises_left`.

Status: done.

## B5. Semi-bluffs (P1)
Flush or straight draws with ~30–40% equity: bet or raise on the flop/turn when the opponent folds often
(fold-to-bet stat > ~45%). Never vs stations. Use the 3-card advantage: on the flop we can hold
draws *and* made hands across our 3 cards.

Status: done (20% with untrusted stats; 70% or 0 by fold-to-bet once trusted).

## B6. River bluffs (P1)
Polarised river: bet value with the top of the range and bluff with the bottom (no showdown value).
Bluff share of the betting range = B/(P + 2B), with P the pot *before* our bet B: **~29% for ⅔ pot, 33% for
pot** (Gemini's B/(P+3B) is wrong). Bluff *only* vs opponents who fold enough. Bluff 0% vs stations or random bots.
- **We act on one hand, not a range,** so turn the share into a per-hand probability: with `v` = how often we
  reach this river spot with a value bet and `a` = how often with no showdown value, bluff an air hand with
  probability `min(1, (v / a) · B / (P + B))`. Start from fixed estimates of v and a in `params.py`.
- **Exploit test:** a pure bluff of B into P is profitable on its own when their fold-to-bet exceeds
  `B / (P + B)` (40% for ⅔ pot, 50% for pot). Use their shrunk river fold-to-bet (06/M1) against this bar.
- Pick bluff hands that block their calling range (e.g. we hold the suit of a completed flush) [analysis].

Status: done (v = 0.25, a = 0.55; blockers not built).

## B7. Range-aware equity (P1)
Replace "vs random" with "vs range" (03/D2 machinery) on every street after the opponent shows
aggression. A bet or raise from a passive opponent is strong, so shift their range heavily.
- **The shift must grow with the size of the bet** (added Fri 13 Nov after the first arena runs; not part of
  the Codex round). As first built, a shove narrowed their range no more than a 2-chip bet, and the biggest
  losses vs `jlam_agent_1_2` were pot-odds calls of flop all-ins against a barely narrowed range. Scale the
  narrowing by the bet's share of the pot (`to_call / (pot − to_call)` for an opening bet), larger again for
  an all-in, and bounded so one bet can't collapse the range. This is the built-in prior; B8 (learning this
  opponent's own size → strength mapping from showdowns) stays separate and optional.

Status: done, including the size-aware shift (`bot/betting.py`, `bot/replay.py`; damped vs opponents who are often all-in).

## B8. Bet-size tells (P2)
Weak bots often size proportionally to strength. Record (size/pot → showdown strength) pairs per leg
and condition their range on their size once ≥ ~10 showdowns are observed.

Status: not built; only the `size_corr` statistic exists (06/M1).

## B8b. Archetype thresholds (P1, starting values from Gemini; tune them)
- **Station:** value-bet when E ≥ 0.52 vs their (wide) range; size 0.6× pot for 0.52–0.68 and 1–2× pot (or a
  geometric shove) above 0.68; zero bluffs; bet draws only when E ≥ 0.55.
- **Nit / equity-threshold bot:** c-bet ~30% of pot on every flop (break-even is 23% folds); when it raises,
  its range is roughly the hands with E ≥ 0.65–0.75 vs random (about its top 15%). Estimate our equity against
  *that* range and apply B1. No blanket "fold one pair" and no fixed 50% bar: at a 25% price a hand with 40%
  equity against the raising range is a clear call.
- **Random:** value-only (no bluffs); its actions carry no information, so its range stays "random hand" and
  calls are plain B1; raise to the cap when E ≥ 0.68.

## B9. Check-raise and slow-play (P3)
With monsters vs aggressive opponents, check to induce bets. Only after archetype detection (06).

Status: not built. (B8b archetype thresholds: built, driven by the 06 archetype weights.)
