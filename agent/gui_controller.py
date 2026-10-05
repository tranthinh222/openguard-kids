"""UI-independent application logic for the OpenGuard desktop agent."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime
from typing import Callable
from urllib.parse import urlparse

import httpx

from openguard_agent import AgentClient, AgentConfig, AgentNotEnrolledError, AgentState, StateStore

NETWORK_ERROR = "Không kết nối được server. Kiểm tra Internet và thử lại."

# Server `detail` messages mapped to wording a child or parent can act on.
SERVER_MESSAGES = {
    "Invalid enrollment code": "Mã không đúng. Kiểm tra lại mã trên trang phụ huynh.",
    "Enrollment code already used": "Mã này đã được dùng. Hãy tạo mã mới trên trang phụ huynh.",
    "Enrollment code expired": "Mã đã hết hạn. Hãy tạo mã mới trên trang phụ huynh.",
    "Invalid refresh token": "Phiên đăng nhập của thiết bị đã hết hạn. Hãy ghép lại thiết bị.",
    "Device revoked": "Thiết bị đã bị gỡ khỏi trang phụ huynh. Hãy ghép lại thiết bị.",
}


def normalize_enrollment_code(value: str) -> str:
    code = "".join(value.split()).upper()
    if len(code) != 8 or not code.isalnum():
        raise ValueError("Mã ghép đôi phải gồm đúng 8 chữ cái hoặc chữ số.")
    return code


def normalize_server_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Địa chỉ server phải bắt đầu bằng http:// hoặc https://.")
    return url


def is_network_error(exc: Exception) -> bool:
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


def describe_error(exc: Exception) -> str:
    """Turn agent/network exceptions into a short Vietnamese message for the GUI."""
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, AgentNotEnrolledError):
        return "Thiết bị chưa được ghép với trang phụ huynh."
    if is_network_error(exc):
        return NETWORK_ERROR
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        try:
            detail = response.json().get("message") or response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if detail in SERVER_MESSAGES:
            return SERVER_MESSAGES[detail]
        if response.status_code >= 500:
            return "Server đang gặp sự cố. Hãy thử lại sau ít phút."
        return f"Server từ chối yêu cầu (mã {response.status_code}). Hãy thử lại hoặc tạo mã mới."
    if isinstance(exc, RuntimeError):
        return "Không đọc được dữ liệu agent trên máy này."
    return "Đã có lỗi không mong muốn. Hãy thử lại."


def needs_reenroll(exc: Exception) -> bool:
    """The server rejected this device's tokens, so only a new pairing can fix it."""
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 401


def format_sync_time(value: str | None, now: datetime | None = None) -> str:
    """Show an ISO timestamp as local HH:MM, adding the date when it is not today."""
    if not value:
        return "chưa đồng bộ"
    try:
        moment = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return "không rõ"
    now = now or datetime.now().astimezone()
    if moment.date() == now.date():
        return moment.strftime("%H:%M")
    return moment.strftime("%H:%M, %d/%m/%Y")


class AgentController:
    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig.from_env()
        self.store = StateStore(self.config.state_path)
        # Commands arrive over WebSocket or heartbeat; both report through this callback.
        self.on_command_event: Callable[[dict], None] | None = None

    def state(self) -> AgentState:
        return self.store.load()

    def set_server_url(self, server_url: str) -> None:
        self.config = replace(self.config, server_url=normalize_server_url(server_url))

    def enroll(self, code: str, server_url: str) -> AgentState:
        self.set_server_url(server_url)
        client = AgentClient(self.config, self.store)
        try:
            return client.enroll(normalize_enrollment_code(code))
        finally:
            client.close()

    def heartbeat(self) -> dict:
        client = AgentClient(self.config, self.store, on_command_event=self.on_command_event)
        try:
            return client.heartbeat()
        finally:
            client.close()

    def request_extra_time(self, minutes: int = 15) -> dict:
        client = AgentClient(self.config, self.store)
        try:
            return client.request_extra_time(minutes)
        finally:
            client.close()


class HeartbeatWorker:
    def __init__(self, controller: AgentController, on_result: Callable[[dict | None, Exception | None], None]):
        self.controller = controller
        self.on_result = on_result
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        if self.running:
            return
        # A fresh event per run lets a restart begin while the old thread is still
        # finishing a request; the old thread sees its own event set and exits quietly.
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="openguard-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                result, error = self.controller.heartbeat(), None
            except Exception as exc:
                result, error = None, exc
            if not stop.is_set():
                self.on_result(result, error)
            stop.wait(self.controller.config.heartbeat_interval_sec)


class ProtectionWorker:
    """Run screen-time enforcement and real-time commands outside Tk."""

    def __init__(self, controller: AgentController, on_event: Callable[[dict], None]):
        self.controller = controller
        self.on_event = on_event
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="openguard-protection", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self, stop: threading.Event) -> None:
        client = AgentClient(self.controller.config, self.controller.store, on_command_event=self.on_event)
        websocket = None
        try:
            counter = client.screen_time_counter(self.on_event)
            websocket = client.websocket_worker()
            websocket.start()
            while not stop.is_set():
                result = counter.tick()
                for event in result.events:
                    if event.get("type") == "GRACE_TICK":
                        self.on_event(event)
                stop.wait(min(self.controller.config.usage_tick_sec, 5.0))
        except Exception as exc:
            self.on_event({"type": "PROTECTION_ERROR", "error": exc})
        finally:
            if websocket is not None:
                websocket.stop()
            client.close()
