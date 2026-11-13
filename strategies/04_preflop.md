# 04: Preflop

Context: 3-card hands connect far more often. With the best legal two-card keep plus the flop we make a pair
or better 66.6% of the time, vs 49.9% with two dealt hole cards. Four or more cards of one suit (made flushes
included) appear among our three hole cards plus the flop 11.4% of the time, but a legal keep can hold on to
four of them only 9.3% of the time (three suited hole cards plus one on the flop lose one to the discard), vs
4.5% with two hole cards. Equities between hands are *closer* than in Hold'em, so playing more hands
is correct. Folding preflop costs only the blind, while the button acts first preflop and last postflop.

## P1. Simple tier heuristic (P0, day 1)
Before the table exists, score a 3-card hand by:
- **Trips:** score them as the **pair we will keep**, minus a penalty: one of our own set outs is dead in our
  hand and there is no alternative keep. They are *not* all premium: vs a random 3-card hand (both sides
  discarding by the static flop score, 100k samples) 222 has about 32% equity, 999 about 58%, AAA about 77%.
- **Pairs:** strong (higher pair = stronger), plus a third-card bonus for suited/connected to the pair.
- **Broadways and aces:** high-card value.
- **Suitedness:** two suited is a clear bonus; three suited is slightly *worse* than two suited
  (it kills one of our own flush outs; human Pineapple literature agrees).
- **Connectedness:** cards within a 5-rank window that can form straights.

Map the score to tiers: raise / call / fold. Use pot odds for the cheap spots (the request's `pot` already
includes every chip committed): the big blind facing a min-raise to 4 calls 2 into 6 and needs only 25% raw
equity, and the button completing calls 1 into 3 (also 25%). Almost every 3-card hand has that much against a
wide range, so **defend the big blind against a min-raise with at least the top ~90%**, and against a 3× open
(call 4 into 8, 33%) with the top ~65–75%. Fold only the bottom tier.

**Synergy matters more than the best two cards (Gemini, consistent with the Pineapple literature):**
- **Premium:**
  - high pair + suited broadway kicker (A♠A♥K♠, K♦K♣Q♦);
  - two-suited broadway wraps (A♠K♠Q♦, K♠Q♠J♦);
  - suited connected wraps (T♠9♠8♦, J♥T♥8♣).
- **Danglers:** a useless third card (A♠K♥2♣ rainbow) makes a hand worth clearly less than its top two cards suggest.
- **Naked low pairs** (4♠4♥9♣): they miss the set 88% of the time and become weak underpairs. Mostly set-mining hands.
- **Traps:**
  - **monotone** (three of one suit): worse than two-suited;
  - **rolled-up trips** (0.24%): one must be discarded, leaving a pair with a single out. Never 4-bet shove
    low or medium trips (222–999).

The 1,755-hand table (P2) captures all of this automatically. The heuristic needs it hand-coded.

Cost: 2 h. Status: done as the fallback (`preflop.heuristic`, fitted to the table; used only if the table file is missing).

## P2. 1755-hand equity table (P1)
Precompute offline the equity of each canonical 3-card hand vs a random 3-card hand (flop discard
by D1 logic for both), ~20k samples each. Ship it as JSON. Then:
- **Button (acts first):** open-raise top ~70–80% (to 5–6 chips = 2.5–3 BB), limp a few, fold the bottom.
- **Big blind vs open:** 3-bet the top ~15%, call the next ~50–60%, fold the rest (adjust by raise size:
  pot odds improve vs small raises).
- **Facing a 3-bet** (we opened to 6, they made it 18: call 12 into 24, so 33% equity needed vs *their* 3-bet
  range): continue with about the **top 35–40% of all hands**, i.e. roughly half of our opening range. Folding
  more than two thirds of the opens lets any 3-bet profit immediately (it risks 16 to win 8).
- **Facing a 4-bet** (the cap is reached: we can only call or fold preflop, vs a strong range): continue with
  about the top ~10–15% of all hands, more when the price is better than 3:1. This is **not** a pure
  showdown-equity decision unless the call puts a player all-in: after 6 → 18 → 40 and a call the pot is 80 with
  160 behind each, and the raise counter resets on the flop. So compare *realised* equity (05/B1's `R_pos`,
  0.92 out of position) with the price; use raw equity vs `to_call / (pot + to_call)` only when the call is
  all-in.
- Percentages are always **of all 1,755-class hands weighted by combinations**, not of the range we arrived with.

All percentages are starting points to tune in the arena. Cost: 3 h + compute. Status: done (`bot/data/preflop.json`, 120k samples per class, SE 0.14 points, plus equity vs top-5/10/20/35/50/75% ranges; ranges in `bot/preflop.py`, thresholds in `params.py` W4, untuned).

## P3. Sizing (P1)
- All amounts are **raise-to totals for the street, blinds included** (the button's open "to 6" adds 5 chips).
  Clamp to `[min_raise, max_raise]`; `max_raise` is 200 for both seats preflop.
- Open: 3× BB (to 6). Min-raises give weak bots good odds.
- 3-bet: ~3× the open (to 18). 4-bet: ~2.2× the 3-bet (to 40), or all-in when the 4-bet would commit > 40% of
  the stack.
- **Raise cap:** the big blind counts as bet 1, so preflop allows 3 raises: open (`raises_left` 3 → 2), 3-bet
  (→ 1), 4-bet (→ 0). **The 4-bet can't be re-raised**: the opponent can only call or fold. So a value 4-bet
  need not be all-in to "protect" itself, and when *we* face a 4-bet we only choose between calling and
  folding (see P2 for how).
  After a button limp the sequence shifts by one seat (BB raise, button 3-bet, BB 4-bet).

Status: done (open to 6, 3-bet 3x, 4-bet 2.2x, all-in when a raise commits > 40% of the stack).

## P4. Exploit adjustments (P2, from 06)
- vs a calling station: raise wider for value. A station's rare raise is strong (06/M2), so after limping we
  may still fold to it when continuing is −EV; facing a shove, require the pot-odds equity as always.
- vs a maniac or all-in bot: the break-even equity for calling a 200 shove is `to_call / (pot + to_call)` vs
  *their shoving range*, computed with both players' later discards simulated. That is **49.5%** for the big
  blind facing an open shove (198 into 202) and for the button after limping; **48.5%** for the button after
  opening to 6 (194 into 206). (An earlier "49.75% for the SB" figure was wrong: the button acts first, so it
  never faces a shove with only the small blind in.) Two views:
  - Gemini: gate at **~56.5% vs random (≈ the top 34%)**, giving up a little EV for much lower variance.
  - GPT-astra: "wait for premiums" is not automatically best; an indiscriminate shover justifies broad calls.
  **Decide in the arena** with `charlar_all_in_v2` and our own shove bot: compare match-win rate, not chips.
  Stop opening small speculative hands.
- vs a nit or big blind that over-folds (fold-to-steal > 0.62): open 100% of buttons, min-raise to 4. (The
  steal risks 3 to win 3, so it breaks even at 50% folds before counting our equity when called.)

Status: hooks done, inactive until 06 supplies `hands`, `shove`, `fold_to_steal`, `fold_to_bet`, `vpip`, `pfr`, `three_bet`. **Known gap until then:** an unknown shover is assumed to hold the top 20%, so we fold ~92% of hands to an always-shove bot (+6.6 chips/hand vs +20.9 for call-everything; +26.8 once the shove stat is supplied).
