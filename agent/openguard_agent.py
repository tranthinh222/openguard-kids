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
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

AGENT_VERSION = "0.1.0"
LOGGER = logging.getLogger("openguard-agent")


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

    @classmethod
    def from_env(cls) -> "AgentConfig":
        interval = int(os.getenv("OGK_HEARTBEAT_INTERVAL_SEC", "60"))
        timeout = float(os.getenv("OGK_REQUEST_TIMEOUT_SEC", "10"))
        if interval < 1 or timeout <= 0:
            raise ValueError("Heartbeat interval and request timeout must be positive")
        verify_tls = os.getenv("OGK_VERIFY_TLS", "true").lower() not in {
            "0", "false", "no", "off"
        }
        return cls(
            server_url=os.getenv("OGK_SERVER_URL", "http://127.0.0.1:8000").rstrip("/"),
            state_path=Path(os.getenv("OGK_STATE_PATH", str(default_state_path()))),
            heartbeat_interval_sec=interval,
            request_timeout_sec=timeout,
            verify_tls=verify_tls,
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

    def load(self) -> AgentState:
        if not self.path.exists():
            return AgentState()
        try:
            return AgentState(**json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"Cannot read agent state at {self.path}: {exc}") from exc

    def save(self, state: AgentState) -> None:
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
    ):
        self.store = store
        self.http = httpx.Client(
            base_url=config.server_url,
            timeout=config.request_timeout_sec,
            verify=config.verify_tls,
            transport=transport,
        )

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
        state.last_heartbeat_at = datetime.now(timezone.utc).isoformat()
        state.last_server_time = payload["server_time"]
        self.store.save(state)
        return payload

    def _send_heartbeat(self, state: AgentState) -> httpx.Response:
        return self.http.post(
            "/api/v1/agent/heartbeat",
            headers={"Authorization": f"Bearer {state.access_token}"},
            json={
                "policy_version": state.policy_version,
                "agent_version": AGENT_VERSION,
                "quota_used_sec": state.quota_used_sec,
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
    LOGGER.info("Agent started; heartbeat interval=%s seconds", interval)
    while not stopped.is_set():
        try:
            reply = client.heartbeat()
            LOGGER.info(
                "Heartbeat accepted; policy=%s update=%s commands=%s",
                reply["policy_version"],
                reply["policy_update_available"],
                len(reply.get("commands", [])),
            )
        except (httpx.HTTPError, RuntimeError, KeyError) as exc:
            LOGGER.error("Heartbeat failed: %s", exc)
        stopped.wait(interval)


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
