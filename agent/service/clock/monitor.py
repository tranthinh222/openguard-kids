"""Server-anchored wall clock, persisted across restarts, and clock-tampering audit."""

from __future__ import annotations

import os
import sqlite3
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

# How often trusted_now() persists the last trusted timestamp (the anti-rollback floor).
CHECKPOINT_INTERVAL_SEC = 10.0


@dataclass(frozen=True)
class ClockStatus:
    drift_seconds: float
    drifted: bool
    trusted_time: datetime


def current_boot_id() -> str | None:
    """Identify this OS boot so a monotonic anchor is only reused within the same boot."""
    if os.name == "nt":
        try:
            import winreg
            key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                return "win:" + str(winreg.QueryValueEx(handle, "BootId")[0])
        except OSError:
            return None
    try:
        return "linux:" + Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


class ClockMonitor:
    """Trusted time = last server anchor + monotonic seconds elapsed since that anchor.

    Modes: ``server`` (heartbeat in this process), ``restored`` (server anchor persisted by an
    earlier process in the same boot), ``provisional`` (after reboot without server: wall clock,
    never earlier than the last persisted trusted timestamp). ``None`` until one is available.
    """

    def __init__(
        self,
        path: Path,
        threshold_seconds: float = 120,
        monotonic: Callable[[], float] = time.monotonic,
        local_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        report_timezone=None,
        boot_id: Callable[[], str | None] = current_boot_id,
        allow_provisional: bool = True,
    ):
        self.path = path
        self.threshold_seconds = threshold_seconds
        self.monotonic = monotonic
        self.local_now = local_now
        self._server_anchor: datetime | None = None
        self._mono_anchor: float | None = None
        self._mode: str | None = None
        self._last_checkpoint = float("-inf")
        self._mutex = threading.RLock()
        self.status: ClockStatus | None = None
        self._timezone = report_timezone or local_now().astimezone().tzinfo
        self._boot_id = boot_id()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS clock_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, local_time TEXT NOT NULL,
                    server_time TEXT NOT NULL, drift_seconds REAL NOT NULL,
                    threshold_seconds REAL NOT NULL, created_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS clock_anchor (
                    id INTEGER PRIMARY KEY CHECK (id = 1), server_time TEXT NOT NULL,
                    mono REAL NOT NULL, boot_id TEXT, floor_time TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            row = db.execute("SELECT server_time, mono, boot_id, floor_time FROM clock_anchor WHERE id=1").fetchone()
        if row is not None:
            self._restore(*row, allow_provisional=allow_provisional)

    def _restore(self, server_time: str, mono: float, boot_id: str | None, floor_time: str, allow_provisional: bool) -> None:
        now_mono = self.monotonic()
        if boot_id is not None and boot_id == self._boot_id and now_mono >= mono:
            # Same boot: the monotonic clock kept running while the process was down.
            self._server_anchor, self._mono_anchor, self._mode = self._parse(server_time), mono, "restored"
            return
        if not allow_provisional:
            return
        floor = self._parse(floor_time)
        local = self.local_now().astimezone(timezone.utc)
        if local < floor:
            # Rolled back across a reboot: never resume earlier than time already used.
            self._audit(local, floor, (local - floor).total_seconds(), floor)
        self._server_anchor, self._mono_anchor, self._mode = max(local, floor), now_mono, "provisional"

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

    @property
    def mode(self) -> str | None:
        with self._mutex:
            return self._mode

    @property
    def verified(self) -> bool:
        """True when the anchor came from the server, in this process or earlier in this boot."""
        return self.mode in {"server", "restored"}

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
            self._mode = "server"
            drifted = not clock_trusted if clock_trusted is not None else abs(drift) > self.threshold_seconds
            self.status = ClockStatus(drift, drifted, server)
            self._checkpoint(server, force=True)
        if drifted:
            self._audit(local, server, drift, server)
        return ClockStatus(drift, drifted, server)

    def _audit(self, local: datetime, server: datetime, drift: float, created: datetime) -> None:
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute(
                "INSERT INTO clock_events(local_time, server_time, drift_seconds, threshold_seconds, created_at) VALUES (?, ?, ?, ?, ?)",
                (local.isoformat(), server.isoformat(), drift, self.threshold_seconds, created.isoformat()),
            )

    def _checkpoint(self, trusted: datetime, force: bool = False) -> None:
        mono = self.monotonic()
        if not force and mono - self._last_checkpoint < CHECKPOINT_INTERVAL_SEC:
            return
        self._last_checkpoint = mono
        with sqlite3.connect(self.path, timeout=10) as db:
            # Only a server anchor may seed a later same-boot restore. It also replaces the floor,
            # so a provisional time that ran ahead (clock moved forward offline) is corrected.
            if self._mode in {"server", "restored"}:
                db.execute(
                    "INSERT INTO clock_anchor(id, server_time, mono, boot_id, floor_time, updated_at) VALUES (1, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET server_time=excluded.server_time, mono=excluded.mono, "
                    "boot_id=excluded.boot_id, floor_time=excluded.floor_time, updated_at=excluded.updated_at",
                    (self._server_anchor.isoformat(), self._mono_anchor, self._boot_id,
                     trusted.astimezone(timezone.utc).isoformat(), trusted.astimezone(timezone.utc).isoformat()),
                )
            else:
                db.execute("UPDATE clock_anchor SET floor_time=MAX(floor_time, ?), updated_at=? WHERE id=1",
                           (trusted.astimezone(timezone.utc).isoformat(),) * 2)

    def trusted_now(self) -> datetime:
        with self._mutex:
            if self._server_anchor is None or self._mono_anchor is None:
                raise RuntimeError("Trusted clock requires a successful heartbeat after startup")
            moment = self._server_anchor + timedelta(seconds=max(0, self.monotonic() - self._mono_anchor))
            self._checkpoint(moment)
            return moment.astimezone(self._timezone)
