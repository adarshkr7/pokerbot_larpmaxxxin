"""Clock and tiers (F01 plan 3.6 and 6D), with the single missing-clock policy."""
import math

import pytest

import params
import timing
from state import LegState
from timing import Clock


def leg(stage=1):
    lg = LegState()
    lg.configure({"total_hands": 200 if stage == 1 else 500,
                  "time_bank_ms": 30000 if stage == 1 else 75000, "per_response_ms": 5000})
    return lg


def clock_at(time_left, hand_id, stage=1):
    c = Clock(leg(stage))
    req = {"hand_id": hand_id}
    if time_left is not None:
        req["time_left_ms"] = time_left
    c.start(req)
    return c


def test_stage_values():
    c1 = clock_at(30000, 1, stage=1)
    assert c1.reserve_ms == 2400
    assert c1.per_hand_ms == pytest.approx(138.0)
    assert c1.tier() == "normal"
    c2 = clock_at(75000, 1, stage=2)
    assert c2.reserve_ms == 6000
    assert c2.per_hand_ms == pytest.approx(138.0)
    assert c2.tier() == "normal"


@pytest.mark.parametrize("time_left, hand_id, per_hand, tier", [
    (2999, 200, 599, "panic"),        # bank condition, even with ample per-hand time
    (3000, 200, 600, "normal"),       # boundary: 3,000 is not < 1.25 x 2,400
    (3000, 100, 600 / 101, "panic"),  # per-hand condition (< 25 ms)
    (6000, 101, 36, "throttle"),      # 25 <= 36 < 80
])
def test_tier_table(time_left, hand_id, per_hand, tier):
    c = clock_at(time_left, hand_id)
    assert c.per_hand_ms == pytest.approx(per_hand)
    assert c.tier() == tier


def test_absent_time_uses_last_known_value():
    c = Clock(leg())
    c.start({"hand_id": 199, "time_left_ms": 2999})
    c.start({"hand_id": 200})
    assert c.time_left == 2999
    assert c.per_hand_ms == pytest.approx(599)
    assert c.tier() == "panic"


def test_absent_on_first_request_uses_full_bank():
    c = clock_at(None, 1)
    assert c.time_left == 30000
    assert c.per_hand_ms == pytest.approx(138.0)
    assert c.tier() == "normal"


@pytest.mark.parametrize("bad", ["abc", float("nan"), float("inf"), None, True, [1]])
def test_non_numeric_time_is_same_as_absent(bad):
    c = Clock(leg())
    c.start({"hand_id": 1, "time_left_ms": bad})
    assert c.time_left == 30000
    c.start({"hand_id": 2, "time_left_ms": 12000})
    c.start({"hand_id": 3, "time_left_ms": bad})
    assert c.time_left == 12000


@pytest.mark.parametrize("value", [0, -1, -50000])
def test_zero_or_negative_time_is_panic_with_zero_budget(value):
    c = clock_at(value, 50)
    assert c.tier() == "panic"
    for kind in params.SHARE:
        assert c.budget_ms(kind) == 0.0


def test_missing_hand_id_uses_last_seen_else_one():
    c = Clock(leg())
    c.start({"time_left_ms": 30000})
    assert c.hand_id == 1 and c.remaining_hands == 200
    c.start({"hand_id": 150, "time_left_ms": 30000})
    c.start({"time_left_ms": 30000})
    assert c.hand_id == 150 and c.remaining_hands == 51


def test_budgets_never_negative_and_capped():
    cap = min(params.MAX_DECISION_MS, params.MAX_DECISION_FRAC * 5000)
    for stage in (1, 2):
        for time_left in (-5, 0, 1000, 3000, 6000, 20000, 75000, 10 ** 9):
            for hand_id in (1, 100, 199, 200, 500, 900):
                c = clock_at(time_left, hand_id, stage)
                for kind in list(params.SHARE) + ["unknown"]:
                    b = c.budget_ms(kind)
                    assert 0.0 <= b <= cap and math.isfinite(b)


def test_budget_values_stage1_normal_and_throttle():
    c = clock_at(30000, 1)
    assert c.budget_ms("discard") == pytest.approx(138 * 0.30 * 0.65)
    c = clock_at(6000, 101)
    assert c.budget_ms("flop") == pytest.approx(36 * 0.25 * 0.65 * 0.5)


def test_expired_with_fake_clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(timing, "_now", lambda: now[0])
    c = Clock(leg())
    c.start({"hand_id": 1, "time_left_ms": 30000})
    now[0] += 0.0049
    assert not c.expired(5.0)
    assert c.elapsed_ms() == pytest.approx(4.9)
    now[0] += 0.0002
    assert c.expired(5.0)
