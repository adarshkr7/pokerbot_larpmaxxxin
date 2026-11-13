"""Test-only wrapper: runs bot/bot.py's main() with a sabotaged Brain. Mode from env PATCH_MODE.

  init_raises  Brain() raises in its constructor (bot must still answer every request and exit 0)
  act_raises   Brain.act and Brain.discard raise on every call
  always_raise Brain.act always intends {"action": "raise", "amount": 999}
  v0_discard   Brain.discard is the frozen v0 (toss-lowest) discard: everything else is our real bot, so a
               match against the champion isolates every change except the discard (tests C1 / C2)
  v0_preflop   preflop decisions are the frozen v0 check/call (placeholder.v0_action) instead of preflop.decide
  v0_postflop  flop / turn / river decisions are the frozen v0 check/call instead of betting.decide
  stub_opp     the opponent model never learns (a fresh OppModel, i.e. neutral, all hand long): isolates the
               opponent model (06) from everything else
  size_blind   B7 range narrowing ignores the bet size again (every bet / raise tilts as a 2/3-pot bet)
Modes combine with commas, e.g. PATCH_MODE=v0_discard,v0_preflop,v0_postflop (C1 / C2 isolate everything else that is new).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))

import bot  # noqa: E402  (redirects stdout to stderr, as in production)
import brain  # noqa: E402
import placeholder  # noqa: E402

MODE = os.environ.get("PATCH_MODE", "")
MODES = set(MODE.split(","))


def _boom(*args, **kwargs):
    raise RuntimeError(f"sabotaged by patched_bot ({MODE})")


if MODE == "init_raises":
    brain.Brain.__init__ = _boom
elif MODE == "act_raises":
    brain.Brain.act = _boom
    brain.Brain.discard = _boom
elif MODE == "always_raise":
    brain.Brain.act = lambda self, req: {"action": "raise", "amount": 999}
if "v0_discard" in MODES:
    def _v0_discard(self, req):
        self.clock.start(req)
        hand = self._ensure_hand(req)
        hand.update_from_discard_request(req)
        return {"type": "discard", "card": placeholder.v0_discard(hand.hole_strs)}
    brain.Brain.discard = _v0_discard
if "v0_preflop" in MODES:
    import preflop  # noqa: E402
    preflop.decide = lambda req, hand_state=None, opp=None, rng=None: placeholder.v0_action(req)
if "stub_opp" in MODES:
    import opponent  # noqa: E402

    class _NeutralOpp(opponent.OppModel):
        def observe_hand(self, msg, seat=None):
            return None
    brain.OppModel = _NeutralOpp
if "size_blind" in MODES:
    import betting  # noqa: E402
    betting.size_mult = lambda x, allin=False, damp=1.0: 1.0
if "v0_postflop" in MODES:
    import betting  # noqa: E402
    betting.decide = lambda req, hand_state=None, opp=None, clock=None, rng=None: placeholder.v0_action(req)

bot.main()
