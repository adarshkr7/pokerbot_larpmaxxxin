"""Dispatch: owns the leg/hand state, the clock and the opponent model; calls the policies."""
import random

import betting as betting_mod
import discard as discard_mod
import evaluator
import legal
import params
import placeholder
import preflop as preflop_mod
from cards import fmt
from log import log, log_exc, warn
from opponent import OppModel
from state import HandState, LegState
from timing import Clock

_warmed = False


def _warm_once():
    """Fill the evaluator's memo tables once per process, during the uncharged start-up (Brain() is built
    before the first message is read)."""
    global _warmed
    if _warmed:
        return
    _warmed = True
    try:
        evaluator.warm()
    except Exception:
        log_exc("evaluator.warm")


class Brain:
    def __init__(self):
        self.leg = LegState()
        self.hand = None
        self.opp = OppModel()
        self.clock = Clock(self.leg)
        self.rng = random.Random()
        _warm_once()

    # ----------------------------------------------------------------- events
    def on_init(self, msg):
        self.leg.configure(msg)

    def on_new_hand(self, msg):
        self.hand = HandState(msg.get("hand_id"), msg.get("seat"), msg.get("hole_cards"))

    def on_discard_result(self, msg):
        self._ensure_hand(msg).update_from_discard_result(msg)

    def on_hand_result(self, msg):
        self.leg.record(msg)
        try:                                     # a modelling bug must never affect play: swallow and log
            seat = self.hand.seat if self.hand is not None else None
            self.opp.observe_hand(msg, seat)
            pit = getattr(self.hand, "river_pit", None) if self.hand is not None else None
            if pit is not None:
                self.opp.observe_pit(msg, pit)
        except Exception:
            log_exc("opponent model")
        self.hand = None

    def on_notice(self, msg):
        self.leg.notices += 1
        warn("NOTICE from engine (a bug):", msg)

    def on_match_end(self, msg):
        log(f"leg done: hands {self.leg.hands_done} net {self.leg.net:+} notices {self.leg.notices}")

    # --------------------------------------------------------------- requests
    def act(self, req):
        self.clock.start(req)
        hand = self._ensure_hand(req)
        hand.update_from_request(req)
        if req.get("street") == "preflop":
            try:
                intent = preflop_mod.decide(req, hand, self.opp, rng=self.rng)
                if isinstance(intent, dict):
                    return intent
            except Exception:
                log_exc("preflop")
        elif req.get("street") in ("flop", "turn", "river"):
            try:
                intent = betting_mod.decide(req, hand, self.opp, self.clock, self.rng)
                if isinstance(intent, dict):
                    return intent
            except Exception:
                log_exc("betting")
        return placeholder.v0_action(req)        # the fallback for every street

    def discard(self, req):
        self.clock.start(req)
        hand = self._ensure_hand(req)
        hand.update_from_discard_request(req)
        try:
            if len(hand.hole3) == 3 and len(hand.hole_strs) == 3 and len(hand.board) == 3:
                betting = hand.my_stack > 0 and hand.opp_stack > 0
                budget = self.clock.budget_ms("discard")
                if not betting and budget > 0:     # D5: no later decisions in this hand
                    cap = min(params.MAX_DECISION_MS, params.MAX_DECISION_FRAC * self.leg.per_response_ms)
                    budget = min(budget * params.DISCARD_ALLIN_BUDGET_MULT, max(cap, budget))
                card = discard_mod.choose_discard(hand.hole3, hand.board, self.opp, hand.dead, budget, self.rng,
                                                  betting_possible=betting)
                return {"type": "discard", "card": fmt(card)}
        except Exception:
            log_exc("discard")
        try:
            return {"type": "discard", "card": placeholder.v0_discard(hand.hole_strs)}
        except Exception:
            return {"type": "discard", "card": legal.fallback_discard(hand.hole_strs)}

    # ---------------------------------------------------------------- helpers
    def _ensure_hand(self, msg):
        """The current HandState; a minimal one if new_hand was missed or the hand id differs."""
        hid = msg.get("hand_id")
        if self.hand is None or self.hand.hand_id != hid:
            self.hand = HandState(hid)
        return self.hand
