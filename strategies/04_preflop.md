# 04: Preflop

Context: 3-card hands connect far more often (flop pair-or-better 65.5% vs 49.1% with 2 cards;
4-flush 11.4% vs 4.5%). Equities between hands are *closer* than in Hold'em, so playing more hands
is correct. Folding preflop costs only the blind, while the button acts first preflop and last postflop.

## P1. Simple tier heuristic (P0, day 1)
Before the table exists, score a 3-card hand by:
- **Trips:** top tier.
- **Pairs:** strong (higher pair = stronger), plus a third-card bonus for suited/connected to the pair.
- **Broadways and aces:** high-card value.
- **Suitedness:** two suited is a clear bonus; three suited is slightly *worse* than two suited
  (it kills one of our own flush outs; human Pineapple literature agrees).
- **Connectedness:** cards within a 5-rank window that can form straights.

Map the score to tiers: raise / call / fold. Never fold the big blind to a min-raise with a top-60% hand.

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

Cost: 2 h. Status: todo.

## P2. 1755-hand equity table (P1)
Precompute offline the equity of each canonical 3-card hand vs a random 3-card hand (flop discard
by D1 logic for both), ~20k samples each. Ship it as JSON. Then:
- **Button (acts first):** open-raise top ~70–80% (to 5–6 chips = 2.5–3 BB), limp a few, fold the bottom.
- **Big blind vs open:** 3-bet the top ~15%, call the next ~50–60%, fold the rest (adjust by raise size:
  pot odds improve vs small raises).
- **Facing a 3-bet or 4-bet:** continue with the top ~25% / ~10%; shove or call depending on stack-to-pot.

All percentages are starting points to tune in the arena. Cost: 3 h + compute. Status: todo.

## P3. Sizing (P1)
- Open: 3× BB (6 chips). Min-raises give weak bots good odds.
- 3-bet: ~3× the open. 4-bet: ~2.2× or shove when the 4-bet would commit > 40% of the stack.
- **Raise cap:** preflop allows the BB plus 3 raises. With the cap reached, only call/fold remain, so a 4-bet
  that ends the raising is effectively uncapped pressure.

Status: todo.

## P4. Exploit adjustments (P2, from 06)
- vs a calling station: raise wider for value, never limp-fold.
- vs a maniac or all-in bot: the break-even point for calling a 200 shove is **49.5% (BB) / 49.75% (SB)** equity
  vs *their shoving range*, computed with both players' later discards simulated. Two views:
  - Gemini: gate at **~56.5% vs random (≈ the top 34%)**, giving up a little EV for much lower variance.
  - GPT-astra: "wait for premiums" is not automatically best; an indiscriminate shover justifies broad calls.
  **Decide in the arena** with `charlar_all_in_v2` and our own shove bot: compare match-win rate, not chips.
  Stop opening small speculative hands.
- vs a nit or big blind that over-folds (fold-to-steal > 0.62): open 100% of buttons, min-raise to 4.

Status: todo.
