# W6: Opponent model and exploits

**Plans + implements:** Claude · **Reviews plans:** Codex · **Branch:** `ws/W6` · **Day:** Sat (W1 ships the neutral stub on Wed)

## Goal
Regularised per-leg opponent statistics and a soft archetype blend that shifts W4/W5 parameters, giving
clear gains vs station / maniac / nit bots without losing to the champion or to balanced opponents.

## Owns
`bot/opponent.py`, `tests/test_opponent.py`, `# --- W6 ---` in `bot/params.py`.

## Interfaces
`OppModel` per `agents/INTERFACES.md` (same API as the W1 stub). Feeds `range_weights` to W3/W5 and archetype
weights to W4/W5 parameter blending.

## Strategy items
06/M1 (track opportunities; separate bet/raise/call frequencies; prior strength 12–20 to tune; showdowns are
biased), M2 (archetype table + counters), M3 (adaptive targets), M4 (bounded exploits, fall back to the
baseline). Discard rationality τ feeds W3's β.

## Check two ways
1. Unit tests: stat estimates converge on synthetic action streams; priors dominate at n = 0; no division by zero.
2. Arena: classification accuracy vs each sparring bot after 30 / 60 hands (logged to stderr in debug mode);
   recovery when a bot switches style mid-leg (W7's switcher).

## Done when
- [ ] beats the champion head-to-head (z ≥ 2), gauntlet points ≥ champion's
