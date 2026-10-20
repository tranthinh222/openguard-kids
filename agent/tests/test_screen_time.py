from datetime import datetime

from service.policy.models import Policy
from service.policy.verifier import expected_signature
from service.screen_time.counter import ScreenTimeCounter, UsageRepository


def policy(quota_minutes=3, schedule=None):
    payload = {
        "screen_time": {
            "weekday_minutes": quota_minutes,
            "weekend_minutes": quota_minutes,
            "idle_timeout_sec": 300,
            "grace_period_sec": 0,
            "warning_minutes": [1],
        },
        "weekly_schedule": schedule or [True] * 336,
        "apps": [],
        "domains": [],
    }
    return Policy.from_envelope({
        "id": "p1", "version": 1, "payload": payload,
        "signature": expected_signature(payload, 1, "secret"),
    })


def test_three_minutes_active_usage_locks(tmp_path):
    clock = [0.0]
    locks = []
    counter = ScreenTimeCounter(
        UsageRepository(tmp_path / "agent.db"), lambda: policy(), lambda _timeout: True,
        lambda: True, lambda: locks.append(True) or True, lambda: clock[0],
        lambda: datetime(2026, 10, 5, 12, 0), max_tick_seconds=30,
    )
    result = None
    for _ in range(6):
        clock[0] += 30
        result = counter.tick()
    assert result.used_seconds == 180
    assert result.should_lock is True
    assert len(locks) == 1


def test_idle_and_locked_time_are_not_counted(tmp_path):
    clock = [0.0]
    active = [False]
    unlocked = [True]
    counter = ScreenTimeCounter(
        UsageRepository(tmp_path / "agent.db"), lambda: policy(), lambda _timeout: active[0],
        lambda: unlocked[0], lambda: True, lambda: clock[0], lambda: datetime(2026, 10, 5, 12, 0),
    )
    clock[0] = 10
    assert counter.tick().counted_seconds == 0
    active[0], unlocked[0], clock[0] = True, False, 20
    assert counter.tick().counted_seconds == 0
    unlocked[0], clock[0] = True, 30
    assert counter.tick().counted_seconds == 10


def test_outside_schedule_locks_without_counting(tmp_path):
    schedule = [False] * 336
    locks = []
    clock = [0.0]
    counter = ScreenTimeCounter(
        UsageRepository(tmp_path / "agent.db"), lambda: policy(schedule=schedule), lambda _timeout: True,
        lambda: True, lambda: locks.append(True) or True, lambda: clock[0], lambda: datetime(2026, 10, 5, 12, 0),
    )
    clock[0] = 1
    result = counter.tick()
    assert result.reason == "outside_schedule"
    assert result.used_seconds == 0
    assert locks == [True]
