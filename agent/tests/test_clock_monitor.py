import sqlite3
from datetime import datetime, timezone

from service.clock import ClockMonitor
import pytest


def test_clock_drift_threshold_and_trusted_monotonic_time(tmp_path):
    mono = [10.0]
    local = [datetime(2026, 10, 5, 12, 2, 1, tzinfo=timezone.utc)]
    monitor = ClockMonitor(tmp_path / "agent.db", monotonic=lambda: mono[0], local_now=lambda: local[0])
    status = monitor.synchronize("2026-10-05T12:00:00Z")
    assert status.drifted is True
    assert status.drift_seconds == 121

    local[0] = datetime(2030, 1, 1, tzinfo=timezone.utc)
    mono[0] += 30
    assert monitor.trusted_now().astimezone(timezone.utc) == datetime(2026, 10, 5, 12, 0, 30, tzinfo=timezone.utc)
    with sqlite3.connect(tmp_path / "agent.db") as db:
        assert db.execute("SELECT COUNT(*) FROM clock_events").fetchone()[0] == 1


def test_clock_drift_at_threshold_is_not_an_event(tmp_path):
    monitor = ClockMonitor(
        tmp_path / "agent.db",
        local_now=lambda: datetime(2026, 10, 5, 12, 2, tzinfo=timezone.utc),
    )
    assert monitor.synchronize("2026-10-05T12:00:00Z").drifted is False


def test_restart_requires_new_sync_instead_of_trusting_changed_local_date(tmp_path):
    path = tmp_path / "agent.db"
    old = ClockMonitor(path)
    old.synchronize("2026-10-05T12:00:00Z")
    restarted = ClockMonitor(path, local_now=lambda: datetime(2040, 1, 1, tzinfo=timezone.utc))
    assert not restarted.ready
    with pytest.raises(RuntimeError, match="successful heartbeat"):
        restarted.trusted_now()


def test_server_classification_and_audit_use_server_time(tmp_path):
    path = tmp_path / "agent.db"
    monitor = ClockMonitor(path, local_now=lambda: datetime(2040, 1, 1, tzinfo=timezone.utc))
    status = monitor.synchronize("2026-10-05T12:00:00Z", clock_trusted=False,
                                 drift_seconds=31, threshold_seconds=30)
    assert status.drifted and status.drift_seconds == 31
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT created_at FROM clock_events").fetchone()[0] == "2026-10-05T12:00:00+00:00"
    assert not monitor.synchronize("2026-10-05T12:00:00Z", clock_trusted=True,
                                   drift_seconds=0, threshold_seconds=30).drifted
