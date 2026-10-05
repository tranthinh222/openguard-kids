"""Monotonic active-use accounting backed by SQLite."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

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
    ):
        self.repository = repository
        self.policy_provider = policy_provider
        self.active_probe = active_probe
        self.unlocked_probe = unlocked_probe
        self.locker = locker
        self.monotonic = monotonic
        self.now = now
        self.max_tick_seconds = max_tick_seconds
        self._previous = self.monotonic()
        self._lock_pending = False

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
            return TickResult(0, usage.used_seconds, available, False, "session_locked")
        if not policy.is_allowed_at(moment):
            self._lock_once(moment.date())
            return TickResult(0, usage.used_seconds, available, True, "outside_schedule")
        if available <= 0:
            self._lock_once(moment.date())
            return TickResult(0, usage.used_seconds, 0, True, "quota_exhausted")
        if not self.active_probe(policy.screen_time.idle_timeout_sec):
            return TickResult(0, usage.used_seconds, available, False, "idle")

        # A suspended process must not turn one stale tick into hours of usage.
        counted = min(delta, self.max_tick_seconds, available)
        usage = self.repository.add_usage(moment.date(), counted)
        remaining = max(0.0, quota - usage.used_seconds)
        should_lock = remaining <= 0
        if should_lock:
            self._lock_once(moment.date())
        return TickResult(counted, usage.used_seconds, remaining, should_lock, "quota_exhausted" if should_lock else "counted")

    def _lock_once(self, _day: date) -> None:
        if not self._lock_pending:
            self.locker()
            self._lock_pending = True
