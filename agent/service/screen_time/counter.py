"""Monotonic active-use accounting backed by SQLite."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from service.enforcement import EnforcementReason, WorkstationEnforcer
from service.policy.models import Policy


@dataclass(frozen=True)
class DailyUsage:
    date: str
    used_seconds: float
    bonus_seconds: int
    updated_at: str


@dataclass(frozen=True)
class TickResult:
    counted_seconds: float
    used_seconds: float
    available_seconds: float
    should_lock: bool
    reason: str
    events: tuple[dict, ...] = ()


class UsageRepository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mutex = threading.Lock()
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS usage_daily (
                    date TEXT PRIMARY KEY, used_seconds REAL NOT NULL DEFAULT 0,
                    bonus_seconds INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS warning_state (
                    date TEXT NOT NULL, policy_version INTEGER NOT NULL,
                    warning_minute INTEGER NOT NULL, sent_at TEXT NOT NULL,
                    PRIMARY KEY(date, policy_version, warning_minute)
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, day: date) -> DailyUsage:
        existing = self.get_if_exists(day)
        return existing or DailyUsage(day.isoformat(), 0.0, 0, datetime.now().astimezone().isoformat())

    def get_if_exists(self, day: date) -> DailyUsage | None:
        key = day.isoformat()
        with self._connect() as db:
            row = db.execute("SELECT * FROM usage_daily WHERE date=?", (key,)).fetchone()
        return None if row is None else DailyUsage(**dict(row))

    def add_usage(self, day: date, seconds: float) -> DailyUsage:
        key = day.isoformat()
        now = datetime.now().astimezone().isoformat()
        with self._mutex, self._connect() as db:
            db.execute(
                "INSERT INTO usage_daily(date, used_seconds, bonus_seconds, updated_at) VALUES (?, ?, 0, ?) "
                "ON CONFLICT(date) DO UPDATE SET used_seconds=used_seconds+excluded.used_seconds, updated_at=excluded.updated_at",
                (key, max(0.0, seconds), now),
            )
            row = db.execute("SELECT * FROM usage_daily WHERE date=?", (key,)).fetchone()
        return DailyUsage(**dict(row))

    def set_bonus(self, day: date, seconds: int) -> DailyUsage:
        key = day.isoformat()
        now = datetime.now().astimezone().isoformat()
        with self._mutex, self._connect() as db:
            db.execute(
                "INSERT INTO usage_daily(date, used_seconds, bonus_seconds, updated_at) VALUES (?, 0, ?, ?) "
                "ON CONFLICT(date) DO UPDATE SET bonus_seconds=excluded.bonus_seconds, updated_at=excluded.updated_at",
                (key, max(0, seconds), now),
            )
            row = db.execute("SELECT * FROM usage_daily WHERE date=?", (key,)).fetchone()
        return DailyUsage(**dict(row))

    def warning_sent(self, day: date, policy_version: int, minute: int) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM warning_state WHERE date=? AND policy_version=? AND warning_minute=?",
                (day.isoformat(), policy_version, minute),
            ).fetchone()
        return row is not None

    def mark_warning_sent(self, day: date, policy_version: int, minute: int) -> None:
        with self._mutex, self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO warning_state VALUES (?, ?, ?, ?)",
                (day.isoformat(), policy_version, minute, datetime.now().astimezone().isoformat()),
            )


class ScreenTimeCounter:
    def __init__(
        self,
        repository: UsageRepository,
        policy_provider: Callable[[], Policy | None],
        active_probe: Callable[[int], bool],
        unlocked_probe: Callable[[], bool],
        locker: Callable[[], bool],
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        max_tick_seconds: float = float("inf"),
        enforcer: WorkstationEnforcer | None = None,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.repository = repository
        self.policy_provider = policy_provider
        self.active_probe = active_probe
        self.unlocked_probe = unlocked_probe
        self.locker = locker
        self.monotonic = monotonic
        self.now = now
        self.max_tick_seconds = max_tick_seconds
        self.enforcer = enforcer
        self.on_event = on_event or (lambda _event: None)
        self._previous = self.monotonic()
        self._lock_pending = False
        self._grace_deadline: float | None = None

    def tick(self) -> TickResult:
        current_mono = self.monotonic()
        delta = max(0.0, current_mono - self._previous)
        self._previous = current_mono
        moment = self.now()
        policy = self.policy_provider()
        if policy is None:
            return TickResult(0, 0, 0, False, "no_policy")
        usage = self.repository.get(moment.date())
        quota = policy.quota_seconds_at(moment) + usage.bonus_seconds
        available = max(0.0, quota - usage.used_seconds)

        if not self.unlocked_probe():
            self._lock_pending = False
            if self.enforcer:
                self.enforcer.session_is_locked()
            return TickResult(0, usage.used_seconds, available, False, "session_locked")
        if not policy.is_allowed_at(moment):
            self._enforce(EnforcementReason.SCHEDULE_DISALLOWED)
            return TickResult(0, usage.used_seconds, available, True, "outside_schedule")
        if available <= 0:
            return self._quota_exhausted(policy, usage.used_seconds, current_mono)
        if not self.active_probe(policy.screen_time.idle_timeout_sec):
            return TickResult(0, usage.used_seconds, available, False, "idle")

        counted = min(delta, self.max_tick_seconds, available)
        usage = self.repository.add_usage(moment.date(), counted)
        remaining = max(0.0, quota - usage.used_seconds)
        events = self._warning_events(policy, moment.date(), available, remaining)
        if remaining <= 0:
            exhausted = self._quota_exhausted(policy, usage.used_seconds, current_mono)
            return TickResult(counted, usage.used_seconds, 0, exhausted.should_lock, exhausted.reason, events + exhausted.events)
        self._grace_deadline = None
        return TickResult(counted, usage.used_seconds, remaining, False, "counted", events)

    def _warning_events(self, policy: Policy, day: date, before: float, after: float) -> tuple[dict, ...]:
        events = []
        for minute in policy.screen_time.warning_minutes:
            threshold = minute * 60
            if before > threshold >= after and not self.repository.warning_sent(day, policy.version, minute):
                event = {"type": "TIME_WARNING", "minutes_remaining": minute}
                self.repository.mark_warning_sent(day, policy.version, minute)
                self.on_event(event)
                events.append(event)
        return tuple(events)

    def _quota_exhausted(self, policy: Policy, used: float, current_mono: float) -> TickResult:
        grace = policy.screen_time.grace_period_sec
        if grace > 0:
            if self._grace_deadline is None:
                self._grace_deadline = current_mono + grace
                event = {"type": "GRACE_STARTED", "seconds_remaining": grace}
                self.on_event(event)
                return TickResult(0, used, 0, False, "grace_period", (event,))
            remaining = max(0, int(self._grace_deadline - current_mono + 0.999))
            if current_mono < self._grace_deadline:
                return TickResult(0, used, 0, False, "grace_period", ({"type": "GRACE_TICK", "seconds_remaining": remaining},))
        self._enforce(EnforcementReason.QUOTA_EXHAUSTED)
        return TickResult(0, used, 0, True, "quota_exhausted")

    def _enforce(self, reason: EnforcementReason) -> None:
        if self.enforcer is not None:
            self.enforcer.enforce(reason)
        else:
            self._lock_once()

    def _lock_once(self) -> None:
        if not self._lock_pending:
            self.locker()
            self._lock_pending = True
