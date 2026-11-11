"""Dispatch: owns the leg/hand state, the clock and the opponent model; calls the policies."""
import placeholder
from log import log, warn
from opponent import OppModel
from state import HandState, LegState
from timing import Clock


class Brain:
    def __init__(self):
        self.leg = LegState()
        self.hand = None
        self.opp = OppModel()
        self.clock = Clock(self.leg)

    # ----------------------------------------------------------------- events
    def on_init(self, msg):
        self.leg.configure(msg)

    def on_new_hand(self, msg):
        self.hand = HandState(msg.get("hand_id"), msg.get("seat"), msg.get("hole_cards"))

    def on_discard_result(self, msg):
        self._ensure_hand(msg).update_from_discard_result(msg)

    def on_hand_result(self, msg):
        self.leg.record(msg)
        self.opp.observe_showdown(msg)
        self.hand = None

    def on_notice(self, msg):
        self.leg.notices += 1
        warn("NOTICE from engine (a bug):", msg)

    def on_match_end(self, msg):
        log(f"leg done: hands {self.leg.hands_done} net {self.leg.net:+} notices {self.leg.notices}")

    # --------------------------------------------------------------- requests
    def act(self, req):
        self.clock.start(req)
        self._ensure_hand(req).update_from_request(req)
        return placeholder.v0_action(req)

    def discard(self, req):
        self.clock.start(req)
        hand = self._ensure_hand(req)
        hand.update_from_discard_request(req)
        return {"type": "discard", "card": placeholder.v0_discard(hand.hole_strs)}

    # ---------------------------------------------------------------- helpers
    def _ensure_hand(self, msg):
        """The current HandState; a minimal one if new_hand was missed or the hand id differs."""
        hid = msg.get("hand_id")
        if self.hand is None or self.hand.hand_id != hid:
            self.hand = HandState(hid)
        return self.hand
