"""Per-decision clock and time tiers (02/E5). Constants live in params.py."""
import math
import time

import params

_now = time.perf_counter      # module attribute so tests can substitute a fake clock


def _finite_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class Clock:
    def __init__(self, leg):
        self.leg = leg
        self.t0 = _now()
        self.time_left = float(leg.time_bank_ms)
        self.hand_id = 1
        self._last_known = None   # last time_left_ms received in this leg
        self._last_hand = None

    def start(self, req):
        """Start timing a decision.

        Missing-clock policy (F01 plan 3.6): a finite time_left_ms is used as is (<= 0 counts as 0);
        absent or non-numeric -> the last value received in this leg, else the full bank.
        """
        self.t0 = _now()
        hid = req.get("hand_id")
        if isinstance(hid, int) and not isinstance(hid, bool):
            self._last_hand = hid
        self.hand_id = self._last_hand if self._last_hand is not None else 1
        tl = req.get("time_left_ms")
        if _finite_number(tl):
            tl = max(0.0, float(tl))
            self._last_known = tl
        elif self._last_known is not None:
            tl = self._last_known
        else:
            tl = float(self.leg.time_bank_ms)
        self.time_left = tl

    @property
    def remaining_hands(self):
        return max(1, int(self.leg.total_hands) - self.hand_id + 1)

    @property
    def reserve_ms(self):
        return max(params.RESERVE_MIN_MS, params.RESERVE_FRAC * self.leg.time_bank_ms)

    @property
    def per_hand_ms(self):
        return max(0.0, self.time_left - self.reserve_ms) / self.remaining_hands

    def tier(self):
        per_hand = self.per_hand_ms
        if self.time_left < params.PANIC_BANK_MULT * self.reserve_ms or per_hand < params.PANIC_PER_HAND_MS:
            return "panic"
        if per_hand < params.THROTTLE_PER_HAND_MS:
            return "throttle"
        return "normal"

    def budget_ms(self, kind):
        tier = self.tier()
        if tier == "panic":
            return 0.0
        b = self.per_hand_ms * params.SHARE.get(kind, 0.0) * params.TARGET_USE
        if tier == "throttle":
            b *= params.THROTTLE_MULT
        cap = min(params.MAX_DECISION_MS, params.MAX_DECISION_FRAC * self.leg.per_response_ms)
        return min(max(b, 0.0), cap)

    def elapsed_ms(self):
        return (_now() - self.t0) * 1000.0

    def expired(self, budget_ms):
        return self.elapsed_ms() >= budget_ms
