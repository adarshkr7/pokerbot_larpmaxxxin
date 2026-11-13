# 03: The discard (biggest cheap edge)

Our measurement (1,500 random flops, opponent = random 2 cards; `research/bench_discard.py`):

| Fact | Value |
|---|---|
| "Toss lowest rank" picks the max-equity discard | only **55.7%** of flops |
| Equity lost per contested flop by "toss lowest" | **≈ 5.5%** |
| Best-vs-worst discard equity spread | median 22.5%; > 15% on **72%** of flops |

**Re-run with realistic opponents** (dealt 3 cards, keep their best made hand on the flop; GPT-astra's
correction): toss-lowest is optimal on 56.6% of flops and loses **6.1%** equity, so the edge is even larger.

Many student bots will toss the lowest card or a random one. Getting this right is worth a lot.

## D1. Equity-max keep vs realistic opponent holdings (P0)
For each of the 3 keep-pairs, estimate equity on this flop over turn+river and keep the best.
- **The opponent is dealt 3 cards too.** Sample opponent *triples* from the unseen cards (weighted by
  their range once D2 exists) and apply an **opponent discard policy** (cheap: keep the pair with the best
  made hand on the flop, plus a draw bonus). That policy may use only *their* triple and public info,
  never our cards, our discard, or the sampled future board.
- **Never choose our discard by looking at a simulated runout.** Our candidate stays fixed across all
  runouts; we average, then choose.
- Use common random numbers (the same sampled opponent triples and runouts) for all 3 pairs.
- Budget: ~300–600 shared samples (each sample scores all 3 keeps). If the best two keeps are within 1%
  (inside the sampling noise) **and betting is still possible**, prefer the one with more *draw potential*
  (flush/straight draw), since a draw gains when we can bet it on the turn [analysis]. When all-in (D5) take
  the plain maximum.
- Zero-compute path (panic tier, or an exception): keep the pair with the best static flop score `S` (D3),
  which is still far better than toss-lowest.
- Our own discarded card is dead for the rest of the hand: it must stay in the dead mask for every later
  equity call.
- **Note:** discards are DEAD in our game, unlike MIT 2026 where they became board cards (that is
  why MIT's MC reference bot did *worse* than toss-lowest; it doesn't apply to us).

Cost: 2 h on top of E1/E3. Status: done (`bot/discard.py`; 16-0-0 vs v0 at +0.207 ± 0.014 chips/hand with identical betting; ~17% of the Stage 2 bank).

## D2. Equity vs the opponent's *range* (P1)
The opponent isn't random by the flop: they chose to play preflop and continued on the flop. Weight the
sampled opponent holdings by how likely they are to have played this way:
- preflop: weight by their 3-card preflop strength vs their observed VPIP/raise behaviour
  (e.g. a raiser's range = top X% of hands, with X from their stats). "Top X%" is **combination-weighted**:
  accumulate each class's physical multiplicity (4, 12 or 24 triples), as in 04/P2, not a count of classes;
- flop: a bettor or raiser is weighted towards made hands and draws.
Implementation: rejection sampling or importance weights on sampled 3-card opponent hands. Each
sampled opponent then keeps *its* best 2 (simulate their discard with D1 logic or a cheap proxy).

Cost: 4 h. Status: plug-in points built (`triple_weight`, `prior`); the range models themselves are todo (need 04 and 06).

## D3. Read the opponent's exposed discard (P1)
After `discard_result` we know their discarded card:
1. **Card removal:** the card is dead. Remove it from runouts and from their possible holdings
   (keep an explicit `dead[52]` mask: our 3 cards, the board, their discard).
2. **Inverse-discard filter (Gemini, refined).** Enumerate the candidate kept pairs {c1, c2} from the unseen
   cards (C(45,2) = 990 right after the discard, 946 on the turn, 903 on the river). Each implies their original
   hand T = {c1, c2, d_v}. Weight:
   `W(c1,c2) ∝ [P_preflop(C | their preflop action) / m(C)] × P_flop(their flop action | S_best(T))
   × L_discard`, where `C = canon(T)` and `m(C)` is the number of physical triples in that class (4, 12 or 24).
   `P_preflop(C | action)` is the mass of a whole class, so it must be divided by `m(C)` before it is assigned
   to one physical triple; otherwise each rainbow triple gets six times the weight of each monotone one. (The
   simplest correct form: give every physical triple the weight `play(C)`, the probability that a hand of class
   C takes this preflop action.) `S_best(T)` is the max of S over the three pairs of T (during flop betting they still
   held all three cards, so their flop action depends on the triple, not on the pair they later kept), and
   `L_discard = exp(β·S(c1,c2)) / [exp(β·S(c1,c2)) + exp(β·S(c1,d_v)) + exp(β·S(c2,d_v))]`
   (a softmax "quantal response").
   **S is a cheap flop score on one fixed scale, defined once and used everywhere (D1 fallback, D3, 06/M1):**
   `S = category + kicker_fraction + draw bonus`, with `v = eval7(pair + flop)`, `category = v >> 20`
   (0 = high card … 8 = straight flush) and `kicker_fraction = (v & 0xFFFFF) / 2**20` ∈ [0, 1); the draw bonus (only when the made hand is below a straight) is +0.25 for a flush draw,
   +0.20 for an open-ended straight draw, +0.08 for a gutshot, +0.04 per hole card above the top board card.
   On this scale β ≈ 4 means "a pair one class better is kept about 55 times more often".
   - Scale β by their observed **discard rationality τ** (06/M1). For a **random discarder** β = 0, i.e.
     `L_discard = 1/3` for every pair (only card removal is left).
   - A **toss-lowest** opponent is *not* uninformative: seeing d_v means both kept cards rank at or above it
     (tossing an ace means they kept two aces). When the toss-lowest detector (06/M1) fires, use
     `L_discard = (1 − η)·[d_v is the card toss-lowest would discard from T, ties s < h < d < c] + η/3` with
     noise η ≈ 0.1, instead of the softmax.
   - **Smoothing, applied once to the final weights:** normalise the raw products to `q` over the M valid pairs
     (if their sum is 0 or not finite, use uniform `q`), then return `W_i = 0.98·q_i + 0.02/M`. Do **not** add
     0.02 to every raw pair weight: over 990 pairs that would make the result 95% uniform and erase the
     inference. This also rules out a zero-sum normalisation (a ZeroDivisionError would be a crash).
   - Vectorise it in numpy: ~990 rows, a few ms.
3. **Signals [analysis]:**
   - **High card tossed (A/K/Q):** they kept two cards they value more, usually a pair, set, two pair or
     strong draw. Their range is strong or drawy.
   - **Tossed card matches a board suit:** they are probably not on that flush draw (or kept two others of it).
   - **Low card tossed:** little information under toss-lowest, but under equity-max it is weak evidence too.

Cost: 3 h (after D2 sampling exists). Status: `posterior_after_discard` done and tested; not yet called by the live bot (05/B7 will use it).

**Worked examples (Gemini; verified by us with 40k samples, opponent dealt 3 cards and keeping its best made
hand)** of choosing by flop context, not by preflop rank:
- A♠K♠Q♦ on J♦T♣2♠: toss the **A**, keep KQ for the open-ended straight draw (KQ 53.0%, AK 50.3%, AQ 47.3%).
- A♠K♠Q♦ on 9♠4♠2♦: toss the **Q**, keep the nut flush draw (AK 64.4%, AQ 43.2%, KQ 38.9%).
- A♦Q♦9♣ on A♠9♥4♣: toss the **Q**, keep two pair (A9 92.5%, AQ 84.7%, Q9 68.6%).

Use these as unit-test cases for D1. The first has only a ~2.7-point gap, so its test needs a fixed seed and
≥ 4,000 samples (or exact enumeration); the other two are safe with a few hundred.

## D4. Our discard leaks information (P2)
Theory (Gemini): total EV of a discard = equity EV + information EV. The information EV is 0 when all-in or
against opponents who don't read discards. **Pure showdown-equity maximisation is exactly optimal only when no
further betting is possible** (D5). While betting remains, the keeps can also differ in how well they realise
equity and win later bets, even against an opponent who ignores discards; that is what D1's draw tie-break is
for. Deception is only worth considering within ~1.2% equity, and only vs opponents shown to read discards:
- **No automatic "toss a high card with a monster".** By D3's own reading, a high card tossed signals a
  *strong or drawy* kept hand, so it does not induce bluffs from an opponent who reads discards the way we do.
  Use D1's choice unless we have evidence of how this opponent reacts.
- **Kept hand is not a flush draw:** avoid tossing a card of the flop's two-flush suit when we plan to check-call
  (it would announce that we are capped against flushes).

Cheap counter-measures:
- when two keeps are within ~1–2% equity, randomise between them;
- don't systematically toss the highest card only with monsters.

Against a weak field this barely matters. Low priority.

Status: todo.

## D5. All-in discards (P0)
When all-in before the discard, there is no more betting, so pure equity-max (D1) with more samples is exactly right.
Status: done (plain maximum, larger sample cap when all-in).
