"""Server-anchored wall clock and clock-tampering audit."""

from __future__ import annotations

import sqlite3
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
# import os

# def agent_wall_now() -> datetime:
#     offset = 0.0
#     if os.getenv("ENVIRONMENT", "").lower() == "development":
#         offset = float(os.getenv("OGK_TEST_CLOCK_OFFSET_SEC", "0"))

#     return datetime.now(timezone.utc) + timedelta(seconds=offset)

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
        # local_now: Callable[[], datetime] = agent_wall_now,
    ):
        self.path = path
        self.threshold_seconds = threshold_seconds
        self.monotonic = monotonic
        self.local_now = local_now
        self._server_anchor: datetime | None = None
        self._mono_anchor: float | None = None
        self._mutex = threading.RLock()
        self.status: ClockStatus | None = None
        self._timezone = local_now().astimezone().tzinfo
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

    @property
    def ready(self) -> bool:
        with self._mutex:
            return self._server_anchor is not None

    def synchronize(self, server_time: str | datetime, *, clock_trusted: bool | None = None,
                    drift_seconds: float | None = None, threshold_seconds: float | None = None) -> ClockStatus:
        server = self._parse(server_time)
        local = self.local_now().astimezone(timezone.utc)
        drift = drift_seconds if drift_seconds is not None else (local - server).total_seconds()
        with self._mutex:
            if threshold_seconds is not None:
                self.threshold_seconds = threshold_seconds
            self._server_anchor = server
            self._mono_anchor = self.monotonic()
            drifted = not clock_trusted if clock_trusted is not None else abs(drift) > self.threshold_seconds
            self.status = ClockStatus(drift, drifted, server)
        if drifted:
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "INSERT INTO clock_events(local_time, server_time, drift_seconds, threshold_seconds, created_at) VALUES (?, ?, ?, ?, ?)",
                    (local.isoformat(), server.isoformat(), drift, self.threshold_seconds, server.isoformat()),
                )
        return ClockStatus(drift, drifted, server)

    def trusted_now(self) -> datetime:
        with self._mutex:
            if self._server_anchor is None or self._mono_anchor is None:
                raise RuntimeError("Trusted clock requires a successful heartbeat after startup")
            return (self._server_anchor + timedelta(seconds=max(0, self.monotonic() - self._mono_anchor))).astimezone(self._timezone)
