"""The single protection runtime, hosted by the Windows Service or the console `run` command.

Tray = UI, Service = protection: everything that enforces (screen time, app/DNS blocking,
heartbeat, WebSocket, event sync) lives here. The tray only talks to it over local IPC, so
closing, killing or logging out of the tray never stops protection.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import threading
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path

from gui_controller import (AgentController, HeartbeatWorker, ProtectionWorker, connection_state, describe_error,
                            is_network_error, normalize_enrollment_code, normalize_server_url)
from openguard_agent import AGENT_VERSION, AgentConfig, device_name
from service.host import InteractiveHost, ServiceHost
from service.ipc import IPCError, create_server, default_address
from service.runtime_lock import RuntimeLock

LOGGER = logging.getLogger("openguard-agent.runtime")

SUPERVISE_SEC = 2.0
# More crashes than this inside the window means restarting in-process is not helping:
# exit non-zero and let the Service Control Manager recovery actions restart the process.
MAX_RESTARTS, RESTART_WINDOW_SEC = 5, 300.0
GUARD_RECHECK_SEC = 30.0
TRAY_RELAUNCH_SEC = 10.0
TRAY_POLL_GRACE_SEC = 15.0
PUBLIC_METHODS = {"status", "events", "heartbeat_now", "request_extra_time", "transparency", "report_idle", "enroll"}
ADMIN_METHODS = {"set_sync_paused"}


def json_safe(event: dict) -> dict:
    """Events cross the IPC boundary: exceptions become child-readable text, objects are dropped."""
    result = {}
    for key, value in event.items():
        if isinstance(value, BaseException):
            result[key] = describe_error(value)
        elif value is None or isinstance(value, (str, int, float, bool, list, dict)):
            result[key] = value
    return result


class EventBuffer:
    """Recent runtime notices for trays to poll; sequence numbers survive tray restarts."""

    def __init__(self, size: int = 200):
        self._events: deque[dict] = deque(maxlen=size)
        self._seq = 0
        self._mutex = threading.Lock()

    def publish(self, event: dict) -> int:
        with self._mutex:
            self._seq += 1
            self._events.append({"seq": self._seq, **event})
            return self._seq

    def since(self, after: int) -> dict:
        with self._mutex:
            # A tray that starts (after=-1) only needs the cursor, not stale notices.
            events = [] if after < 0 else [event for event in self._events if event["seq"] > after]
            return {"seq": self._seq, "events": events}


def default_tray_command() -> str:
    """pythonw.exe next to the interpreter running the service, launching the tray in background."""
    configured = os.getenv("OGK_TRAY_COMMAND")
    if configured:
        return configured
    python = Path(os.getenv("OGK_TRAY_PYTHON") or sys.executable)
    windowless = python.with_name("pythonw.exe")
    interpreter = windowless if windowless.exists() else python
    script = Path(__file__).resolve().parents[1] / "agent_gui.py"
    return f'"{interpreter}" "{script}" --background'


class TrayWatchdog:
    """Keeps a tray running in the child's session (NT1: the icon is visible while protecting).

    Only the tray process this watchdog launched is trusted for idle reports; a script the child
    writes can connect to the pipe but cannot make the service stop counting time.
    """

    def __init__(self, command: str | None = None, cwd: str | None = None, session=None, launch=None,
                 monotonic=time.monotonic):
        from service.windows import session as wts
        self.command = command or default_tray_command()
        self.cwd = cwd or str(Path(__file__).resolve().parents[1])
        self.session = session or wts.active_console_session
        self.launch = launch or wts.launch_in_session
        self.monotonic = monotonic
        self.pid = self._created = self._session_of = None
        self._last_attempt = -math.inf
        self._polls: dict[int | None, float] = {}

    def seen(self, caller) -> None:
        self._polls[caller.session] = self.monotonic()

    def trusted(self, caller) -> bool:
        """The launched process or its children (a venv pythonw.exe is a launcher for the real one)."""
        if caller.pid is None or not self._alive():
            return False
        if caller.pid == self.pid:
            return True
        import psutil
        try:
            return caller.pid in {child.pid for child in psutil.Process(self.pid).children(recursive=True)}
        except psutil.Error:
            return False

    def _alive(self) -> bool:
        if self.pid is None:
            return False
        import psutil
        try:
            return psutil.Process(self.pid).create_time() == self._created
        except psutil.Error:
            return False

    def tick(self) -> None:
        current, mono = self.session(), self.monotonic()
        if current is None or (self._alive() and self._session_of == current):
            return
        if mono - self._polls.get(current, -math.inf) < TRAY_POLL_GRACE_SEC:
            return  # A tray the user started is already polling in this session.
        if mono - self._last_attempt < TRAY_RELAUNCH_SEC:
            return
        self._last_attempt = mono
        try:
            pid = self.launch(current, self.command, self.cwd, hidden=False)
        except Exception as exc:
            LOGGER.warning("Cannot start tray in session %s: %s", current, exc)
            return
        if pid:
            import psutil
            try:
                self._created = psutil.Process(pid).create_time()
            except psutil.Error:
                return
            self.pid, self._session_of = pid, current
            LOGGER.info("Tray started in session %s (pid %s)", current, pid)


class AgentRuntime:
    def __init__(self, config: AgentConfig | None = None, host=None, ipc_address: str | None = None,
                 tray: TrayWatchdog | None = None, network_guard=None, monotonic=time.monotonic, transport=None):
        self.config = config or AgentConfig.from_env()
        self.host = host or InteractiveHost()
        self.controller = AgentController(self.config, host=self.host, transport=transport)
        self.controller.on_command_event = self._publish
        self.buffer = EventBuffer()
        self.heartbeat = HeartbeatWorker(self.controller, self._on_heartbeat)
        self.protection = ProtectionWorker(self.controller, self._publish)
        self.address = ipc_address or default_address(self.config.state_path)
        self.tray, self.guard, self.monotonic = tray, network_guard, monotonic
        self.connection, self.connection_error = "checking", ""
        self.sync_paused = False
        self.fatal: str | None = None
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._restarts: deque[float] = deque()
        self._protection_started = False
        self._dns_healthy: bool | None = None
        self._next_guard = 0.0
        self._guard_error_reported = False
        self._limits: dict[str, float] = {}
        self.ipc = self.lease = self._supervisor = None

    @property
    def database(self) -> Path:
        return self.config.database_path or self.config.state_path.with_name("agent.db")

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        # One runtime per database; a second Service/console instance fails here, before IPC.
        self.lease = RuntimeLock(self.database, suffix=".host.lock")
        try:
            state = self.controller.state()
            if state.server_url:
                self.controller.set_server_url(state.server_url)
        except (RuntimeError, ValueError) as exc:
            LOGGER.error("Agent state unreadable: %s", exc)
        try:
            self.ipc = create_server(self.address, self.handle)
            self.ipc.start()
        except Exception:
            self.lease.close()
            raise
        with self._busy:
            self._start_workers()
        self._supervisor = threading.Thread(target=self._supervise, name="openguard-supervisor", daemon=True)
        self._supervisor.start()
        LOGGER.info("OpenGuard runtime started (host=%s, ipc=%s)", self.host.name, self.address)

    def request_stop(self, reason: str | None = None) -> None:
        if reason:
            self.fatal = reason
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._stop.wait(timeout)

    def stop(self) -> None:
        self._stop.set()
        if self._supervisor is not None and self._supervisor is not threading.current_thread():
            self._supervisor.join(timeout=10)
        self.heartbeat.stop()
        self.protection.stop()
        self._join_workers()
        if self.guard is not None:
            try:
                self.guard.restore()  # Never leave the machine pointing at a stopped proxy.
            except Exception as exc:
                LOGGER.error("Network settings could not be restored: %s", exc)
        if self.ipc is not None:
            self.ipc.stop()
        if self.lease is not None:
            self.lease.close()
        LOGGER.info("OpenGuard runtime stopped")

    def _enrolled(self) -> bool:
        try:
            return self.controller.state().enrolled
        except RuntimeError:
            return False

    def _start_workers(self) -> None:
        if not self._enrolled():
            return
        self.protection.start()
        self._protection_started = True
        if not self.sync_paused:
            self.heartbeat.start()

    def _join_workers(self, timeout: float | None = None) -> bool:
        timeout = timeout if timeout is not None else self.config.request_timeout_sec * 4 + 15
        for worker in (self.heartbeat, self.protection):
            if worker._thread is not None:
                worker._thread.join(timeout=timeout)
                if worker._thread.is_alive():
                    return False
        return True

    def _supervise(self) -> None:
        while not self._stop.wait(SUPERVISE_SEC):
            try:
                self.supervise_once()
            except Exception:
                LOGGER.exception("Supervisor tick failed")

    def supervise_once(self) -> None:
        if self._busy.acquire(blocking=False):  # Skip while an enrollment swaps the workers.
            try:
                if self._enrolled():
                    if not self.protection.running and self._protection_started:
                        self._restart_protection()
                    elif not self._protection_started:
                        self._start_workers()
                    if not self.sync_paused and not self.heartbeat.running:
                        self.heartbeat.start()
            finally:
                self._busy.release()
        if self.tray is not None:
            self.tray.tick()
        if self.guard is not None:
            self._guard_tick()

    def _restart_protection(self) -> None:
        mono = self.monotonic()
        self._restarts.append(mono)
        while self._restarts and mono - self._restarts[0] > RESTART_WINDOW_SEC:
            self._restarts.popleft()
        if len(self._restarts) > MAX_RESTARTS:
            LOGGER.critical("Protection crashed %s times in %ss; exiting for SCM recovery",
                            len(self._restarts), int(RESTART_WINDOW_SEC))
            self.request_stop("protection_crash_loop")
            return
        LOGGER.warning("Protection worker stopped unexpectedly; restarting")
        self.protection.start()
        self._publish({"type": "PROTECTION_RESTARTED"})

    def _guard_tick(self) -> None:
        mono = self.monotonic()
        try:
            if self._dns_healthy and (self.guard.state != "protecting" or mono >= self._next_guard):
                was = self.guard.state
                changed = self.guard.protect()
                self._next_guard = mono + GUARD_RECHECK_SEC
                self._guard_error_reported = False
                if was == "protecting" and changed:
                    self._publish({"type": "DNS_ADAPTER_REAPPLIED", "adapters": changed})
            elif self._dns_healthy is False and self.guard.state == "protecting" \
                    and self.config.dns_failure_mode == "open":
                # Proxy is down: restore the adapters' own DNS instead of cutting the child off
                # from school sites; protection resumes as soon as the proxy answers again.
                self.guard.suspend()
                self._publish({"type": "DNS_FAILSAFE", "mode": "open"})
        except Exception as exc:
            self._next_guard = mono + GUARD_RECHECK_SEC
            if not self._guard_error_reported:
                self._guard_error_reported = True
                self._publish({"type": "CONTENT_ERROR", "message": f"Không cấu hình được DNS của card mạng: {exc}"})

    # ------------------------------------------------------------------ events

    def _publish(self, event: dict) -> None:
        if event.get("type") == "DNS_HEALTH":
            self._dns_healthy = bool(event.get("healthy"))
        self.buffer.publish(json_safe(event))

    def _on_heartbeat(self, result: dict | None, error: Exception | None) -> None:
        self.connection, self.connection_error = connection_state(error)

    # --------------------------------------------------------------------- IPC

    def handle(self, method: str, params: dict, caller):
        if self.tray is not None and method == "status" and params.get("tray"):
            self.tray.seen(caller)
        if method in ADMIN_METHODS and not caller.admin:
            raise PermissionError("Cần quyền quản trị viên (phụ huynh) cho thao tác này.")
        if method not in PUBLIC_METHODS | ADMIN_METHODS:
            raise IPCError("unknown_method", f"Unknown method {method}")
        return getattr(self, "ipc_" + method)(params, caller)

    def _limit(self, name: str, seconds: float) -> None:
        mono = self.monotonic()
        if mono < self._limits.get(name, -math.inf):
            raise IPCError("rate_limited", "Vui lòng chờ vài giây rồi thử lại.")
        self._limits[name] = mono + seconds

    def ipc_status(self, _params, caller) -> dict:
        try:
            state, state_error = self.controller.state(), None
        except RuntimeError as exc:
            state, state_error = None, describe_error(exc)
        clock = self.controller.clock_monitor
        trusted = clock.trusted_now() if clock.ready else None
        tick = self.protection.latest if self.protection.running else None
        policy = self.controller.current_policy()
        return {
            "enrolled": bool(state and state.enrolled), "state_error": state_error,
            "device_id": state.device_id if state else None, "device_name": device_name(),
            "server_url": self.controller.config.server_url, "agent_version": AGENT_VERSION,
            "host": self.host.name, "last_heartbeat_at": state.last_heartbeat_at if state else None,
            "policy_version": state.policy_version if state else 0,
            "connection": self.connection, "connection_error": self.connection_error,
            "sync_paused": self.sync_paused, "protection_running": self.protection.running,
            "caller_admin": caller.admin,
            "clock": {"ready": clock.ready, "mode": clock.mode, "trusted_now": trusted.isoformat() if trusted else None,
                      "drifted": bool(clock.status and clock.status.drifted)},
            "tick": asdict(tick) if tick else None,
            "policy": {"id": policy.policy_id, "version": policy.version, "payload": policy.payload,
                       "signature": policy.signature} if policy else None,
            "dns": {"healthy": self._dns_healthy, **(self.guard.status() if self.guard else {"state": "disabled"})},
        }

    def ipc_events(self, params, _caller) -> dict:
        return self.buffer.since(int(params.get("after", -1)))

    def ipc_heartbeat_now(self, _params, _caller) -> dict:
        self._limit("heartbeat", 3)
        try:
            self.controller.heartbeat()
            error = None
        except Exception as exc:
            error = exc
        self._on_heartbeat(None, error)
        status = self.controller.clock_monitor.status
        return {"ok": error is None, "connection": self.connection, "message": self.connection_error,
                "drifted": bool(status and status.drifted)}

    def ipc_request_extra_time(self, params, _caller) -> dict:
        minutes = int(params.get("minutes", 15))
        if not 5 <= minutes <= 60:
            raise ValueError("minutes must be between 5 and 60")
        self._limit("extra_time", 10)
        try:
            self.controller.request_extra_time(minutes)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "message": describe_error(exc)}

    def ipc_transparency(self, _params, _caller) -> dict:
        self._limit("transparency", 2)
        from service.screen_time import UsageRepository
        try:
            payload = self.controller.transparency()
        except Exception as exc:
            return {"ok": False, "message": describe_error(exc)}
        clock = self.controller.clock_monitor
        usage = UsageRepository(self.database).get(clock.trusted_now().date()).used_seconds if clock.ready else None
        return {"ok": True, "result": payload, "usage_seconds": usage}

    def ipc_report_idle(self, params, caller) -> dict:
        if not isinstance(self.host, ServiceHost) or self.tray is None or not self.tray.trusted(caller):
            return {"accepted": False}
        idle = float(params.get("idle_seconds"))
        if not math.isfinite(idle) or idle < 0:
            raise ValueError("idle_seconds must be a non-negative number")
        self.host.idle.report(idle)
        return {"accepted": True}

    def ipc_enroll(self, params, caller) -> dict:
        code = normalize_enrollment_code(str(params.get("code", "")))
        server_url = normalize_server_url(str(params.get("server_url") or self.controller.config.server_url))
        if self._enrolled() and not caller.admin:
            # Otherwise a child could pair the computer to an account they control.
            raise PermissionError("Máy đã được ghép. Cần quyền quản trị viên (phụ huynh) để ghép lại.")
        self._limit("enroll", 3)
        with self._busy:
            self.heartbeat.stop()
            self.protection.stop()
            if not self._join_workers():
                self._start_workers()
                raise IPCError("busy", "Agent đang dừng các tác vụ, hãy thử lại sau ít giây.")
            try:
                state = self.controller.enroll(code, server_url)
            except Exception as exc:
                return {"ok": False, "message": describe_error(exc), "network": is_network_error(exc)}
            finally:
                self.connection, self.connection_error = "checking", ""
                self._start_workers()
        return {"ok": True, "device_id": state.device_id}

    def ipc_set_sync_paused(self, params, _caller) -> dict:
        self.sync_paused = bool(params.get("paused"))
        if self.sync_paused:
            self.heartbeat.stop()
        elif self._enrolled():
            self.heartbeat.start()
        return {"sync_paused": self.sync_paused}


def build_service_runtime(config: AgentConfig | None = None) -> AgentRuntime:
    """Wire the runtime for a LocalSystem service: WTS host, tray watchdog, network guard."""
    config = config or AgentConfig.from_env()
    host = ServiceHost()
    guard = None
    if config.dns_enabled and config.dns_autoconfig_enabled(service=True):
        from service.windows.network import NetworkGuard
        guard = NetworkGuard(config.database_path or config.state_path.with_name("agent.db"),
                             upstream=config.dns_upstream)
    return AgentRuntime(config, host=host, tray=TrayWatchdog(), network_guard=guard)


def build_console_runtime(config: AgentConfig | None = None) -> AgentRuntime:
    config = config or AgentConfig.from_env()
    guard = None
    if os.name == "nt" and config.dns_enabled and config.dns_autoconfig_enabled(service=False):
        from service.windows.network import NetworkGuard
        guard = NetworkGuard(config.database_path or config.state_path.with_name("agent.db"),
                             upstream=config.dns_upstream)
    return AgentRuntime(config, network_guard=guard)


