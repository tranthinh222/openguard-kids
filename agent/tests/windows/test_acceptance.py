"""Week 04 A7: acceptance tests against a real Windows 10/11 machine with the service installed.

They change real OS state (kill processes, start a renamed executable) and are skipped unless
explicitly enabled. Run from an elevated PowerShell on the test machine, signed in on the console:

    $env:OGK_WINDOWS_ACCEPTANCE = '1'
    $env:OGK_ACCEPTANCE_BLOCKED_DOMAIN = 'example.com'     # in the child's block list
    $env:OGK_ACCEPTANCE_BLOCKED_SHA256 = '<sha256 of notepad.exe>'  # app rule with this hash
    .\\.venv\\Scripts\\python.exe -m pytest agent/tests/windows -v -rs

Every test appends what it observed to %TEMP%\\openguard-acceptance.jsonl as evidence.
Screen lock, idle and reboot need a person at the keyboard: see WEEK04.md, section A7.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt" or os.getenv("OGK_WINDOWS_ACCEPTANCE") != "1",
                                reason="real Windows acceptance run not enabled (OGK_WINDOWS_ACCEPTANCE=1)")

SERVICE = "OpenGuardKids"
EVIDENCE = Path(tempfile.gettempdir()) / "openguard-acceptance.jsonl"


def evidence(test: str, **observed) -> None:
    with EVIDENCE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "test": test, **observed},
                                ensure_ascii=False, default=str) + "\n")


def powershell(script: str) -> str:
    return subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True,
                          timeout=60).stdout.strip()


def wait_for(predicate, timeout: float, step: float = 0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return None


def service_pid() -> int:
    import win32service
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        handle = win32service.OpenService(manager, SERVICE, win32service.SERVICE_QUERY_STATUS)
        try:
            status = win32service.QueryServiceStatusEx(handle)
        finally:
            win32service.CloseServiceHandle(handle)
    finally:
        win32service.CloseServiceHandle(manager)
    assert status["CurrentState"] == win32service.SERVICE_RUNNING
    return int(status["ProcessId"])


def status() -> dict:
    from service.ipc import IPCClient
    from service.ipc.protocol import PIPE_NAME
    return IPCClient(PIPE_NAME).call("status")


def tray_processes():
    import psutil
    found = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        cmdline = " ".join(process.info["cmdline"] or [])
        if "agent_gui.py" in cmdline:
            found.append(process)
    return found


def test_service_is_auto_start_recoverable_and_not_stoppable_by_users():
    config = powershell(f"sc.exe qc {SERVICE}; sc.exe qfailure {SERVICE}; sc.exe sdshow {SERVICE}")
    evidence("service_config", output=config)
    assert "AUTO_START" in config and "LocalSystem" in config
    assert "RESTART -- Delay = 5000" in config
    descriptor = config.splitlines()[-1]
    interactive = [ace for ace in descriptor.split(")") if ace.endswith(";IU")]
    assert interactive and all("WP" not in ace and "RP" not in ace for ace in interactive)


def test_ipc_status_comes_from_the_service():
    current = status()
    evidence("ipc_status", host=current["host"], protection=current["protection_running"],
             clock=current["clock"], dns=current["dns"])
    assert current["host"] == "windows_service" and current["protection_running"]


def test_closing_tray_keeps_protection_and_tray_returns():
    trays = wait_for(tray_processes, 30)
    assert trays, "tray is not running in the console session"
    for tray in trays:
        tray.kill()
    assert status()["protection_running"]
    back = wait_for(tray_processes, 40)
    evidence("tray_closed", killed=[tray.pid for tray in trays], relaunched=[tray.pid for tray in back or []],
             protection_running=status()["protection_running"])
    assert back, "service did not relaunch the tray"


def test_killing_service_recovers_without_losing_state():
    import psutil
    before, old = status(), service_pid()
    psutil.Process(old).kill()
    started = time.monotonic()
    new = wait_for(lambda: (lambda pid: pid if pid != old else None)(_safe_pid()), 60)
    after = wait_for(lambda: _safe_status(), 30)
    evidence("service_killed", old_pid=old, new_pid=new, recovery_sec=round(time.monotonic() - started, 1),
             clock_before=before["clock"]["mode"], clock_after=after and after["clock"]["mode"])
    assert new and after and after["enrolled"] and after["device_id"] == before["device_id"]
    assert after["clock"]["mode"] in {"server", "restored"}


def _safe_pid():
    try:
        return service_pid()
    except Exception:
        return None


def _safe_status():
    try:
        current = status()
        return current if current["protection_running"] else None
    except Exception:
        return None


def test_adapters_point_at_loopback_and_direct_dns_is_blocked():
    adapters = powershell("Get-NetAdapter | ? Status -eq 'Up' | % { Get-DnsClientServerAddress -InterfaceIndex "
                          "$_.ifIndex | Select InterfaceAlias,AddressFamily,ServerAddresses } | ConvertTo-Json")
    rules = powershell("Get-NetFirewallRule -Group 'OpenGuardKids' | Select DisplayName,Action,Direction | "
                       "ConvertTo-Json")
    direct = powershell("try { Resolve-DnsName example.org -Server 8.8.8.8 -DnsOnly -QuickTimeout "
                        "-ErrorAction Stop | Out-Null; 'resolved' } catch { 'blocked: ' + $_.Exception.Message }")
    evidence("dns_adapters", adapters=adapters, firewall=rules, direct_8888=direct)
    assert "127.0.0.1" in adapters and "Block" in rules
    assert direct.startswith("blocked")


def test_blocked_domain_and_doh_endpoint_get_nxdomain():
    domain = os.getenv("OGK_ACCEPTANCE_BLOCKED_DOMAIN")
    if not domain:
        pytest.skip("set OGK_ACCEPTANCE_BLOCKED_DOMAIN to a domain in the child's block list")
    results = {}
    for name in (domain, "dns.google", "use-application-dns.net", "wikipedia.org"):
        results[name] = powershell(f"Clear-DnsClientCache; try {{ Resolve-DnsName {name} -DnsOnly -ErrorAction Stop "
                                   f"| Out-Null; 'ok' }} catch {{ $_.CategoryInfo.Reason + ': ' + $_.Exception.Message }}")
    policies = powershell(r"Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Google\Chrome','HKLM:\SOFTWARE\Policies\Microsoft\Edge'"
                          " -ErrorAction SilentlyContinue | Select DnsOverHttpsMode | ConvertTo-Json")
    evidence("dns_block", results=results, browser_policies=policies)
    assert results["wikipedia.org"] == "ok"
    for name in (domain, "dns.google", "use-application-dns.net"):
        assert results[name] != "ok", name
    assert "off" in policies


def test_renamed_blocked_executable_is_terminated_by_hash():
    if not os.getenv("OGK_ACCEPTANCE_BLOCKED_SHA256"):
        pytest.skip("set OGK_ACCEPTANCE_BLOCKED_SHA256 and block that hash in the child's policy")
    import psutil
    source = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
    renamed = Path(tempfile.gettempdir()) / "renamed-game.exe"
    shutil.copyfile(source, renamed)
    process = subprocess.Popen([str(renamed)])
    started = time.monotonic()
    gone = wait_for(lambda: not psutil.pid_exists(process.pid) or process.poll() is not None, 15, 0.2)
    evidence("renamed_exe", pid=process.pid, terminated=bool(gone), seconds=round(time.monotonic() - started, 1))
    if not gone:
        process.kill()
    assert gone
