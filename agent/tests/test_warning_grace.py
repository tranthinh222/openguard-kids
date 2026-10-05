from datetime import datetime

from service.enforcement import WorkstationEnforcer
from service.policy.models import Policy
from service.policy.verifier import expected_signature
from service.screen_time.counter import ScreenTimeCounter, UsageRepository


def make_policy(quota=11, grace=60):
    payload = {
        "screen_time": {"weekday_minutes": quota, "weekend_minutes": quota, "idle_timeout_sec": 300,
                        "grace_period_sec": grace, "warning_minutes": [10, 5, 1]},
        "weekly_schedule": [True] * 336, "apps": [], "domains": [],
    }
    return Policy.from_envelope({"id": "p", "version": 1, "payload": payload,
                                 "signature": expected_signature(payload, 1, "secret")})


def test_warnings_are_once_per_day_and_survive_new_counter(tmp_path):
    mono = [0.0]
    events = []
    repository = UsageRepository(tmp_path / "agent.db")
    args = dict(repository=repository, policy_provider=lambda: make_policy(), active_probe=lambda _x: True,
                unlocked_probe=lambda: True, locker=lambda: True, monotonic=lambda: mono[0],
                now=lambda: datetime(2026, 10, 5, 12), on_event=events.append)
    counter = ScreenTimeCounter(**args)
    mono[0] = 61
    assert [event["minutes_remaining"] for event in counter.tick().events] == [10]
    restarted = ScreenTimeCounter(**args)
    mono[0] += 1
    assert restarted.tick().events == ()


def test_grace_uses_monotonic_then_locks(tmp_path):
    mono = [0.0]
    locks = []
    repository = UsageRepository(tmp_path / "agent.db")
    enforcer = WorkstationEnforcer(lock=lambda: locks.append(True) or True, monotonic=lambda: mono[0])
    counter = ScreenTimeCounter(repository, lambda: make_policy(quota=1, grace=60), lambda _x: True,
                                lambda: True, lambda: True, lambda: mono[0],
                                lambda: datetime(2026, 10, 5, 12), enforcer=enforcer)
    mono[0] = 60
    first = counter.tick()
    assert first.reason == "grace_period" and not first.should_lock
    mono[0] = 119
    assert counter.tick().reason == "grace_period"
    mono[0] = 120
    assert counter.tick().should_lock is True
    assert locks == [True]
