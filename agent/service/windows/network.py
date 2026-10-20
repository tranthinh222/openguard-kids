"""Point every active adapter at the loopback DNS proxy and close the common DNS bypasses.

The guard keeps the adapters' original DNS configuration in SQLite before the first change,
so stopping/uninstalling (or the fail-open safety mode) restores exactly what was there:
DHCP-provided servers stay DHCP, static servers are written back.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import sqlite3
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger("openguard-agent.network")

LOOPBACK_DNS = ("127.0.0.1", "::1")
FIREWALL_GROUP = "OpenGuardKids"
CREATE_NO_WINDOW = 0x08000000
# Browser policies that turn off built-in DNS-over-HTTPS so queries reach the system resolver.
BROWSER_POLICIES = (
    (r"SOFTWARE\Policies\Google\Chrome", "DnsOverHttpsMode", "off"),
    (r"SOFTWARE\Policies\Microsoft\Edge", "DnsOverHttpsMode", "off"),
    (r"SOFTWARE\Policies\BraveSoftware\Brave", "DnsOverHttpsMode", "off"),
    (r"SOFTWARE\Policies\Mozilla\Firefox\DNSOverHTTPS", "Enabled", 0),
    (r"SOFTWARE\Policies\Mozilla\Firefox\DNSOverHTTPS", "Locked", 1),
)


@dataclass(frozen=True)
class Adapter:
    guid: str
    index: int
    alias: str


@dataclass(frozen=True)
class DnsConfig:
    """Static servers per family; None means the family is DHCP/automatic."""
    v4: tuple[str, ...] | None
    v6: tuple[str, ...] | None


def complement_ranges(address: str) -> list[str]:
    """Every address of the family except `address`, in Windows Firewall range syntax."""
    ip = ipaddress.ip_address(address)
    first, last = (ipaddress.IPv4Address(0), ipaddress.IPv4Address(2**32 - 1)) if ip.version == 4 else \
        (ipaddress.IPv6Address(0), ipaddress.IPv6Address(2**128 - 1))
    ranges = []
    if ip > first:
        ranges.append(f"{first}-{ip - 1}")
    if ip < last:
        ranges.append(f"{ip + 1}-{last}")
    return ranges


def _ps_list(values) -> str:
    return "@(" + ",".join("'" + str(value).replace("'", "''") + "'" for value in values) + ")"


class PowerShellBackend:
    """Windows implementation; every value interpolated into a script is validated first."""

    def run(self, script: str) -> str:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
             "$ErrorActionPreference='Stop'; " + script],
            capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or f"PowerShell exited with {completed.returncode}")
        return completed.stdout.strip()

    def adapters(self) -> list[Adapter]:
        raw = self.run("Get-NetAdapter | Where-Object Status -eq 'Up' | "
                       "Select-Object ifIndex,InterfaceGuid,Name | ConvertTo-Json -Compress")
        items = json.loads(raw) if raw else []
        items = [items] if isinstance(items, dict) else items
        return [Adapter(str(item["InterfaceGuid"]).lower(), int(item["ifIndex"]), str(item["Name"])) for item in items]

    def current(self, adapter: Adapter) -> tuple[tuple[str, ...], tuple[str, ...]]:
        raw = self.run(f"Get-DnsClientServerAddress -InterfaceIndex {int(adapter.index)} | "
                       "Select-Object AddressFamily,ServerAddresses | ConvertTo-Json -Compress")
        items = json.loads(raw) if raw else []
        items = [items] if isinstance(items, dict) else items
        servers = {2: (), 23: ()}
        for item in items:
            servers[int(item["AddressFamily"])] = tuple(item.get("ServerAddresses") or ())
        return servers[2], servers[23]

    def static(self, adapter: Adapter) -> DnsConfig:
        import winreg
        found = []
        for stack in ("Tcpip", "Tcpip6"):
            key = rf"SYSTEM\CurrentControlSet\Services\{stack}\Parameters\Interfaces\{adapter.guid}"
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                    value = str(winreg.QueryValueEx(handle, "NameServer")[0])
            except OSError:
                value = ""
            servers = tuple(item for item in value.replace(",", " ").split() if item)
            found.append(servers or None)
        return DnsConfig(*found)

    def set_static(self, adapter: Adapter, servers) -> None:
        servers = [str(ipaddress.ip_address(item)) for item in servers]
        self.run(f"Set-DnsClientServerAddress -InterfaceIndex {int(adapter.index)} -ServerAddresses {_ps_list(servers)}")

    def reset(self, adapter: Adapter) -> None:
        self.run(f"Set-DnsClientServerAddress -InterfaceIndex {int(adapter.index)} -ResetServerAddresses")

    def flush_cache(self) -> None:
        self.run("Clear-DnsClientCache")

    def firewall_active(self) -> bool:
        count = self.run(f"@(Get-NetFirewallRule -Group '{FIREWALL_GROUP}' -ErrorAction SilentlyContinue).Count")
        return int(count or 0) > 0

    def apply_firewall(self, upstream: str) -> None:
        upstream = str(ipaddress.ip_address(upstream))
        other = "::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff" if ":" not in upstream else "0.0.0.0-255.255.255.255"
        rules = []
        for protocol in ("UDP", "TCP"):
            # Plain DNS anywhere but the agent's own upstream, and DNS-over-TLS everywhere.
            rules.append((f"DNS {protocol}", protocol, "53", complement_ranges(upstream) + [other]))
            rules.append((f"DoT {protocol}", protocol, "853", ["Any"]))
        script = [f"Remove-NetFirewallRule -Group '{FIREWALL_GROUP}' -ErrorAction SilentlyContinue"]
        for name, protocol, port, addresses in rules:
            remote = "Any" if addresses == ["Any"] else _ps_list(addresses)
            script.append(f"New-NetFirewallRule -DisplayName 'OpenGuard Kids block {name}' -Group '{FIREWALL_GROUP}' "
                          f"-Direction Outbound -Action Block -Protocol {protocol} -RemotePort {port} "
                          f"-RemoteAddress {remote} -Profile Any | Out-Null")
        self.run("; ".join(script))

    def remove_firewall(self) -> None:
        # Filtering an enumeration yields an empty, successful pipeline when the
        # group is already gone. Do not hide access/provider/removal errors.
        self.run("Get-NetFirewallRule -ErrorAction Stop | "
                 f"Where-Object {{ $_.Group -eq '{FIREWALL_GROUP}' }} | "
                 "Remove-NetFirewallRule -ErrorAction Stop")

    def read_policy(self, path: str, name: str):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as handle:
                return winreg.QueryValueEx(handle, name)[0]
        except OSError:
            return None

    def write_policy(self, path: str, name: str, value) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as handle:
            if value is None:
                try:
                    winreg.DeleteValue(handle, name)
                except FileNotFoundError:
                    pass
            else:
                kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
                winreg.SetValueEx(handle, name, 0, kind, value)


class NetworkGuard:
    """States: idle → protecting ⇄ suspended (fail-open) → idle after restore()."""

    def __init__(self, database: Path, backend=None, upstream: str = "1.1.1.1", firewall: bool = True,
                 browser_policy: bool = True):
        self.database, self.backend = database, backend or PowerShellBackend()
        self.upstream, self.firewall, self.browser_policy = upstream, firewall, browser_policy
        self.state, self.last_error = "idle", None
        self._mutex = threading.Lock()
        with sqlite3.connect(self.database, timeout=10) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS dns_adapter_backup (
                guid TEXT PRIMARY KEY, alias TEXT NOT NULL, config TEXT NOT NULL, saved_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS browser_policy_backup (
                path TEXT NOT NULL, name TEXT NOT NULL, previous TEXT NOT NULL, PRIMARY KEY(path, name))""")

    def status(self) -> dict:
        return {"state": self.state, "error": self.last_error}

    def protect(self) -> list[str]:
        """Idempotent: (re)point adapters at loopback; returns aliases that had to be changed."""
        with self._mutex:
            try:
                changed = []
                if self.browser_policy:
                    self._apply_browser_policies()
                for adapter in self.backend.adapters():
                    if self._is_ours(self.backend.current(adapter)):
                        continue
                    self._backup(adapter)
                    self.backend.set_static(adapter, LOOPBACK_DNS)
                    changed.append(adapter.alias)
                if self.firewall and not self.backend.firewall_active():
                    self.backend.apply_firewall(self.upstream)
                if changed:
                    self.backend.flush_cache()
                    LOGGER.warning("DNS of %s pointed at the OpenGuard proxy", ", ".join(changed))
                self.state, self.last_error = "protecting", None
                return changed
            except Exception as exc:
                self.state, self.last_error = "error", str(exc)
                LOGGER.error("Network protection failed: %s", exc)
                raise

    def suspend(self) -> None:
        """Fail-open: the proxy is down, so give the adapters their own DNS back for now."""
        with self._mutex:
            self._restore_adapters()
            if self.firewall:
                self.backend.remove_firewall()
            self.state = "suspended"

    def restore(self) -> None:
        """Service stop/uninstall: undo every change, including browser policies."""
        with self._mutex:
            self._restore_adapters()
            if self.firewall:
                self.backend.remove_firewall()
            self._restore_browser_policies()
            self.state = "idle"

    @staticmethod
    def _is_ours(current) -> bool:
        v4, v6 = current
        return tuple(v4) == (LOOPBACK_DNS[0],) and tuple(v6) in {(LOOPBACK_DNS[1],), ()}

    def _backup(self, adapter: Adapter) -> None:
        config = self.backend.static(adapter)
        # Never record our own loopback values as "original" (e.g. after a crash mid-change).
        if config.v4 and LOOPBACK_DNS[0] in config.v4:
            config = DnsConfig(None, config.v6)
        if config.v6 and LOOPBACK_DNS[1] in config.v6:
            config = DnsConfig(config.v4, None)
        with sqlite3.connect(self.database, timeout=10) as db:
            db.execute("INSERT OR IGNORE INTO dns_adapter_backup VALUES (?, ?, ?, ?)",
                       (adapter.guid, adapter.alias, json.dumps({"v4": config.v4, "v6": config.v6}),
                        datetime.now(timezone.utc).isoformat()))

    def _restore_adapters(self) -> None:
        live = {adapter.guid: adapter for adapter in self.backend.adapters()}
        with sqlite3.connect(self.database, timeout=10) as db:
            rows = db.execute("SELECT guid, config FROM dns_adapter_backup").fetchall()
        for guid, raw in rows:
            adapter = live.get(guid)
            if adapter is None:
                continue  # Disconnected adapter: keep the backup until it comes back.
            config = json.loads(raw)
            self.backend.reset(adapter)
            static = [*(config["v4"] or ()), *(config["v6"] or ())]
            if static:
                self.backend.set_static(adapter, static)
            with sqlite3.connect(self.database, timeout=10) as db:
                db.execute("DELETE FROM dns_adapter_backup WHERE guid=?", (guid,))
        if rows:
            self.backend.flush_cache()

    def _apply_browser_policies(self) -> None:
        with sqlite3.connect(self.database, timeout=10) as db:
            for path, name, value in BROWSER_POLICIES:
                current = self.backend.read_policy(path, name)
                if current == value:
                    continue
                db.execute("INSERT OR IGNORE INTO browser_policy_backup VALUES (?, ?, ?)",
                           (path, name, json.dumps(current)))
                self.backend.write_policy(path, name, value)

    def _restore_browser_policies(self) -> None:
        with sqlite3.connect(self.database, timeout=10) as db:
            for path, name, previous in db.execute("SELECT path, name, previous FROM browser_policy_backup").fetchall():
                self.backend.write_policy(path, name, json.loads(previous))
            db.execute("DELETE FROM browser_policy_backup")


def guard_supported() -> bool:
    return os.name == "nt"
