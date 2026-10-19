"""Where protection runs: inside the child's desktop session, or as a LocalSystem service."""

from __future__ import annotations

import threading
import time

from service.apps import monitor
from service.enforcement.workstation import _windows_lock
from service.screen_time.platform import is_session_unlocked, is_user_active
from service.windows import session as wts

# A tray idle report older than this is ignored; the tray reports every few seconds.
IDLE_REPORT_TTL_SEC = 15.0


class InteractiveHost:
    """Console `run` or development: the process already lives in the child's session."""

    name = "interactive"

    def active(self, idle_timeout_sec: int) -> bool:
        return is_user_active(idle_timeout_sec)

    def unlocked(self) -> bool:
        return is_session_unlocked()

    def lock(self) -> bool:
        return _windows_lock()

    def processes(self):
        return monitor.processes()


class IdleReports:
    """Idle seconds reported by the tray the service launched itself (others are ignored)."""

    def __init__(self, monotonic=time.monotonic):
        self.monotonic = monotonic
        self._mutex = threading.Lock()
        self._report: tuple[float, float] | None = None

    def report(self, idle_seconds: float) -> None:
        with self._mutex:
            self._report = max(0.0, float(idle_seconds)), self.monotonic()

    def idle_seconds(self) -> float | None:
        with self._mutex:
            if self._report is None:
                return None
            idle, received = self._report
            age = self.monotonic() - received
            return None if age > IDLE_REPORT_TTL_SEC else idle + age


class ServiceHost:
    """Session 0 service: probes, locks and scans the active console session through WTS.

    Without a fresh idle report from the tray, the child counts as active: losing the tray can
    only make the counter stricter, never give free time.
    """

    name = "windows_service"

    def __init__(self, idle: IdleReports | None = None, session=wts.active_console_session):
        self.idle = idle or IdleReports()
        self.session = session

    def active(self, idle_timeout_sec: int) -> bool:
        idle = self.idle.idle_seconds()
        return idle is None or idle < idle_timeout_sec

    def unlocked(self) -> bool:
        return wts.session_unlocked(self.session())

    def lock(self) -> bool:
        return wts.lock_session(self.session())

    def processes(self):
        current = self.session()
        return monitor.processes(target_session=current) if current is not None else iter(())
