"""OpenGuard Kids week-one agent: enrollment and heartbeat."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import platform
import signal
import socket
import sqlite3
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

from service.policy import PolicyManager, PolicyRejectedError, PolicyRepository
from service.clock import ClockMonitor
from service.commands import CommandHandler, ProcessedCommandRepository
from service.enforcement import RemoteLockRepository, WorkstationEnforcer
from service.realtime import WebSocketWorker
from service.requests import ExtraTimeClient
from service.events import EventQueue
from service.host import InteractiveHost
from service.screen_time import ScreenTimeCounter, UsageRepository

AGENT_VERSION = "0.4.0"
LOGGER = logging.getLogger("openguard-agent")


def protected_env_path() -> Path | None:
    """Service configuration written by the installer; readable only by SYSTEM/Administrators."""
    program_data = os.getenv("PROGRAMDATA")
    return Path(program_data) / "OpenGuardKids" / "agent.env" if os.name == "nt" and program_data else None


def load_environment() -> None:
    # Real environment variables take priority, then the protected file, then the project file.
    for path in (protected_env_path(), Path(__file__).resolve().parents[1] / ".env"):
        if path is None:
            continue
        try:
            load_dotenv(path, override=False)
        except OSError:
            pass  # The tray runs as the child and is not allowed to read the protected file.


load_environment()


def default_state_path() -> Path:
    program_data = os.getenv("PROGRAMDATA")
    if os.name == "nt" and program_data:
        return Path(program_data) / "OpenGuardKids" / "agent-state.json"
    return Path.home() / ".openguard-kids" / "agent-state.json"


@dataclass(frozen=True)
class AgentConfig:
    server_url: str
    state_path: Path
    heartbeat_interval_sec: int = 60
    request_timeout_sec: float = 10.0
    verify_tls: bool = True
    database_path: Path | None = None
    policy_hmac_secret: str | None = None
    usage_tick_sec: float = 1.0
    relock_delay_sec: float = 5.0
    apps_enabled: bool = True
    dns_enabled: bool = True
    dns_port: int = 53
    dns_upstream: str = '1.1.1.1'
    app_poll_sec: float = 2.0
    event_sync_sec: float = 5.0
    report_timezone_offset_minutes: int = 420
    offline_clock_mode: str = 'strict'
    policy_offline_days: int = 7
    dns_autoconfig: str = 'auto'
    dns_failure_mode: str = 'open'
    tls_cert_sha256: str | None = None
    tls_ca_file: str | None = None

    @classmethod
    def from_env(cls) -> "AgentConfig":
        interval = int(os.getenv("OGK_HEARTBEAT_INTERVAL_SEC", "60"))
        timeout = float(os.getenv("OGK_REQUEST_TIMEOUT_SEC", "10"))
        if interval < 1 or timeout <= 0:
            raise ValueError("Heartbeat interval and request timeout must be positive")
        verify_tls = os.getenv("OGK_VERIFY_TLS", "true").lower() not in {
            "0", "false", "no", "off"
        }
        state_path = Path(os.getenv("OGK_STATE_PATH", str(default_state_path())))
        tick = float(os.getenv("OGK_USAGE_TICK_SEC", "1"))
        relock_delay = float(os.getenv('OGK_RELOCK_DELAY_SEC', '5'))
        if not math.isfinite(relock_delay) or relock_delay < 0:
            raise ValueError('OGK_RELOCK_DELAY_SEC must be finite and non-negative')
        if not 0.1 <= tick <= 30:
            raise ValueError("Usage tick must be between 0.1 and 30 seconds")
        dns_port = int(os.getenv('OGK_DNS_PORT', '53'))
        app_poll = float(os.getenv('OGK_APP_POLL_SEC', '2'))
        event_sync = float(os.getenv('OGK_EVENT_SYNC_SEC', '5'))
        report_offset = int(os.getenv('OGK_REPORT_TIMEZONE_OFFSET_MINUTES', '420'))
        if not -720 <= report_offset <= 840:
            raise ValueError('Invalid report timezone offset')
        offline_clock = os.getenv('OGK_OFFLINE_CLOCK', 'strict').lower()
        offline_days = int(os.getenv("OGK_POLICY_OFFLINE_DAYS", "7"))
        if not 1 <= offline_days <= 90:
            raise ValueError("OGK_POLICY_OFFLINE_DAYS must be between 1 and 90")
        if offline_clock not in {'provisional', 'strict'}:
            raise ValueError('OGK_OFFLINE_CLOCK must be provisional or strict')
        dns_autoconfig = os.getenv('OGK_DNS_AUTOCONFIG', 'auto').lower()
        dns_failure = os.getenv('OGK_DNS_FAILURE_MODE', 'open').lower()
        if dns_autoconfig not in {'auto', 'true', 'false'} or dns_failure not in {'open', 'closed'}:
            raise ValueError('OGK_DNS_AUTOCONFIG must be auto/true/false and OGK_DNS_FAILURE_MODE open/closed')
        if not 1 <= dns_port <= 65535 or not .5 <= app_poll <= 30 or not 1 <= event_sync <= 60:
            raise ValueError('Invalid DNS port, app polling or event sync interval')
        return cls(
            server_url=os.getenv("OGK_SERVER_URL", "http://127.0.0.1:8000").rstrip("/"),
            state_path=state_path,
            heartbeat_interval_sec=interval,
            request_timeout_sec=timeout,
            verify_tls=verify_tls,
            database_path=Path(os.getenv("OGK_DATABASE_PATH", str(state_path.with_name("agent.db")))),
            policy_hmac_secret=os.getenv("OGK_POLICY_HMAC_SECRET") or None,
            usage_tick_sec=tick,
            relock_delay_sec=relock_delay,
            apps_enabled=os.getenv('OGK_APPS_ENABLED', 'true').lower() not in {'0', 'false', 'no', 'off'},
            dns_enabled=os.getenv('OGK_DNS_ENABLED', 'true').lower() not in {'0', 'false', 'no', 'off'},
            dns_port=dns_port, dns_upstream=os.getenv('OGK_DNS_UPSTREAM', '1.1.1.1'),
            app_poll_sec=app_poll, event_sync_sec=event_sync,
            report_timezone_offset_minutes=report_offset,
            offline_clock_mode=offline_clock,
            policy_offline_days=offline_days,
            dns_autoconfig=dns_autoconfig, dns_failure_mode=dns_failure,
            tls_cert_sha256=os.getenv("OGK_TLS_CERT_SHA256") or None,
            tls_ca_file=os.getenv("OGK_TLS_CA_FILE") or None,
        )

    def dns_autoconfig_enabled(self, service: bool) -> bool:
        """Adapters can only point at port 53; `auto` changes them only when running as the Service."""
        if self.dns_port != 53:
            return False
        return self.dns_autoconfig == 'true' or (self.dns_autoconfig == 'auto' and service)

    def clock_monitor(self) -> ClockMonitor:
        return ClockMonitor(self.database_path or self.state_path.with_name("agent.db"),
                            report_timezone=timezone(timedelta(minutes=self.report_timezone_offset_minutes)),
                            allow_provisional=self.offline_clock_mode != 'strict')


@dataclass
class AgentState:
    erasure_pending: bool = False
    device_id: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    policy_version: int = 0
    quota_used_sec: int = 0
    last_heartbeat_at: str | None = None
    last_server_time: str | None = None
    server_url: str | None = None

    @property
    def enrolled(self) -> bool:
        return bool(self.device_id and self.access_token and self.refresh_token)


class StateStore:
    _locks = {}
    _locks_guard = threading.Lock()

    def __init__(self, path: Path):
        self.path = path
        with self._locks_guard:
            self._mutex = self._locks.setdefault(str(path.resolve()).casefold(), threading.RLock())

    def update(self, **changes):
        with self._mutex:
            state = self.load()
            for key, value in changes.items():
                if key == 'policy_version':
                    value = max(state.policy_version, value)
                setattr(state, key, value)
            self.save(state)
            return state

    def load(self) -> AgentState:
        with self._mutex:
            if not self.path.exists():
                return AgentState()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if "format" in payload:
                    from service.state_crypto import decrypt
                    return AgentState(**json.loads(decrypt(self.path, payload)))
                state = AgentState(**payload)
                self.save(state)  # Upgrade legacy plaintext on first successful read.
                return state
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise RuntimeError(f"Cannot read agent state at {self.path}: {exc}") from exc

    def save(self, state: AgentState) -> None:
        with self._mutex:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", text=True
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    from service.state_crypto import encrypt
                    json.dump(encrypt(self.path, json.dumps(asdict(state)).encode("utf-8")), handle)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary_name, 0o600)
                os.replace(temporary_name, self.path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)


def device_name() -> str:
    return os.getenv("COMPUTERNAME") or socket.gethostname() or "unknown-device"


def device_fingerprint() -> str:
    """Create a stable one-way ID without sending raw machine attributes."""
    values = [platform.system(), platform.machine(), device_name(), str(uuid.getnode())]
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()


class AgentNotEnrolledError(RuntimeError):
    pass


class AgentClient:
    def __init__(
        self,
        config: AgentConfig,
        store: StateStore,
        transport: httpx.BaseTransport | None = None,
        on_command_event: Callable[[dict], None] | None = None,
        clock_monitor: ClockMonitor | None = None,
        host=None,
    ):
        self.config = config
        self.store = store
        # Session probes, workstation lock and process list differ between console and Service.
        self.host = host or InteractiveHost()
        from service.tls import tls_context
        self.http = httpx.Client(
            base_url=config.server_url,
            timeout=config.request_timeout_sec,
            verify=tls_context(config.server_url, config.verify_tls, config.tls_cert_sha256, config.tls_ca_file),
            trust_env=False,
            transport=transport,
        )
        database_path = config.database_path or config.state_path.with_name("agent.db")
        self.policy_manager = (
            PolicyManager(PolicyRepository(database_path), config.policy_hmac_secret)
            if config.policy_hmac_secret else None
        )
        self.usage_repository = UsageRepository(database_path)
        self.clock_monitor = clock_monitor or config.clock_monitor()
        self.events = EventQueue(database_path, self.store.load().device_id or '__unenrolled__')
        self.on_event = on_command_event or (lambda event: LOGGER.info('Agent event: %s', event))
        self.enforcer = WorkstationEnforcer(lock=self.host.lock, on_locked=lambda: self.activity('locked'),
                                           relock_delay_sec=config.relock_delay_sec, state_key=database_path)
        self.remote_lock = RemoteLockRepository(database_path)
        self.command_handler = CommandHandler(
            ProcessedCommandRepository(database_path), self.usage_repository,
            self.enforcer, today=lambda: self.clock_monitor.trusted_now().date(),
            on_event=self._command_event,
            remote_lock=self.remote_lock,
            event_queue=self.events, event_now=self.clock_monitor.trusted_now,
            policy_id=lambda: self.policy_manager.current.policy_id if self.policy_manager and self.policy_manager.current else None,
        )
        self.extra_time = ExtraTimeClient(self._authorized_post)

    def activity(self, kind, **kwargs):
        if self.clock_monitor.ready:
            policy = self.policy_manager.current if self.policy_manager else None
            return self.events.emit(kind, self.clock_monitor.trusted_now(),
                                    policy_id=policy.policy_id if policy else None, **kwargs)

    def _command_event(self, event):
        if event.get('type') in {'TIME_ADDED', 'REMOTE_UNLOCKED'}:
            key = event.get('command_id')
            self.activity('override_granted', event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'override:' + key)) if key else None)
        self.on_event(event)

    def accept_policy(self, envelope):
        if not self.policy_manager:
            return
        try:
            policy = self.policy_manager.accept(envelope)
        except PolicyRejectedError:
            return
        current = self.policy_manager.current
        self.store.update(policy_version=current.version)
        self.on_event(dict(type='POLICY_UPDATED', version=current.version))
        return policy

    def authorized_get(self, path):
        state = self.store.load()
        if not state.enrolled:
            raise AgentNotEnrolledError('Agent is not enrolled')
        response = self.http.get(path, headers={'Authorization': f'Bearer {state.access_token}'})
        if response.status_code == 401:
            self._refresh_access_token(state)
            response = self.http.get(path, headers={'Authorization': f'Bearer {state.access_token}'})
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.http.close()

    def enroll(self, code: str) -> AgentState:
        from service.runtime_lock import RuntimeLock
        with RuntimeLock(self.events.path):
            return self._enroll(code)

    def _enroll(self, code: str) -> AgentState:
        code = code.strip().upper()
        if len(code) != 8:
            raise ValueError("Enrollment code must contain exactly 8 characters")
        response = self.http.post(
            "/api/v1/agent/enroll",
            json={"code": code, "device_name": device_name(), "fingerprint": device_fingerprint()},
        )
        response.raise_for_status()
        payload = response.json()
        previous_device = self.store.load().device_id
        if previous_device and previous_device != payload['device_id']:
            # Callers stop protection before re-pairing. Never apply an old child's policy.
            with self.events.connect() as db:
                for table in ('policies', 'usage_daily', 'warning_state', 'processed_commands', 'remote_lock'):
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        db.execute(f'DELETE FROM {table}')
        state = AgentState(
            device_id=payload["device_id"],
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            server_url=self.config.server_url,  # The Service restarts with the paired server.
        )
        self.store.save(state)
        self.events.owner = state.device_id
        return state

    def heartbeat(self) -> dict[str, Any]:
        state = self.store.load()
        if not state.enrolled:
            raise AgentNotEnrolledError("Agent is not enrolled; run enroll first")
        usage = (self.usage_repository.get_if_exists(self.clock_monitor.trusted_now().date())
                 if self.clock_monitor.ready else None)
        if usage is not None:
            state.quota_used_sec = int(usage.used_seconds)
        elif self.clock_monitor.ready:
            state.quota_used_sec = 0
        if self.policy_manager and self.policy_manager.current:
            state.policy_version = self.policy_manager.current.version
        response = self._send_heartbeat(state)
        if response.status_code == 401:
            refresh = self.http.post(
                "/api/v1/agent/token/refresh", json={"refresh_token": state.refresh_token}
            )
            refresh.raise_for_status()
            state.access_token = refresh.json()["access_token"]
            self.store.update(access_token=state.access_token)
            response = self._send_heartbeat(state)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        clock_status = self.clock_monitor.synchronize(
            payload["server_time"], clock_trusted=payload.get("clock_trusted"),
            drift_seconds=payload.get("clock_drift_sec"),
            threshold_seconds=payload.get("clock_drift_threshold_sec"),
        )
        if clock_status.drifted:
            LOGGER.warning("CLOCK_TAMPERING: local clock drift %.1f seconds; using server time", clock_status.drift_seconds)
        if payload.get("policy_update_available") and self.policy_manager is not None:
            self._sync_policy(state)
        for command in payload.get("commands", []):
            result = self.command_handler.handle(command)
            self._ack_command(result.command_id, result.status, result.error, state)
        state.last_heartbeat_at = payload["server_time"]
        state.last_server_time = payload["server_time"]
        current = self.policy_manager.current if self.policy_manager else None
        self.store.update(last_heartbeat_at=state.last_heartbeat_at, last_server_time=state.last_server_time,
                          quota_used_sec=state.quota_used_sec, policy_version=current.version if current else state.policy_version)
        return payload

    def _sync_policy(self, state: AgentState) -> None:
        response = self.http.get(
            "/api/v1/agent/policy",
            headers={"Authorization": f"Bearer {state.access_token}"},
        )
        response.raise_for_status()
        policy = self.accept_policy(response.json())
        if policy:
            state.policy_version = policy.version

    def screen_time_counter(self, on_event: Callable[[dict], None] | None = None) -> ScreenTimeCounter:
        if self.policy_manager is None:
            raise RuntimeError("OGK_POLICY_HMAC_SECRET is required to enforce screen time")
        def report(event):
            if event.get('type') == 'TIME_WARNING':
                self.activity('quota_warning')
            (on_event or self.on_event)(event)
        return ScreenTimeCounter(
            repository=self.usage_repository,
            policy_provider=lambda: self.policy_manager.current,
            active_probe=self.host.active,
            unlocked_probe=self.host.unlocked,
            locker=lambda: False,
            enforcer=self.enforcer,
            now=self.clock_monitor.trusted_now,
            clock_ready=lambda: self.clock_monitor.ready,
            policy_expired=self.policy_expired,
            remote_locked=self.remote_lock.active,
            on_event=report,
        )

    def policy_expired(self):
        stamp = self.store.load().last_heartbeat_at
        if not stamp or not self.clock_monitor.ready:
            return False
        confirmed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return self.clock_monitor.trusted_now() - confirmed >= timedelta(days=self.config.policy_offline_days)

    def request_extra_time(self, minutes: int = 15) -> dict[str, Any]:
        result = self.extra_time.request(minutes)
        self.activity('unlock_request')
        return result

    def _authorized_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        state = self.store.load()
        if not state.enrolled:
            raise AgentNotEnrolledError("Agent is not enrolled; run enroll first")
        if path.endswith('/events/batch') and state.device_id != self.events.owner:
            raise RuntimeError('Event queue belongs to a different enrollment')
        response = self.http.post(path, headers={"Authorization": f"Bearer {state.access_token}"}, json=body)
        if response.status_code == 401:
            self._refresh_access_token(state)
            response = self.http.post(path, headers={"Authorization": f"Bearer {state.access_token}"}, json=body)
        response.raise_for_status()
        return response.json()

    def _refresh_access_token(self, state: AgentState) -> None:
        refresh = self.http.post("/api/v1/agent/token/refresh", json={"refresh_token": state.refresh_token})
        refresh.raise_for_status()
        state.access_token = refresh.json()["access_token"]
        self.store.update(access_token=state.access_token)

    def _ack_command(self, command_id: str, status: str, error: str | None, state: AgentState | None = None) -> None:
        if not command_id:
            return
        state = state or self.store.load()
        self._authorized_post(
            f"/api/v1/agent/commands/{command_id}/ack",
            {"status": status, "error": error},
        )

    def websocket_worker(self) -> WebSocketWorker:
        return WebSocketWorker(
            self.config.server_url,
            token_provider=lambda: self.store.load().access_token or "",
            handler=self.command_handler,
            verify_tls=self.config.verify_tls,
            tls_cert_sha256=self.config.tls_cert_sha256,
            tls_ca_file=self.config.tls_ca_file,
            on_auth_failure=self._refresh_for_websocket,
            on_policy=self.accept_policy,
        )

    def _refresh_for_websocket(self) -> None:
        self._refresh_access_token(self.store.load())

    def _send_heartbeat(self, state: AgentState) -> httpx.Response:
        return self.http.post(
            "/api/v1/agent/heartbeat",
            headers={"Authorization": f"Bearer {state.access_token}"},
            json={
                "policy_version": state.policy_version,
                "agent_version": AGENT_VERSION,
                "quota_used_sec": state.quota_used_sec,
                **({'quota_date': self.clock_monitor.trusted_now().date().isoformat()} if self.clock_monitor.ready else {}),
                "agent_wall_clock": datetime.now(timezone.utc).isoformat(),
                # "agent_wall_clock": self.clock_monitor.local_now().isoformat(),
            },
        )


def build_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="OpenGuard Kids agent")
    result.add_argument("--verbose", action="store_true")
    commands = result.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("enroll", help="pair this device")
    enroll.add_argument("code")
    commands.add_parser("heartbeat", help="send one heartbeat")
    commands.add_parser("run", help="run protection in this console (same runtime as the Service)")
    commands.add_parser("status", help="show safe local status")
    return result


def data_dir_problem(config: AgentConfig) -> str | None:
    """Explain, instead of a traceback, why this console cannot write the agent's data folder."""
    folder = (config.database_path or config.state_path).parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
        return None
    except OSError as exc:
        return (f"Không ghi được thư mục dữ liệu {folder} ({exc.strerror or exc}). "
                "Khi đã cài service, thư mục này chỉ SYSTEM và Administrators được ghi: "
                "dùng service (mở giao diện bằng agent_gui.py) thay vì lệnh run, "
                "hoặc mở PowerShell bằng 'Run as Administrator', "
                "hoặc đặt OGK_STATE_PATH sang thư mục khác để thử nghiệm.")


def service_running(config: AgentConfig) -> bool:
    from service.ipc import IPCClient, IPCError, ServiceUnavailableError, default_address
    try:
        IPCClient(default_address(config.state_path), timeout=3).call("status")
    except ServiceUnavailableError:
        return False
    except (IPCError, OSError):
        pass  # Something answers on the address; it is not ours to start a second runtime on.
    return True


def run_forever(config: AgentConfig) -> int:
    """Console host for the same runtime the Windows Service uses (development, Linux, debugging)."""
    from service.runtime import build_console_runtime
    runtime = build_console_runtime(config)

    def stop(_signum: int, _frame: object) -> None:
        runtime.request_stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        runtime.start()
    except (RuntimeError, OSError) as exc:
        LOGGER.error("%s", exc)
        return 1
    LOGGER.info("Agent started; heartbeat interval=%s seconds, IPC %s", config.heartbeat_interval_sec, runtime.address)
    try:
        runtime.wait()
    finally:
        runtime.stop()
    return 1 if runtime.fatal else 0


def enroll_via_service(config: AgentConfig, code: str) -> dict | None:
    """A running Service owns the database, so pairing goes through it; None if none is running."""
    from service.ipc import IPCClient, ServiceUnavailableError, default_address
    try:
        return IPCClient(default_address(config.state_path), timeout=60).call(
            "enroll", code=code, server_url=config.server_url)
    except ServiceUnavailableError:
        return None


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = AgentConfig.from_env()
    try:
        return run_command(args, config)
    except (PermissionError, sqlite3.OperationalError) as exc:
        LOGGER.error("%s", data_dir_problem(config) or exc)
        return 1


def run_command(args: argparse.Namespace, config: AgentConfig) -> int:
    store = StateStore(config.state_path)
    if args.command == "status":
        state = store.load()
        safe = asdict(state)
        safe.pop("access_token")
        safe.pop("refresh_token")
        safe["enrolled"] = state.enrolled
        print(json.dumps(safe, indent=2))
        return 0
    if args.command == "run":
        if service_running(config):
            LOGGER.error("Dịch vụ OpenGuard Kids đang chạy trên máy này; không cần lệnh run. "
                         "Mở giao diện bằng agent_gui.py, xem trạng thái bằng openguard_service.py status.")
            return 1
        problem = data_dir_problem(config)
        if problem:
            LOGGER.error("%s", problem)
            return 1
        return run_forever(config)
    if args.command == "enroll":
        from service.ipc import IPCError
        try:
            reply = enroll_via_service(config, args.code)
        except (IPCError, PermissionError) as exc:
            LOGGER.error("%s", exc)
            return 1
        if reply is not None:
            if not reply.get("ok"):
                LOGGER.error("%s", reply.get("message"))
                return 1
            print(f"Enrolled successfully as device {reply['device_id']}")
            return 0
    client = AgentClient(config, store)
    try:
        if args.command == "enroll":
            state = client.enroll(args.code)
            print(f"Enrolled successfully as device {state.device_id}")
        else:
            print(json.dumps(client.heartbeat(), indent=2))
    except (ValueError, AgentNotEnrolledError, httpx.HTTPError) as exc:
        LOGGER.error("%s", exc)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
