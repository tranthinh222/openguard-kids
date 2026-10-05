"""Reconnectable synchronous WebSocket worker for real-time commands."""

from __future__ import annotations

import json
import logging
import random
import ssl
import threading
from typing import Callable
from urllib.parse import urlparse, urlunparse

from websockets.sync.client import connect

from service.commands import CommandHandler

LOGGER = logging.getLogger("openguard-agent.websocket")


def websocket_url(server_url: str) -> str:
    parsed = urlparse(server_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/api/v1/agent/ws", "", "", ""))


class WebSocketWorker:
    def __init__(
        self,
        server_url: str,
        token_provider: Callable[[], str],
        handler: CommandHandler,
        verify_tls: bool = True,
        connector=connect,
        on_auth_failure: Callable[[], None] | None = None,
    ):
        self.url = websocket_url(server_url)
        self.token_provider = token_provider
        self.handler = handler
        self.verify_tls = verify_tls
        self.connector = connector
        self.on_auth_failure = on_auth_failure
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="openguard-websocket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                kwargs = {"additional_headers": {"Authorization": f"Bearer {self.token_provider()}"}, "open_timeout": 10}
                if self.url.startswith("wss://") and not self.verify_tls:
                    kwargs["ssl"] = ssl._create_unverified_context()
                with self.connector(self.url, **kwargs) as websocket:
                    backoff = 1.0
                    while not self._stop.is_set():
                        try:
                            raw = websocket.recv(timeout=1)
                        except TimeoutError:
                            continue
                        command = json.loads(raw)
                        result = self.handler.handle(command)
                        websocket.send(json.dumps({
                            "type": "ack", "command_id": result.command_id,
                            "status": result.status, "error": result.error,
                        }))
            except Exception as exc:
                if not self._stop.is_set():
                    received = getattr(exc, "rcvd", None)
                    response = getattr(exc, "response", None)
                    code = getattr(received, "code", None)
                    status = getattr(response, "status_code", None)
                    if self.on_auth_failure is not None and (code in {4401, 4403} or status in {401, 403}):
                        try:
                            self.on_auth_failure()
                        except Exception as refresh_exc:
                            LOGGER.warning("WebSocket token refresh failed: %s", refresh_exc)
                    LOGGER.warning("WebSocket disconnected: %s", exc)
                    self._stop.wait(backoff + random.uniform(0, backoff * 0.2))
                    backoff = min(backoff * 2, 30)
