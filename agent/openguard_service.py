"""OpenGuard Kids Windows Service: the protection runtime under LocalSystem.

Run from an elevated PowerShell in the project folder:

    .\\.venv\\Scripts\\python.exe agent\\openguard_service.py install   # install, harden, start
    .\\.venv\\Scripts\\python.exe agent\\openguard_service.py status
    .\\.venv\\Scripts\\python.exe agent\\openguard_service.py remove    # stop, restore DNS, uninstall

The Service Control Manager starts `python.exe openguard_service.py` without arguments, which
hands the process to the service dispatcher.
"""

from __future__ import annotations

import os
import site
import sys

# A service started from a virtual environment runs the base interpreter (the venv launcher
# would spawn a child the SCM does not track); the installer passes the venv site-packages here.
if os.getenv("OGK_SITE_PACKAGES"):
    site.addsitedir(os.environ["OGK_SITE_PACKAGES"])

import argparse  # noqa: E402
import logging  # noqa: E402
import logging.handlers  # noqa: E402
import sysconfig  # noqa: E402
from pathlib import Path  # noqa: E402

AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))

from service.windows.hardening import (SERVICE_NAME, configure_service, harden_data_dir, is_admin,  # noqa: E402
                                       write_protected_env)

DISPLAY_NAME = "OpenGuard Kids Protection"
DESCRIPTION = ("Áp dụng giới hạn thời gian, chặn ứng dụng/tên miền theo chính sách phụ huynh. "
               "Biểu tượng khay hệ thống luôn hiển thị khi dịch vụ chạy.")
LOGGER = logging.getLogger("openguard-agent.service")
# Settings the protected env file carries over from the project .env at install time.
CARRIED_SETTINGS = ("OGK_SERVER_URL", "OGK_POLICY_HMAC_SECRET", "OGK_HEARTBEAT_INTERVAL_SEC", "OGK_REQUEST_TIMEOUT_SEC",
                    "OGK_USAGE_TICK_SEC", "OGK_RELOCK_DELAY_SEC", "OGK_VERIFY_TLS", "OGK_APPS_ENABLED",
                    "OGK_APP_POLL_SEC", "OGK_DNS_ENABLED", "OGK_DNS_PORT", "OGK_DNS_UPSTREAM", "OGK_EVENT_SYNC_SEC",
                    "OGK_REPORT_TIMEZONE_OFFSET_MINUTES", "OGK_OFFLINE_CLOCK", "OGK_DNS_AUTOCONFIG",
                    "OGK_DNS_FAILURE_MODE")


def data_dir() -> Path:
    return Path(os.getenv("PROGRAMDATA", r"C:\ProgramData")) / "OpenGuardKids"


def configure_logging() -> None:
    logs = data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(logs / "service.log", maxBytes=2_000_000, backupCount=5,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def audit(event_type: str, details: str) -> None:
    """Local, append-only record of service lifecycle (the parent sees the device go offline)."""
    try:
        from openguard_agent import AgentConfig
        from service.policy import PolicyRepository
        config = AgentConfig.from_env()
        PolicyRepository(config.database_path or config.state_path.with_name("agent.db")).security_event(
            event_type, details)
    except Exception as exc:
        LOGGER.warning("Could not record %s: %s", event_type, exc)


if os.name == "nt":
    import servicemanager
    import win32service
    import win32serviceutil

    class OpenGuardService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.runtime = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=60_000)
            audit("SERVICE_STOP", "Stop requested through the Service Control Manager")
            if self.runtime is not None:
                self.runtime.request_stop()

        def SvcShutdown(self):
            audit("SERVICE_SHUTDOWN", "Windows is shutting down")
            if self.runtime is not None:
                self.runtime.request_stop()

        def SvcDoRun(self):
            configure_logging()
            servicemanager.LogInfoMsg(f"{DISPLAY_NAME} starting")
            try:
                harden_data_dir(data_dir())
            except Exception as exc:
                LOGGER.error("Data folder ACL could not be applied: %s", exc)
            from service.runtime import build_service_runtime
            try:
                self.runtime = build_service_runtime()
                self.runtime.start()
            except Exception:
                LOGGER.exception("Runtime failed to start")
                os._exit(1)  # Not a clean stop: SCM recovery restarts the service.
            audit("SERVICE_START", f"Runtime started as {self.runtime.host.name}")
            self.runtime.wait()
            self.runtime.stop()
            if self.runtime.fatal:
                LOGGER.critical("Exiting for recovery: %s", self.runtime.fatal)
                os._exit(1)


def install(args) -> int:
    if not is_admin():
        print("Cần chạy PowerShell bằng quyền Administrator.", file=sys.stderr)
        return 1
    from openguard_agent import AgentConfig
    AgentConfig.from_env()  # Fail before installing anything if the configuration is invalid.
    values = {key: os.environ[key] for key in CARRIED_SETTINGS if os.getenv(key)}
    values["OGK_TRAY_PYTHON"] = sys.executable
    harden_data_dir(data_dir())
    write_protected_env(data_dir() / "agent.env", values)
    in_venv = sys.prefix != sys.base_prefix
    interpreter = getattr(sys, "_base_executable", sys.executable) if in_venv else sys.executable
    win32serviceutil.InstallService(
        win32serviceutil.GetServiceClassString(OpenGuardService), SERVICE_NAME, DISPLAY_NAME,
        startType=win32service.SERVICE_AUTO_START, exeName=interpreter, exeArgs=f'"{Path(__file__).resolve()}"',
        description=DESCRIPTION)
    if in_venv:
        import winreg
        key = rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, "Environment", 0, winreg.REG_MULTI_SZ,
                              [f"OGK_SITE_PACKAGES={sysconfig.get_paths()['purelib']}"])
    configure_service()
    if not args.no_start:
        win32serviceutil.StartService(SERVICE_NAME)
        win32serviceutil.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_RUNNING, 60)
    print(f"Đã cài {DISPLAY_NAME}. Dữ liệu và log: {data_dir()}")
    project_env = AGENT_DIR.parent / ".env"
    if project_env.exists():
        print(f"Cấu hình đã được chép vào {data_dir() / 'agent.env'} (chỉ SYSTEM/Administrators đọc được). "
              f"Hãy xóa hoặc giới hạn quyền đọc {project_env} để tài khoản của trẻ không đọc được secret.")
    return 0


def remove(_args) -> int:
    if not is_admin():
        print("Cần chạy PowerShell bằng quyền Administrator.", file=sys.stderr)
        return 1
    audit("SERVICE_UNINSTALL", "Uninstalled by an administrator")
    try:
        win32serviceutil.StopService(SERVICE_NAME)
        win32serviceutil.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_STOPPED, 90)
    except Exception as exc:
        print(f"Dịch vụ không chạy hoặc không dừng được: {exc}")
    # The runtime restores DNS when it stops; repeat from the saved backup in case it had crashed.
    from openguard_agent import AgentConfig
    from service.windows.network import NetworkGuard
    config = AgentConfig.from_env()
    NetworkGuard(config.database_path or config.state_path.with_name("agent.db"), upstream=config.dns_upstream).restore()
    try:
        win32serviceutil.RemoveService(SERVICE_NAME)
    except Exception as exc:
        # An administrator may already have removed it using sc.exe delete.
        # Network restoration above must still be possible in that case.
        if getattr(exc, 'winerror', None) != 1060:
            raise
    print("Đã gỡ dịch vụ và khôi phục cấu hình DNS/firewall/trình duyệt.")
    return 0


def status(_args) -> int:
    state = {1: "STOPPED", 2: "START_PENDING", 3: "STOP_PENDING", 4: "RUNNING"}
    try:
        current = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
    except Exception:
        print("Chưa cài dịch vụ.")
        return 1
    print(f"{SERVICE_NAME}: {state.get(current, current)}")
    return 0


def main() -> int:
    if os.name != "nt":
        print("Windows Service chỉ có trên Windows; dùng `python openguard_agent.py run` để chạy runtime.",
              file=sys.stderr)
        return 1
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(OpenGuardService)
        servicemanager.StartServiceCtrlDispatcher()
        return 0
    parser = argparse.ArgumentParser(description="OpenGuard Kids Windows Service")
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install", help="install, harden and start the service")
    install_parser.add_argument("--no-start", action="store_true")
    commands.add_parser("remove", help="stop, restore network settings and uninstall")
    commands.add_parser("status", help="show the service state")
    args = parser.parse_args()
    return {"install": install, "remove": remove, "status": status}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
