"""Install-time hardening: who may stop the service, crash recovery, and data-folder ACLs.

None of this hides the agent: the service stays visible in services.msc and Task Manager, and
an administrator (the parent) can always stop or uninstall it.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

SERVICE_NAME = "OpenGuardKids"
# Windows' default service DACL minus nothing for SYSTEM/Administrators; interactive and service
# accounts may only query (no RP start / WP stop / DT pause), so the child cannot `sc stop` it.
SERVICE_SDDL = ("D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)"
                "(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)")
# Restart after 5 s, 5 s, then 30 s; the failure counter resets after a day without crashes.
FAILURE_ACTIONS = ("reset=", "86400", "actions=", "restart/5000/restart/5000/restart/30000")
CREATE_NO_WINDOW = 0x08000000


def is_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _run(*command: str) -> None:
    completed = subprocess.run(list(command), capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(command)} failed: {(completed.stdout + completed.stderr).strip()}")


def configure_service(name: str = SERVICE_NAME) -> None:
    _run("sc.exe", "failure", name, *FAILURE_ACTIONS)
    # Also treat a non-zero exit (crash loop detected by the runtime) as a failure to recover from.
    _run("sc.exe", "failureflag", name, "1")
    _run("sc.exe", "sdset", name, SERVICE_SDDL)


def harden_data_dir(path: Path) -> None:
    """Only SYSTEM and Administrators may read or write tokens, policy cache and the event queue."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)
        return
    _run("icacls.exe", str(path), "/inheritance:r", "/grant:r",
         "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F", "/T", "/C", "/Q")


def write_protected_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in sorted(values.items()) if "\n" not in str(value)]
    path.write_text("# Written by openguard_service.py install\n" + "\n".join(lines) + "\n", encoding="utf-8")
