"""Test-only wrapper: runs bot/bot.py's main() with a sabotaged Brain. Mode from env PATCH_MODE.

  init_raises  Brain() raises in its constructor (bot must still answer every request and exit 0)
  act_raises   Brain.act and Brain.discard raise on every call
  always_raise Brain.act always intends {"action": "raise", "amount": 999}
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))

import bot  # noqa: E402  (redirects stdout to stderr, as in production)
import brain  # noqa: E402

MODE = os.environ.get("PATCH_MODE", "")


def _boom(*args, **kwargs):
    raise RuntimeError(f"sabotaged by patched_bot ({MODE})")


if MODE == "init_raises":
    brain.Brain.__init__ = _boom
elif MODE == "act_raises":
    brain.Brain.act = _boom
    brain.Brain.discard = _boom
elif MODE == "always_raise":
    brain.Brain.act = lambda self, req: {"action": "raise", "amount": 999}

bot.main()
