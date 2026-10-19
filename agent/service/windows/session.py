"""WTS helpers for a LocalSystem service acting on the child's interactive session.

A service runs in session 0, where GetLastInputInfo, OpenInputDesktop and LockWorkStation
see the service desktop instead of the child's. These helpers address the active console
session explicitly. Every function is a no-op (or returns None) outside Windows.
"""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

LOGGER = logging.getLogger("openguard-agent.session")

NO_SESSION = 0xFFFFFFFF
WTS_CURRENT_SERVER_HANDLE = None
WTS_SESSION_INFO_EX = 25
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1
WTS_ACTIVE = 0
CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400


class _InfoExLevel1(ctypes.Structure):
    _fields_ = [("SessionId", wintypes.ULONG), ("SessionState", ctypes.c_int), ("SessionFlags", wintypes.LONG),
                ("WinStationName", ctypes.c_wchar * 33), ("UserName", ctypes.c_wchar * 21),
                ("DomainName", ctypes.c_wchar * 18), ("LogonTime", ctypes.c_longlong),
                ("ConnectTime", ctypes.c_longlong), ("DisconnectTime", ctypes.c_longlong),
                ("LastInputTime", ctypes.c_longlong), ("CurrentTime", ctypes.c_longlong),
                ("IncomingBytes", wintypes.DWORD), ("OutgoingBytes", wintypes.DWORD),
                ("IncomingFrames", wintypes.DWORD), ("OutgoingFrames", wintypes.DWORD),
                ("IncomingCompressedBytes", wintypes.DWORD), ("OutgoingCompressedBytes", wintypes.DWORD)]


class _InfoEx(ctypes.Structure):
    # The LARGE_INTEGER members make ctypes align Data at offset 8, matching WTSINFOEXW.
    _fields_ = [("Level", wintypes.DWORD), ("Data", _InfoExLevel1)]


def active_console_session() -> int | None:
    if os.name != "nt":
        return None
    session = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    return None if session in {NO_SESSION, 0} else int(session)


def session_unlocked(session: int | None) -> bool:
    """True only for an active, unlocked session; unknown or logged-off counts as locked."""
    if os.name != "nt" or session is None:
        return False
    wtsapi = ctypes.windll.wtsapi32
    buffer, size = ctypes.c_void_p(), wintypes.DWORD()
    if not wtsapi.WTSQuerySessionInformationW(WTS_CURRENT_SERVER_HANDLE, session, WTS_SESSION_INFO_EX,
                                              ctypes.byref(buffer), ctypes.byref(size)):
        return False
    try:
        info = ctypes.cast(buffer, ctypes.POINTER(_InfoEx)).contents.Data
        return info.SessionState == WTS_ACTIVE and info.SessionFlags == WTS_SESSIONSTATE_UNLOCK
    finally:
        wtsapi.WTSFreeMemory(buffer)


def launch_in_session(session: int, command: str, cwd: str | None = None, hidden: bool = True) -> int | None:
    """Start `command` as the user logged on to `session`; returns the PID or None."""
    if os.name != "nt":
        return None
    import win32con
    import win32process
    import win32profile
    import win32ts
    token = win32ts.WTSQueryUserToken(session)
    try:
        environment = win32profile.CreateEnvironmentBlock(token, False)
        startup = win32process.STARTUPINFO()
        startup.lpDesktop = "winsta0\\default"
        if hidden:
            startup.dwFlags = win32con.STARTF_USESHOWWINDOW
            startup.wShowWindow = win32con.SW_HIDE
        flags = CREATE_UNICODE_ENVIRONMENT | (CREATE_NO_WINDOW if hidden else 0)
        process, thread, pid, _tid = win32process.CreateProcessAsUser(
            token, None, command, None, None, False, flags, environment, cwd, startup)
        process.Close()
        thread.Close()
        return int(pid)
    finally:
        token.Close()


def lock_session(session: int | None) -> bool:
    """LockWorkStation must run inside the target session; disconnecting is the fallback."""
    if os.name != "nt" or session is None:
        return False
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    try:
        if launch_in_session(session, f'"{system32}\\rundll32.exe" user32.dll,LockWorkStation'):
            return True
    except Exception as exc:  # pywin32 raises pywintypes.error
        LOGGER.warning("LockWorkStation in session %s failed: %s", session, exc)
    # Disconnecting the console session shows the Windows sign-in screen; apps keep running.
    return bool(ctypes.windll.wtsapi32.WTSDisconnectSession(WTS_CURRENT_SERVER_HANDLE, session, False))


def process_session(pid: int) -> int | None:
    if os.name != "nt":
        return None
    value = wintypes.DWORD()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(value)):
        return None
    return int(value.value)
