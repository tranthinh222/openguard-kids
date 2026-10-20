from datetime import datetime

from service.policy.models import Policy
from service.policy.verifier import expected_signature
from service.screen_time import platform
from service.screen_time.counter import ScreenTimeCounter, UsageRepository


def _policy():
    payload = {
        "screen_time": {"weekday_minutes": 60, "weekend_minutes": 60, "idle_timeout_sec": 300,
                        "grace_period_sec": 0, "warning_minutes": []},
        "weekly_schedule": [True] * 336, "apps": [], "domains": [],
    }
    return Policy.from_envelope({"id": "p", "version": 1, "payload": payload,
                                 "signature": expected_signature(payload, 1, "secret")})


def test_idle_threshold_is_300_seconds(monkeypatch):
    monkeypatch.setattr(platform, "idle_seconds", lambda: 299)
    assert platform.is_user_active(300) is True
    monkeypatch.setattr(platform, "idle_seconds", lambda: 300)
    assert platform.is_user_active(300) is False


def test_resume_does_not_count_the_idle_gap(tmp_path):
    mono = [0.0]
    idle = [False]
    counter = ScreenTimeCounter(
        UsageRepository(tmp_path / "agent.db"), _policy,
        lambda _timeout: not idle[0], lambda: True, lambda: True,
        lambda: mono[0], lambda: datetime(2026, 10, 5, 12),
    )
    mono[0] = 10
    assert counter.tick().counted_seconds == 10
    idle[0], mono[0] = True, 310
    assert counter.tick().counted_seconds == 0
    idle[0], mono[0] = False, 311
    assert counter.tick().counted_seconds == 1
    assert counter.repository.get(datetime(2026, 10, 5).date()).used_seconds == 11
