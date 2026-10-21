"""Tray-side link to the protection service: status/event polling and actions over local IPC.

The tray holds no tokens, policy secret or database handle; it only renders what the service
reports and forwards the child's requests.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from service.ipc import IPCClient, IPCError
from service.screen_time.platform import idle_seconds

POLL_SEC = 1.0
IDLE_REPORT_SEC = 5.0


class ServiceLink:
    def __init__(self, client: IPCClient, post: Callable[[str, object], None],
                 idle_probe: Callable[[], float] = idle_seconds, monotonic=time.monotonic,
                 visible_probe=lambda: False):
        self.client, self.post, self.idle_probe, self.monotonic = client, post, idle_probe, monotonic
        self.cursor = -1
        self.visible_probe = visible_probe
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_idle = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="openguard-tray-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self) -> None:
        try:
            status = self.client.call("status", tray=True, visible=bool(self.visible_probe()))
            if status.get("stopping"):
                self.post("service_status", status)
                self.stop()
                return
            batch = self.client.call("events", after=self.cursor)
            if batch["seq"] < self.cursor:
                self.cursor = -1  # The service restarted; its numbering began again.
                batch = self.client.call("events", after=self.cursor)
            if self.cursor >= 0:
                for event in batch["events"]:
                    self.post("protection", event)
            self.cursor = batch["seq"]
            self.post("service_status", status)
            if self.monotonic() >= self._next_idle:
                self._next_idle = self.monotonic() + IDLE_REPORT_SEC
                self.client.call("report_idle", idle_seconds=self.idle_probe())
        except (IPCError, OSError) as exc:
            self.post("service_down", exc)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(POLL_SEC)

    def call_async(self, name: str, method: str, **params) -> None:
        """Run one action off the Tk thread; the result arrives as (name, (result, error))."""
        def task():
            try:
                self.post(name, (self.client.call(method, **params), None))
            except Exception as exc:
                self.post(name, (None, exc))
        threading.Thread(target=task, name=f"openguard-{method}", daemon=True).start()
