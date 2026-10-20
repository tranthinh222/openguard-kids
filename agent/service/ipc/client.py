"""Tray-side IPC client; one short-lived connection per call."""

from __future__ import annotations

import socket
import time

from .protocol import (IO_TIMEOUT_SEC, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, IPCError, ServiceUnavailableError,
                       decode, encode)

# FILE_GENERIC_READ | FILE_WRITE_DATA: exactly what the pipe DACL grants interactive users.
PIPE_CLIENT_ACCESS = 0x0012008B


class IPCClient:
    def __init__(self, address: str, timeout: float = IO_TIMEOUT_SEC):
        self.address, self.timeout = address, timeout

    def call(self, method: str, **params):
        request = encode({"method": method, "params": params})
        if len(request) > MAX_REQUEST_BYTES:
            raise IPCError("too_large", "IPC request too large")
        raw = self._exchange_pipe(request) if self.address.startswith("\\\\.\\pipe\\") else self._exchange_unix(request)
        reply = decode(raw, MAX_RESPONSE_BYTES)
        if not reply.get("ok"):
            error = reply.get("error") or {}
            raise IPCError(str(error.get("code", "internal")), str(error.get("message", "IPC call failed")))
        return reply.get("result")

    def _exchange_unix(self, request: bytes) -> bytes:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        try:
            try:
                connection.connect(self.address)
            except (FileNotFoundError, ConnectionRefusedError) as exc:
                raise ServiceUnavailableError() from exc
            connection.sendall(request)
            return self._read_line(lambda: connection.recv(65536))
        except socket.timeout as exc:
            raise ServiceUnavailableError("OpenGuard service did not answer in time") from exc
        finally:
            connection.close()

    def _exchange_pipe(self, request: bytes) -> bytes:
        import pywintypes
        import win32file
        import win32pipe
        import winerror
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                handle = win32file.CreateFile(self.address, PIPE_CLIENT_ACCESS, 0, None, win32file.OPEN_EXISTING, 0, None)
                break
            except pywintypes.error as exc:
                if exc.winerror == winerror.ERROR_PIPE_BUSY and time.monotonic() < deadline:
                    try:
                        win32pipe.WaitNamedPipe(self.address, 500)
                    except pywintypes.error:
                        time.sleep(0.05)
                    continue
                raise ServiceUnavailableError() from exc
        try:
            win32file.WriteFile(handle, request)
            return self._read_line(lambda: bytes(win32file.ReadFile(handle, 65536)[1]))
        except pywintypes.error as exc:
            raise ServiceUnavailableError("OpenGuard service closed the connection") from exc
        finally:
            handle.Close()

    @staticmethod
    def _read_line(read) -> bytes:
        data = b""
        while b"\n" not in data:
            chunk = read()
            if not chunk:
                raise ServiceUnavailableError("OpenGuard service closed the connection")
            data += chunk
            if len(data) > MAX_RESPONSE_BYTES:
                raise IPCError("too_large", "IPC response too large")
        return data.split(b"\n", 1)[0]


def default_client(state_path) -> IPCClient:
    from .protocol import default_address
    return IPCClient(default_address(state_path))
