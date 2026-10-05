"""Small OS boundary for activity/session checks and workstation locking."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    if os.name != "nt":
        return 0.0
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    elapsed_ms = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def is_user_active(idle_timeout_sec: int) -> bool:
    return idle_seconds() < idle_timeout_sec


def is_session_unlocked() -> bool:
    # The interactive desktop cannot be opened while the Windows secure desktop is active.
    if os.name != "nt":
        return True
    desktop = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
    if not desktop:
        return False
    ctypes.windll.user32.CloseDesktop(desktop)
    return True


def lock_workstation() -> bool:
    if os.name != "nt":
        return False
    return bool(ctypes.windll.user32.LockWorkStation())
