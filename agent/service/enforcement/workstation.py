"""The single boundary for Windows workstation-lock enforcement."""

from __future__ import annotations

import ctypes
import logging
import os
import sqlite3
import time
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger("openguard-agent.enforcement")


class EnforcementReason(StrEnum):
    QUOTA_EXHAUSTED = "quota_exhausted"
    SCHEDULE_DISALLOWED = "schedule_disallowed"
    REMOTE_LOCK = "remote_lock"
    CLOCK_UNVERIFIED = "clock_unverified"


def _windows_lock() -> bool:
    return os.name == "nt" and bool(ctypes.windll.user32.LockWorkStation())


class RemoteLockRepository:
    """Persist a parent's LOCK_NOW so it survives unlock attempts and Agent restarts."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS remote_lock (
                    id INTEGER PRIMARY KEY CHECK (id = 1), active INTEGER NOT NULL, updated_at TEXT NOT NULL
                )
            """)

    def active(self) -> bool:
        with sqlite3.connect(self.path, timeout=10) as db:
            row = db.execute("SELECT active FROM remote_lock WHERE id=1").fetchone()
        return bool(row and row[0])

    def set(self, active: bool) -> None:
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute(
                "INSERT INTO remote_lock(id, active, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET active=excluded.active, updated_at=excluded.updated_at",
                (int(active), datetime.now().astimezone().isoformat()),
            )


class WorkstationEnforcer:
    def __init__(self, lock: Callable[[], bool] = _windows_lock, monotonic: Callable[[], float] = time.monotonic):
        self._lock = lock
        self._monotonic = monotonic
        self._pending = False
        self.last_reason: EnforcementReason | None = None
        self.last_requested_at: float | None = None

    def enforce(self, reason: EnforcementReason, force: bool = False) -> bool:
        if self._pending and not force:
            return True
        requested_at = self._monotonic()
        success = self._lock()
        self.last_reason = reason
        self.last_requested_at = requested_at
        self._pending = success
        if not success:
            LOGGER.error("Failed to lock workstation; reason=%s", reason.value)
        return success

    def session_is_locked(self) -> None:
        self._pending = False

    def allow_unlock(self) -> None:
        # Windows requires the user to authenticate; this clears only Agent state.
        self._pending = False
        self.last_reason = None
