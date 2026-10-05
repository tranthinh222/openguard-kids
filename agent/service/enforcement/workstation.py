"""The single boundary for Windows workstation-lock enforcement."""

from __future__ import annotations

import ctypes
import logging
import os
import time
from enum import StrEnum
from typing import Callable

LOGGER = logging.getLogger("openguard-agent.enforcement")


class EnforcementReason(StrEnum):
    QUOTA_EXHAUSTED = "quota_exhausted"
    SCHEDULE_DISALLOWED = "schedule_disallowed"
    REMOTE_LOCK = "remote_lock"


def _windows_lock() -> bool:
    return os.name == "nt" and bool(ctypes.windll.user32.LockWorkStation())


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
