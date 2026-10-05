"""OpenGuard Kids week-one agent: enrollment and heartbeat."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import signal
import socket
import sqlite3
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

from service.policy import PolicyManager, PolicyRejectedError, PolicyRepository
from service.clock import ClockMonitor
from service.commands import CommandHandler, ProcessedCommandRepository
from service.enforcement import WorkstationEnforcer
from service.realtime import WebSocketWorker
from service.requests import ExtraTimeClient
from service.screen_time import (
    ScreenTimeCounter,
    UsageRepository,
    is_session_unlocked,
    is_user_active,
)

AGENT_VERSION = "0.3.0"
LOGGER = logging.getLogger("openguard-agent")

# Load one shared project-level file; real environment variables take priority.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


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
        if not 0.1 <= tick <= 30:
            raise ValueError("Usage tick must be between 0.1 and 30 seconds")
        return cls(
            server_url=os.getenv("OGK_SERVER_URL", "http://127.0.0.1:8000").rstrip("/"),
            state_path=state_path,
            heartbeat_interval_sec=interval,
            request_timeout_sec=timeout,
            verify_tls=verify_tls,
            database_path=Path(os.getenv("OGK_DATABASE_PATH", str(state_path.with_name("agent.db")))),
            policy_hmac_secret=os.getenv("OGK_POLICY_HMAC_SECRET") or None,
            usage_tick_sec=tick,
        )


@dataclass
class AgentState:
    device_id: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    policy_version: int = 0
    quota_used_sec: int = 0
    last_heartbeat_at: str | None = None
    last_server_time: str | None = None

    @property
    def enrolled(self) -> bool:
        return bool(self.device_id and self.access_token and self.refresh_token)


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self._mutex = threading.RLock()

    def load(self) -> AgentState:
        with self._mutex:
            if not self.path.exists():
                return AgentState()
            try:
                return AgentState(**json.loads(self.path.read_text(encoding="utf-8")))
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
                    json.dump(asdict(state), handle, indent=2)
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
    ):
        self.config = config
        self.store = store
        self.http = httpx.Client(
            base_url=config.server_url,
            timeout=config.request_timeout_sec,
            verify=config.verify_tls,
            transport=transport,
        )
        database_path = config.database_path or config.state_path.with_name("agent.db")
        self.policy_manager = (
            PolicyManager(PolicyRepository(database_path), config.policy_hmac_secret)
            if config.policy_hmac_secret else None
        )
        self.usage_repository = UsageRepository(database_path)
        self.clock_monitor = ClockMonitor(database_path)
        self.enforcer = WorkstationEnforcer()
        self.command_handler = CommandHandler(
            ProcessedCommandRepository(database_path), self.usage_repository,
            self.enforcer, today=lambda: self.clock_monitor.trusted_now().date(),
            on_event=on_command_event or (lambda event: LOGGER.info("Command event: %s", event)),
        )
        self.extra_time = ExtraTimeClient(self._authorized_post)

    def close(self) -> None:
        self.http.close()

    def enroll(self, code: str) -> AgentState:
        code = code.strip().upper()
        if len(code) != 8:
            raise ValueError("Enrollment code must contain exactly 8 characters")
        response = self.http.post(
            "/api/v1/agent/enroll",
            json={"code": code, "device_name": device_name(), "fingerprint": device_fingerprint()},
        )
        response.raise_for_status()
        payload = response.json()
        state = AgentState(
            device_id=payload["device_id"],
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
        )
        self.store.save(state)
        return state

    def heartbeat(self) -> dict[str, Any]:
        state = self.store.load()
        if not state.enrolled:
            raise AgentNotEnrolledError("Agent is not enrolled; run enroll first")
        usage = self.usage_repository.get_if_exists(self.clock_monitor.trusted_now().date())
        if usage is not None:
            state.quota_used_sec = int(usage.used_seconds)
        response = self._send_heartbeat(state)
        if response.status_code == 401:
            refresh = self.http.post(
                "/api/v1/agent/token/refresh", json={"refresh_token": state.refresh_token}
            )
            refresh.raise_for_status()
            state.access_token = refresh.json()["access_token"]
            self.store.save(state)
            response = self._send_heartbeat(state)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        clock_status = self.clock_monitor.synchronize(payload["server_time"])
        if clock_status.drifted:
            LOGGER.warning("Local clock drift detected: %.1f seconds", clock_status.drift_seconds)
        if payload.get("policy_update_available") and self.policy_manager is not None:
            self._sync_policy(state)
        for command in payload.get("commands", []):
            result = self.command_handler.handle(command)
            self._ack_command(result.command_id, result.status, result.error, state)
        state.last_heartbeat_at = datetime.now(timezone.utc).isoformat()
        state.last_server_time = payload["server_time"]
        self.store.save(state)
        return payload

    def _sync_policy(self, state: AgentState) -> None:
        response = self.http.get(
            "/api/v1/agent/policy",
            headers={"Authorization": f"Bearer {state.access_token}"},
        )
        response.raise_for_status()
        try:
            policy = self.policy_manager.accept(response.json())  # type: ignore[union-attr]
        except PolicyRejectedError:
            return
        state.policy_version = policy.version

    def screen_time_counter(self, on_event: Callable[[dict], None] | None = None) -> ScreenTimeCounter:
        if self.policy_manager is None:
            raise RuntimeError("OGK_POLICY_HMAC_SECRET is required to enforce screen time")
        return ScreenTimeCounter(
            repository=self.usage_repository,
            policy_provider=lambda: self.policy_manager.current,
            active_probe=is_user_active,
            unlocked_probe=is_session_unlocked,
            locker=lambda: False,
            enforcer=self.enforcer,
            now=self.clock_monitor.trusted_now,
            on_event=on_event or (lambda event: LOGGER.info("Screen-time event: %s", event)),
        )

    def request_extra_time(self, minutes: int = 15) -> dict[str, Any]:
        return self.extra_time.request(minutes)

    def _authorized_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        state = self.store.load()
        if not state.enrolled:
            raise AgentNotEnrolledError("Agent is not enrolled; run enroll first")
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
        self.store.save(state)

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
            on_auth_failure=self._refresh_for_websocket,
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
                "agent_wall_clock": datetime.now(timezone.utc).isoformat(),
            },
        )


def build_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="OpenGuard Kids agent")
    result.add_argument("--verbose", action="store_true")
    commands = result.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("enroll", help="pair this device")
    enroll.add_argument("code")
    commands.add_parser("heartbeat", help="send one heartbeat")
    commands.add_parser("run", help="send heartbeats continuously")
    commands.add_parser("status", help="show safe local status")
    return result


def run_forever(client: AgentClient, interval: int) -> None:
    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    counter = client.screen_time_counter()
    websocket = client.websocket_worker()
    websocket.start()
    next_heartbeat = 0.0
    LOGGER.info("Agent started; heartbeat interval=%s seconds", interval)
    while not stopped.is_set():
        now = time.monotonic()
        if now >= next_heartbeat:
            try:
                reply = client.heartbeat()
                LOGGER.info(
                    "Heartbeat accepted; policy=%s update=%s commands=%s",
                    reply["policy_version"], reply["policy_update_available"], len(reply.get("commands", [])),
                )
            except (httpx.HTTPError, RuntimeError, KeyError) as exc:
                LOGGER.error("Heartbeat failed: %s", exc)
            next_heartbeat = now + interval
        try:
            result = counter.tick()
            if result.should_lock:
                LOGGER.warning("Workstation lock requested: %s", result.reason)
        except (OSError, sqlite3.Error) as exc:
            LOGGER.error("Screen-time tick failed: %s", exc)
        stopped.wait(min(client.config.usage_tick_sec, 5.0))
    websocket.stop()


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = AgentConfig.from_env()
    store = StateStore(config.state_path)
    if args.command == "status":
        state = store.load()
        safe = asdict(state)
        safe.pop("access_token")
        safe.pop("refresh_token")
        safe["enrolled"] = state.enrolled
        print(json.dumps(safe, indent=2))
        return 0
    client = AgentClient(config, store)
    try:
        if args.command == "enroll":
            state = client.enroll(args.code)
            print(f"Enrolled successfully as device {state.device_id}")
        elif args.command == "heartbeat":
            print(json.dumps(client.heartbeat(), indent=2))
        else:
            run_forever(client, config.heartbeat_interval_sec)
    except (ValueError, AgentNotEnrolledError, httpx.HTTPError) as exc:
        LOGGER.error("%s", exc)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
