"""Protocol loop: the only module that writes to stdout. Never raises, replies exactly once per request.

Design and failure layers: agents/plans/F01_engine_skeleton.md (section 3.1).
"""
import json
import os
import sys

PROTO = sys.stdout            # the engine's pipe, saved before anything else can write to it
sys.stdout = sys.stderr       # any stray print() anywhere goes to stderr, never to the engine

import brain as brain_mod     # noqa: E402  (after the redirect: import-time prints must not reach the pipe)
import legal                  # noqa: E402
from cards import is_valid    # noqa: E402
from log import log_exc       # noqa: E402

HANDLERS = {"init": "on_init", "new_hand": "on_new_hand", "discard_result": "on_discard_result",
            "hand_result": "on_hand_result", "notice": "on_notice"}
CONSTANT_REPLY = {"action_request": {"type": "action", "action": "check"},
                  "discard_request": {"type": "discard", "card": "2s"}}


def send(reply):
    try:
        PROTO.write(json.dumps(reply, separators=(",", ":")) + "\n")
        PROTO.flush()
    except (BrokenPipeError, OSError):
        os._exit(0)           # the engine is gone; nothing left to do


def dispatch(brain, name, msg):
    """Call brain.<name>(msg); a missing Brain, a missing handler or a raising handler never escapes."""
    if brain is None:
        return
    try:
        getattr(brain, name)(msg)
    except Exception:
        log_exc(name)


def respond_action(brain, req):
    intent = None
    if brain is not None:
        try:
            intent = brain.act(req)
        except Exception:
            log_exc("act")
    try:
        return legal.make_legal(intent, req)       # maps a None/unknown intent to fallback_action itself
    except Exception:
        log_exc("make_legal")
    try:
        legal_actions = legal.legal_list(req)
        ok = not legal_actions or "check" in legal_actions
        return {"type": "action", "action": "check" if ok else "fold"}
    except Exception:
        return {"type": "action", "action": "check"}


def respond_discard(brain, req):
    card = None
    if brain is not None:
        try:
            intent = brain.discard(req)
            card = intent.get("card") if isinstance(intent, dict) else intent
        except Exception:
            log_exc("discard")
    try:
        return legal.make_legal_discard(card, req)
    except Exception:
        log_exc("make_legal_discard")
    try:
        hole = req.get("hole_cards")
        hole = hole if isinstance(hole, list) else []
        valid = [c for c in hole if is_valid(c)]
        if valid:
            return {"type": "discard", "card": valid[0]}
        return {"type": "discard", "card": hole[0] if hole and isinstance(hole[0], str) else "2s"}
    except Exception:
        return {"type": "discard", "card": "2s"}


def main():
    try:
        sys.stdin.reconfigure(errors="replace")   # a bad byte must not raise inside the line iterator
    except Exception:
        pass
    brain = None
    try:
        brain = brain_mod.Brain()
    except Exception:
        log_exc("Brain()")
    for raw in sys.stdin:
        pending = None            # request type still owed a reply
        try:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            if not isinstance(t, str):
                continue
            if t == "action_request":
                pending = t
                send(respond_action(brain, msg))
                pending = None
            elif t == "discard_request":
                pending = t
                send(respond_discard(brain, msg))
                pending = None
            elif t == "match_end":
                dispatch(brain, "on_match_end", msg)
                break
            elif t in HANDLERS:
                dispatch(brain, HANDLERS[t], msg)
            # anything else: ignored (forward compatibility)
        except Exception:
            log_exc("loop")
            if pending is not None:
                send(CONSTANT_REPLY[pending])


if __name__ == "__main__":
    main()
