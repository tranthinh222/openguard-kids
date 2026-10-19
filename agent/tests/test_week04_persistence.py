"""Week 04 A3/A4: trusted clock and grace state survive Agent/Service restarts."""
import sqlite3
from datetime import datetime, timedelta, timezone

from service.clock import ClockMonitor
from service.enforcement import WorkstationEnforcer
from service.policy.models import Policy
from service.policy.verifier import expected_signature
from service.screen_time.counter import ScreenTimeCounter, UsageRepository

SERVER = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def make_policy(quota=1, grace=60):
    payload = {
        "screen_time": {"weekday_minutes": quota, "weekend_minutes": quota, "idle_timeout_sec": 300,
                        "grace_period_sec": grace, "warning_minutes": []},
        "weekly_schedule": [True] * 336, "apps": [], "domains": [],
    }
    return Policy.from_envelope({"id": "p", "version": 1, "payload": payload,
                                 "signature": expected_signature(payload, 1, "secret")})


def test_reboot_offline_uses_floor_so_rollback_cannot_go_back(tmp_path):
    path = tmp_path / "agent.db"
    mono = [500.0]
    ClockMonitor(path, monotonic=lambda: mono[0], boot_id=lambda: "boot-1", local_now=lambda: SERVER).synchronize(SERVER)
    # Child rolls the clock back three hours and reboots while the server is unreachable.
    mono[0] = 5.0
    rebooted = ClockMonitor(path, monotonic=lambda: mono[0], boot_id=lambda: "boot-2",
                            local_now=lambda: SERVER - timedelta(hours=3))
    assert rebooted.mode == "provisional" and rebooted.ready and not rebooted.verified
    assert rebooted.trusted_now().astimezone(timezone.utc) == SERVER
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM clock_events").fetchone()[0] == 1


def test_provisional_clock_ignores_wall_changes_after_start(tmp_path):
    path = tmp_path / "agent.db"
    ClockMonitor(path, boot_id=lambda: "boot-1").synchronize(SERVER)
    wall, mono = [SERVER + timedelta(hours=8)], [0.0]
    monitor = ClockMonitor(path, monotonic=lambda: mono[0], boot_id=lambda: "boot-2", local_now=lambda: wall[0])
    wall[0] += timedelta(days=1)
    mono[0] = 30
    assert monitor.trusted_now().astimezone(timezone.utc) == SERVER + timedelta(hours=8, seconds=30)


def test_floor_advances_and_server_sync_replaces_provisional_floor(tmp_path):
    path = tmp_path / "agent.db"
    mono = [0.0]
    monitor = ClockMonitor(path, monotonic=lambda: mono[0], boot_id=lambda: "boot-1")
    monitor.synchronize(SERVER)
    mono[0] = 3600
    monitor.trusted_now()  # checkpoint
    with sqlite3.connect(path) as db:
        floor = db.execute("SELECT floor_time FROM clock_anchor").fetchone()[0]
    assert datetime.fromisoformat(floor) == SERVER + timedelta(hours=1)

    ahead = ClockMonitor(path, monotonic=lambda: 0.0, boot_id=lambda: "boot-2",
                         local_now=lambda: SERVER + timedelta(days=2))
    ahead.trusted_now()
    ahead.synchronize(SERVER + timedelta(hours=2))
    with sqlite3.connect(path) as db:
        floor = db.execute("SELECT floor_time FROM clock_anchor").fetchone()[0]
    assert datetime.fromisoformat(floor) == SERVER + timedelta(hours=2)


def _counter(path, mono, now, locks, events=None):
    enforcer = WorkstationEnforcer(lock=lambda: locks.append(True) or True, monotonic=lambda: mono[0])
    return ScreenTimeCounter(UsageRepository(path), lambda: make_policy(), lambda _x: True, lambda: True,
                             lambda: True, lambda: mono[0], lambda: now[0], enforcer=enforcer,
                             on_event=(events if events is not None else []).append)


def test_restart_during_grace_does_not_grant_new_grace(tmp_path):
    path, locks, events = tmp_path / "agent.db", [], []
    mono, now = [0.0], [SERVER]
    UsageRepository(path).add_usage(SERVER.date(), 60)
    first = _counter(path, mono, now, locks, events)
    assert first.tick().reason == "grace_period"
    assert events[-1] == {"type": "GRACE_STARTED", "seconds_remaining": 60}

    # Service killed 40 seconds into grace and restarted by SCM with a fresh monotonic origin.
    mono[0], now[0] = 1000.0, SERVER + timedelta(seconds=40)
    restarted = _counter(path, mono, now, locks, events)
    result = restarted.tick()
    assert result.reason == "grace_period"
    assert events[-1] == {"type": "GRACE_STARTED", "seconds_remaining": 20, "resumed": True}
    mono[0], now[0] = 1020.0, SERVER + timedelta(seconds=60)
    assert restarted.tick().should_lock and locks == [True]


def test_restart_after_grace_expired_locks_immediately(tmp_path):
    path, locks = tmp_path / "agent.db", []
    mono, now = [0.0], [SERVER]
    UsageRepository(path).add_usage(SERVER.date(), 60)
    _counter(path, mono, now, locks).tick()
    now[0] = SERVER + timedelta(minutes=10)
    result = _counter(path, mono, now, locks).tick()
    assert result.should_lock and result.reason == "quota_exhausted" and locks == [True]


def test_bonus_time_clears_grace_so_next_exhaustion_has_grace(tmp_path):
    path, locks = tmp_path / "agent.db", []
    mono, now = [0.0], [SERVER]
    repository = UsageRepository(path)
    repository.add_usage(SERVER.date(), 60)
    counter = _counter(path, mono, now, locks)
    counter.tick()
    repository.set_bonus(SERVER.date(), 900)
    mono[0], now[0] = 1.0, SERVER + timedelta(seconds=1)
    assert counter.tick().reason == "counted"
    assert repository.grace_deadline(SERVER.date()) is None
