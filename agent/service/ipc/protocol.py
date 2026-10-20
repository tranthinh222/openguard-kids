"""One JSON request line and one JSON response line per local connection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

PIPE_NAME = r"\\.\pipe\OpenGuardKids"
MAX_REQUEST_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
IO_TIMEOUT_SEC = 5.0
# sockaddr_un.sun_path is 108 bytes on Linux (104 on macOS).
MAX_UNIX_PATH = 100


class IPCError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ServiceUnavailableError(IPCError):
    def __init__(self, message: str = "OpenGuard service is not running"):
        super().__init__("unavailable", message)


@dataclass(frozen=True)
class Caller:
    """Identity of the local client as reported by the OS, never by the client itself."""
    pid: int | None
    admin: bool
    session: int | None = None


def default_address(state_path: Path) -> str:
    configured = os.getenv("OGK_IPC_ADDRESS")
    if configured:
        return configured
    if os.name == "nt":
        return PIPE_NAME
    path = str(state_path.with_name("agent.sock"))
    if len(os.fsencode(path)) <= MAX_UNIX_PATH:
        return path
    digest = hashlib.sha256(os.fsencode(path)).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"openguard-{os.getuid()}-{digest}.sock")


def encode(message: dict) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str).encode() + b"\n"


def decode(line: bytes, limit: int) -> dict:
    if len(line) > limit:
        raise IPCError("too_large", "IPC message too large")
    message = json.loads(line.decode())
    if not isinstance(message, dict):
        raise IPCError("bad_request", "IPC message must be an object")
    return message


def respond(handler, request: dict, caller: Caller) -> dict:
    """Run one request through `handler(method, params, caller)`; never leak tracebacks."""
    method, params = request.get("method"), request.get("params") or {}
    if not isinstance(method, str) or not isinstance(params, dict):
        return {"ok": False, "error": {"code": "bad_request", "message": "Invalid IPC request"}}
    try:
        return {"ok": True, "result": handler(method, params, caller)}
    except IPCError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except PermissionError as exc:
        return {"ok": False, "error": {"code": "forbidden", "message": str(exc)}}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": {"code": "bad_request", "message": str(exc)}}
    except Exception:
        import logging
        logging.getLogger("openguard-agent.ipc").exception("IPC method %s failed", method)
        return {"ok": False, "error": {"code": "internal", "message": "Internal service error"}}
