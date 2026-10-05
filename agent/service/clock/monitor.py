"""Server-anchored wall clock and clock-tampering audit."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ClockStatus:
    drift_seconds: float
    drifted: bool
    trusted_time: datetime


class ClockMonitor:
    def __init__(
        self,
        path: Path,
        threshold_seconds: float = 120,
        monotonic: Callable[[], float] = time.monotonic,
        local_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.path = path
        self.threshold_seconds = threshold_seconds
        self.monotonic = monotonic
        self.local_now = local_now
        self._server_anchor: datetime | None = None
        self._mono_anchor: float | None = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS clock_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, local_time TEXT NOT NULL,
                    server_time TEXT NOT NULL, drift_seconds REAL NOT NULL,
                    threshold_seconds REAL NOT NULL, created_at TEXT NOT NULL
                )
            """)

    @staticmethod
    def _parse(value: str | datetime) -> datetime:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if moment.tzinfo is None:
            raise ValueError("server_time must include a timezone")
        return moment.astimezone(timezone.utc)

    def synchronize(self, server_time: str | datetime) -> ClockStatus:
        server = self._parse(server_time)
        local = self.local_now().astimezone(timezone.utc)
        drift = (local - server).total_seconds()
        self._server_anchor = server
        self._mono_anchor = self.monotonic()
        if abs(drift) > self.threshold_seconds:
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "INSERT INTO clock_events(local_time, server_time, drift_seconds, threshold_seconds, created_at) VALUES (?, ?, ?, ?, ?)",
                    (local.isoformat(), server.isoformat(), drift, self.threshold_seconds, datetime.now(timezone.utc).isoformat()),
                )
        return ClockStatus(drift, abs(drift) > self.threshold_seconds, server)

    def trusted_now(self) -> datetime:
        if self._server_anchor is None or self._mono_anchor is None:
            return self.local_now().astimezone()
        return (self._server_anchor + timedelta(seconds=max(0, self.monotonic() - self._mono_anchor))).astimezone()
