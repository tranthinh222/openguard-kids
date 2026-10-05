import sqlite3

import pytest

from service.policy import PolicyManager, PolicyRejectedError, PolicyRepository
from service.policy.verifier import expected_signature


def envelope(version=1, weekday_minutes=3):
    payload = {
        "screen_time": {
            "weekday_minutes": weekday_minutes,
            "weekend_minutes": 3,
            "idle_timeout_sec": 300,
            "grace_period_sec": 0,
            "warning_minutes": [1],
        },
        "weekly_schedule": [True] * 336,
        "apps": [],
        "domains": [],
    }
    return {
        "id": f"policy-{version}",
        "version": version,
        "payload": payload,
        "signature": expected_signature(payload, version, "secret"),
    }


def test_valid_policy_is_saved_and_activated(tmp_path):
    manager = PolicyManager(PolicyRepository(tmp_path / "agent.db"), "secret")
    accepted = manager.accept(envelope(version=2))
    assert accepted.version == 2
    assert manager.current.version == 2


def test_bad_signature_keeps_last_known_good_and_logs_security_event(tmp_path):
    path = tmp_path / "agent.db"
    manager = PolicyManager(PolicyRepository(path), "secret")
    manager.accept(envelope(version=1))
    forged = envelope(version=2)
    forged["signature"] = "0" * 64

    with pytest.raises(PolicyRejectedError):
        manager.accept(forged)

    assert manager.current.version == 1
    with sqlite3.connect(path) as db:
        event = db.execute("SELECT event_type FROM security_events ORDER BY id DESC").fetchone()
    assert event == ("POLICY_REJECTED",)


def test_schema_error_keeps_last_known_good(tmp_path):
    manager = PolicyManager(PolicyRepository(tmp_path / "agent.db"), "secret")
    manager.accept(envelope(version=1))
    invalid = envelope(version=2)
    invalid["payload"]["weekly_schedule"] = [True]
    invalid["signature"] = expected_signature(invalid["payload"], 2, "secret")
    with pytest.raises(PolicyRejectedError):
        manager.accept(invalid)
    assert manager.current.version == 1
