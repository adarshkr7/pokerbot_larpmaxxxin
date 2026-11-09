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
- Budget: ~300–600 samples per pair. If two keeps are within 1%, prefer the one with more
  *draw potential* (flush/straight draw), since a draw gains when we can bet it on the turn [analysis].
- **Note:** discards are DEAD in our game, unlike MIT 2026 where they became board cards (that is
  why MIT's MC reference bot did *worse* than toss-lowest; it doesn't apply to us).

Cost: 2 h on top of E1/E3. Status: todo.

## D2. Equity vs the opponent's *range* (P1)
The opponent isn't random by the flop: they chose to play preflop and continued on the flop. Weight the
sampled opponent holdings by how likely they are to have played this way:
- preflop: weight by their 3-card preflop strength vs their observed VPIP/raise behaviour
  (e.g. a raiser's range = top X% of the 1755-table, with X from their stats);
- flop: a bettor or raiser is weighted towards made hands and draws.
Implementation: rejection sampling or importance weights on sampled 3-card opponent hands. Each
sampled opponent then keeps *its* best 2 (simulate their discard with D1 logic or a cheap proxy).

Cost: 4 h. Status: todo.

## D3. Read the opponent's exposed discard (P1)
After `discard_result` we know their discarded card:
1. **Card removal:** the card is dead. Remove it from runouts and from their possible holdings
   (keep an explicit `dead[52]` mask: our 3 cards, the board, their discard).
2. **Inverse-discard filter (Gemini, refined).** Enumerate the ≤ 990 candidate kept pairs
   {c1, c2} from unseen cards. Each implies their original hand {c1, c2, d_v}. Weight:
   `W(c1,c2) ∝ P_preflop(canon(c1,c2,d_v) | their preflop action) × P_flop(their flop action | S(c1,c2))
   × L_discard`, where
   `L_discard = exp(β·S(c1,c2)) / [exp(β·S(c1,c2)) + exp(β·S(c1,d_v)) + exp(β·S(c2,d_v))]`
   (a softmax "quantal response"). Here S is a cheap flop score: made-hand rank + 0.25 for a flush draw, +0.20 for an open-ended straight draw,
   +0.08 for a gutshot, +0.04 per overcard.
   - Scale β by their observed **discard rationality τ** (06/M1). If they toss the lowest card or at random, β≈0
     (their discard tells us nothing beyond card removal).
   - Add a floor ε ≈ 0.02 and 1e-9 before normalising, so an irrational discard never collapses the
     range to zero weight (a ZeroDivisionError would be a crash).
   - Vectorise it in numpy: ~990 rows, a few ms.
3. **Signals [analysis]:**
   - **High card tossed (A/K/Q):** they kept two cards they value more, usually a pair, set, two pair or
     strong draw. Their range is strong or drawy.
   - **Tossed card matches a board suit:** they are probably not on that flush draw (or kept two others of it).
   - **Low card tossed:** little information under toss-lowest, but under equity-max it is weak evidence too.

Cost: 3 h (after D2 sampling exists). Status: todo.

**Worked examples (Gemini)** of choosing by flop context, not by preflop rank:
- A♠K♠Q♦ on J♦T♣2♠: toss the **A**, keep KQ for the open-ended straight draw.
- A♠K♠Q♦ on 9♠4♠2♦: toss the **Q**, keep the nut flush draw.
- A♦Q♦9♣ on A♠9♥4♣: toss the **Q**, keep two pair.

Use these as unit-test cases for D1.

## D4. Our discard leaks information (P2)
Theory (Gemini): total EV of a discard = equity EV + information EV. The information EV is **0 when all-in** or against
opponents who don't read discards, and in those cases pure max-equity keeping is strictly optimal. Deception is only
worth considering within ~1.2% equity, and only vs TAG/LAG/GTO-type opponents (λ_info ≈ 0.012):
- **Kept hand is two pair or better:** prefer tossing a high card (signals weakness and induces bluffs).
- **Kept hand is not a flush draw:** avoid tossing a card of the flop's two-flush suit when we plan to check-call
  (it would announce that we are capped against flushes).

Cheap counter-measures:
- when two keeps are within ~1–2% equity, randomise between them;
- don't systematically toss the highest card only with monsters.

Against a weak field this barely matters. Low priority.

Status: todo.

## D5. All-in discards (P0)
When all-in before the discard, there is no more betting, so pure equity-max (D1) with more samples is exactly right.
Status: todo.
