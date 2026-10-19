"""Local IPC server: a restricted Windows named pipe, or a Unix socket for development."""

from __future__ import annotations

import logging
import os
import socket
import socketserver
import struct
import threading
from pathlib import Path

from .protocol import (IO_TIMEOUT_SEC, MAX_REQUEST_BYTES, Caller, IPCError, decode, encode, respond)

LOGGER = logging.getLogger("openguard-agent.ipc")

# SYSTEM and Administrators: full. Interactive users: read + write data only; omitting
# FILE_APPEND_DATA (= FILE_CREATE_PIPE_INSTANCE) stops a child from squatting the pipe name.
# Network logons are denied outright.
PIPE_SDDL = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x12019b;;;IU)(D;;GA;;;NU)"
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
MAX_WORKERS = 8


def create_server(address: str, handler):
    if os.name == "nt" and address.startswith("\\\\.\\pipe\\"):
        return NamedPipeServer(address, handler)
    return UnixSocketServer(address, handler)


class UnixSocketServer:
    """Development transport; caller identity comes from SO_PEERCRED."""

    def __init__(self, address: str, handler):
        self.path, self.handler = Path(address), handler
        self._server: socketserver.ThreadingUnixStreamServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(str(self.path))
                raise RuntimeError(f"Another OpenGuard runtime is listening on {self.path}")
            except (ConnectionRefusedError, FileNotFoundError):
                self.path.unlink()
            finally:
                probe.close()
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            timeout = IO_TIMEOUT_SEC

            def handle(self):
                try:
                    line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
                    request = decode(line, MAX_REQUEST_BYTES)
                except (OSError, ValueError, IPCError):
                    return
                self.wfile.write(encode(respond(outer.handler, request, outer._caller(self.request))))

        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True

        self._server = Server(str(self.path), Handler)
        # Root (a service-like dev run) serves every local user; otherwise only the owner.
        os.chmod(self.path, 0o666 if os.geteuid() == 0 else 0o600)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="openguard-ipc", daemon=True)
        self._thread.start()

    @staticmethod
    def _caller(connection: socket.socket) -> Caller:
        try:
            pid, uid, _gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                                       struct.calcsize("3i")))
        except (OSError, AttributeError):
            return Caller(None, False)
        return Caller(pid, uid == 0)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class NamedPipeServer:
    """Overlapped named pipe server so a stalled client can never block the service."""

    def __init__(self, name: str, handler):
        self.name, self.handler = name, handler
        self._stop = threading.Event()
        self._slots = threading.BoundedSemaphore(MAX_WORKERS)
        self._thread: threading.Thread | None = None
        self._first = True

    def start(self) -> None:
        # Creating the first instance here surfaces a squatted/duplicate pipe immediately.
        self._pending = self._create()
        self._thread = threading.Thread(target=self._serve, name="openguard-ipc", daemon=True)
        self._thread.start()

    def _create(self):
        import pywintypes
        import win32file
        import win32pipe
        import win32security
        attributes = win32security.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            PIPE_SDDL, win32security.SDDL_REVISION_1)
        open_mode = win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED
        if self._first:
            open_mode |= FILE_FLAG_FIRST_PIPE_INSTANCE
        pipe_mode = (win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT
                     | PIPE_REJECT_REMOTE_CLIENTS)
        try:
            handle = win32pipe.CreateNamedPipe(self.name, open_mode, pipe_mode, win32pipe.PIPE_UNLIMITED_INSTANCES,
                                               65536, 65536, 0, attributes)
        except pywintypes.error as exc:
            raise RuntimeError(f"Cannot create IPC pipe {self.name} (already in use?): {exc}") from exc
        self._first = False
        return handle

    def _serve(self) -> None:
        import pywintypes
        import win32event
        import win32file
        import win32pipe
        import winerror
        pipe = self._pending
        while not self._stop.is_set():
            overlapped = pywintypes.OVERLAPPED()
            overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
            try:
                connected = win32pipe.ConnectNamedPipe(pipe, overlapped) == winerror.ERROR_PIPE_CONNECTED
                while not connected and not self._stop.is_set():
                    connected = win32event.WaitForSingleObject(overlapped.hEvent, 500) == win32event.WAIT_OBJECT_0
            except pywintypes.error as exc:
                LOGGER.warning("IPC connect failed: %s", exc)
                connected = False
            if self._stop.is_set():
                win32file.CloseHandle(pipe)
                break
            if connected and self._slots.acquire(blocking=False):
                threading.Thread(target=self._serve_client, args=(pipe,), daemon=True,
                                 name="openguard-ipc-client").start()
            else:
                win32file.CloseHandle(pipe)
            try:
                pipe = self._create()
            except RuntimeError:
                LOGGER.exception("IPC pipe could not be recreated")
                self._stop.wait(1)
                continue

    @staticmethod
    def _io(pipe, operation, timeout: float):
        import pywintypes
        import win32event
        import win32file
        import winerror
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        try:
            operation(overlapped)
        except pywintypes.error as exc:
            if exc.winerror in {winerror.ERROR_BROKEN_PIPE, winerror.ERROR_PIPE_NOT_CONNECTED}:
                return None
            raise
        if win32event.WaitForSingleObject(overlapped.hEvent, int(timeout * 1000)) != win32event.WAIT_OBJECT_0:
            win32file.CancelIo(pipe)
            raise TimeoutError("IPC client too slow")
        try:
            return win32file.GetOverlappedResult(pipe, overlapped, False)
        except pywintypes.error as exc:
            if exc.winerror in {winerror.ERROR_BROKEN_PIPE, winerror.ERROR_PIPE_NOT_CONNECTED}:
                return 0
            raise

    def _serve_client(self, pipe) -> None:
        import win32file
        import win32pipe
        try:
            data = b""
            buffer = win32file.AllocateReadBuffer(4096)
            while b"\n" not in data:
                count = self._io(pipe, lambda o: win32file.ReadFile(pipe, buffer, o), IO_TIMEOUT_SEC)
                if not count:
                    return
                data += bytes(buffer[:count])
                if len(data) > MAX_REQUEST_BYTES:
                    return
            request = decode(data.split(b"\n", 1)[0], MAX_REQUEST_BYTES)
            payload = encode(respond(self.handler, request, self._caller(pipe)))
            self._io(pipe, lambda o: win32file.WriteFile(pipe, payload, o), IO_TIMEOUT_SEC)
            # Wait for the client to read and close instead of a FlushFileBuffers that could hang.
            try:
                self._io(pipe, lambda o: win32file.ReadFile(pipe, buffer, o), IO_TIMEOUT_SEC)
            except TimeoutError:
                pass
        except Exception as exc:
            LOGGER.debug("IPC client dropped: %s", exc)
        finally:
            try:
                win32pipe.DisconnectNamedPipe(pipe)
            except Exception:
                pass
            win32file.CloseHandle(pipe)
            self._slots.release()

    @staticmethod
    def _caller(pipe) -> Caller:
        import win32api
        import win32pipe
        import win32security
        pid = session = None
        try:
            pid = int(win32pipe.GetNamedPipeClientProcessId(pipe))
            session = int(win32pipe.GetNamedPipeClientSessionId(pipe))
        except Exception:
            pass
        admin = False
        try:
            win32pipe.ImpersonateNamedPipeClient(pipe)
            try:
                token = win32security.OpenThreadToken(win32api.GetCurrentThread(), win32security.TOKEN_QUERY, True)
                administrators = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid)
                # Under UAC a non-elevated admin carries this SID as deny-only, so this is False.
                admin = bool(win32security.CheckTokenMembership(token, administrators))
            finally:
                win32security.RevertToSelf()
        except Exception as exc:
            LOGGER.debug("IPC caller identity unavailable: %s", exc)
        return Caller(pid, admin, session)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
