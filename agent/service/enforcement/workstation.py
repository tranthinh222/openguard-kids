"""The single boundary for Windows workstation-lock enforcement."""

from __future__ import annotations

import ctypes
import logging
import os
import sqlite3
import time
import threading
import math
from dataclasses import dataclass, field
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


@dataclass
class _LockState:
    pending: bool = False
    session_locked: bool = False
    retry_after: float = 0.0
    last_reason: EnforcementReason | None = None
    last_requested_at: float | None = None
    mutex: object = field(default_factory=threading.RLock)


class WorkstationEnforcer:
    _states = {}
    _states_mutex = threading.Lock()

    def __init__(self, lock: Callable[[], bool] = _windows_lock, monotonic: Callable[[], float] = time.monotonic,
                 on_locked: Callable[[], None] | None = None, relock_delay_sec: float = 5.0,
                 state_key: Path | None = None):
        if not math.isfinite(relock_delay_sec) or relock_delay_sec < 0:
            raise ValueError('Relock delay must be finite and non-negative')
        self._lock = lock
        self._monotonic = monotonic
        self.relock_delay_sec = relock_delay_sec
        with self._states_mutex:
            self._state = (self._states.setdefault(str(state_key.resolve()).casefold(), _LockState())
                           if state_key is not None else _LockState())
        self.on_locked = on_locked

    @property
    def last_reason(self):
        return self._state.last_reason

    @property
    def last_requested_at(self):
        return self._state.last_requested_at

    @property
    def relock_remaining_seconds(self) -> int:
        with self._state.mutex:
            if self._state.pending or self._state.session_locked:
                return 0
            return max(0, math.ceil(self._state.retry_after - self._monotonic()))

    def enforce(self, reason: EnforcementReason, force: bool = False) -> bool:
        with self._state.mutex:
            state = self._state
            if state.pending and not force:
                return True
            requested_at = self._monotonic()
            # Accepted but deferred; the counter retries while the restriction remains.
            # force (remote commands) must not bypass the relock interval.
            if state.session_locked or requested_at < state.retry_after:
                return True
            success = self._lock()
            state.last_reason = reason
            state.last_requested_at = requested_at
            state.retry_after = requested_at + self.relock_delay_sec
            state.pending = success
            if not success:
                LOGGER.error("Failed to lock workstation; reason=%s", reason.value)
            elif self.on_locked:
                self.on_locked()
            return success

    def observe_session(self, unlocked: bool) -> None:
        with self._state.mutex:
            state = self._state
            if not unlocked:
                state.session_locked = True
                state.pending = False
            elif state.session_locked:
                state.session_locked = False
                if state.last_requested_at is not None:
                    state.retry_after = self._monotonic() + self.relock_delay_sec

    def session_is_locked(self) -> None:
        self.observe_session(False)

    def allow_unlock(self) -> None:
        # Windows requires the user to authenticate; this clears only Agent state.
        with self._state.mutex:
            self._state.pending = False
            self._state.last_reason = None
