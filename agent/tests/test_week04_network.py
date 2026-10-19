"""Week 04 A6: DNS adapter auto-config, bypass closing, fail-safe; all OS calls faked."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import dns.message
import dns.query
import dns.rcode

from openguard_agent import AgentConfig
from service.dns.matcher import DomainMatcher
from service.dns.proxy import DOH_CANARY, HEALTH_NAME, DNSProcessor, DNSProxy
from service.events import EventQueue
from service.runtime import AgentRuntime
from service.windows.network import BROWSER_POLICIES, Adapter, DnsConfig, NetworkGuard, complement_ranges
from test_week03_agent import FakeResolver

NOW = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)


class FakeBackend:
    def __init__(self):
        self.adapters_list = [Adapter("{wifi}", 12, "Wi-Fi"), Adapter("{eth}", 7, "Ethernet")]
        self.servers = {"{wifi}": (("192.168.1.1",), ("fe80::1",)), "{eth}": (("8.8.8.8",), ())}
        self.statics = {"{wifi}": DnsConfig(None, None), "{eth}": DnsConfig(("8.8.8.8",), None)}
        self.firewall, self.policies, self.calls = False, {}, []

    def adapters(self):
        return list(self.adapters_list)

    def current(self, adapter):
        return self.servers[adapter.guid]

    def static(self, adapter):
        return self.statics[adapter.guid]

    def set_static(self, adapter, servers):
        self.calls.append(("set", adapter.alias, tuple(servers)))
        v4 = tuple(item for item in servers if ":" not in item)
        v6 = tuple(item for item in servers if ":" in item)
        self.servers[adapter.guid] = (v4 or self.servers[adapter.guid][0], v6 or self.servers[adapter.guid][1])
        self.statics[adapter.guid] = DnsConfig(v4 or None, v6 or None)

    def reset(self, adapter):
        self.calls.append(("reset", adapter.alias))
        self.servers[adapter.guid] = (("192.168.1.1",), ())
        self.statics[adapter.guid] = DnsConfig(None, None)

    def flush_cache(self):
        self.calls.append(("flush",))

    def firewall_active(self):
        return self.firewall

    def apply_firewall(self, upstream):
        self.firewall = upstream

    def remove_firewall(self):
        self.firewall = False

    def read_policy(self, path, name):
        return self.policies.get((path, name))

    def write_policy(self, path, name, value):
        if value is None:
            self.policies.pop((path, name), None)
        else:
            self.policies[(path, name)] = value


def test_protect_backs_up_once_and_restore_returns_dhcp_and_static(tmp_path):
    backend = FakeBackend()
    backend.policies[(BROWSER_POLICIES[0][0], BROWSER_POLICIES[0][1])] = "automatic"
    guard = NetworkGuard(tmp_path / "a.db", backend)
    assert guard.protect() == ["Wi-Fi", "Ethernet"]
    assert all(servers == (("127.0.0.1",), ("::1",)) for servers in backend.servers.values())
    assert backend.firewall == "1.1.1.1" and guard.state == "protecting"
    assert backend.policies[(r"SOFTWARE\Policies\Mozilla\Firefox\DNSOverHTTPS", "Enabled")] == 0
    assert guard.protect() == []  # Idempotent: nothing to change, backup untouched.

    guard.restore()
    assert backend.statics["{wifi}"] == DnsConfig(None, None)  # DHCP stays DHCP.
    assert backend.statics["{eth}"] == DnsConfig(("8.8.8.8",), None)
    assert backend.firewall is False and guard.state == "idle"
    assert backend.policies == {(BROWSER_POLICIES[0][0], BROWSER_POLICIES[0][1]): "automatic"}


def test_adapter_changed_later_is_reapplied_and_new_adapter_covered(tmp_path):
    backend = FakeBackend()
    guard = NetworkGuard(tmp_path / "a.db", backend)
    guard.protect()
    backend.servers["{wifi}"] = (("9.9.9.9",), ())  # e.g. an admin tool or VPN client rewrote it
    backend.adapters_list.append(Adapter("{vpn}", 30, "VPN"))
    backend.servers["{vpn}"], backend.statics["{vpn}"] = (("10.8.0.1",), ()), DnsConfig(("10.8.0.1",), None)
    assert sorted(guard.protect()) == ["VPN", "Wi-Fi"]
    guard.restore()
    # Wi-Fi's backup is still the first (true original) configuration, not 9.9.9.9.
    assert backend.statics["{wifi}"] == DnsConfig(None, None)
    assert backend.statics["{vpn}"] == DnsConfig(("10.8.0.1",), None)


def test_crash_left_loopback_is_not_recorded_as_original(tmp_path):
    backend = FakeBackend()
    backend.servers["{eth}"] = (("127.0.0.1",), ("::1", "fe80::5"))
    backend.statics["{eth}"] = DnsConfig(("127.0.0.1",), ("::1",))
    guard = NetworkGuard(tmp_path / "a.db", backend)
    guard.protect()
    guard.restore()
    assert backend.statics["{eth}"] == DnsConfig(None, None)


def test_suspend_is_fail_open_then_protect_resumes(tmp_path):
    backend = FakeBackend()
    guard = NetworkGuard(tmp_path / "a.db", backend)
    guard.protect()
    guard.suspend()
    assert backend.servers["{eth}"][0] == ("8.8.8.8",) and backend.firewall is False and guard.state == "suspended"
    guard.protect()
    assert backend.servers["{eth}"][0] == ("127.0.0.1",) and guard.state == "protecting"


def test_runtime_dns_health_drives_guard(tmp_path):
    config = AgentConfig("http://testserver", tmp_path / "state.json", apps_enabled=False)
    calls = []
    guard = SimpleNamespace(state="idle", status=lambda: {}, protect=lambda: calls.append("protect") or [],
                            suspend=lambda: calls.append("suspend"), restore=lambda: calls.append("restore"))
    runtime = AgentRuntime(config, network_guard=guard)
    runtime._guard_tick()
    assert calls == []  # Never point adapters at a proxy that has not answered yet.
    runtime._publish({"type": "DNS_HEALTH", "healthy": True})
    runtime._guard_tick()
    guard.state = "protecting"
    runtime._publish({"type": "DNS_HEALTH", "healthy": False})
    runtime._guard_tick()
    assert calls == ["protect", "suspend"]
    assert runtime.buffer.since(0)["events"][-1]["type"] == "DNS_FAILSAFE"


def test_closed_failure_mode_keeps_dns_blocked(tmp_path):
    config = AgentConfig("http://testserver", tmp_path / "state.json", dns_failure_mode="closed")
    calls = []
    guard = SimpleNamespace(state="protecting", status=lambda: {}, protect=lambda: [],
                            suspend=lambda: calls.append("suspend"), restore=lambda: None)
    runtime = AgentRuntime(config, network_guard=guard)
    runtime._publish({"type": "DNS_HEALTH", "healthy": False})
    runtime._guard_tick()
    assert calls == []


def test_autoconfig_only_for_service_on_port_53():
    base = AgentConfig("http://x", None)
    assert base.dns_autoconfig_enabled(service=True) and not base.dns_autoconfig_enabled(service=False)
    assert not AgentConfig("http://x", None, dns_port=15353, dns_autoconfig="true").dns_autoconfig_enabled(True)
    assert AgentConfig("http://x", None, dns_autoconfig="true").dns_autoconfig_enabled(False)
    assert not AgentConfig("http://x", None, dns_autoconfig="false").dns_autoconfig_enabled(True)


def test_firewall_ranges_exclude_only_the_upstream():
    assert complement_ranges("1.1.1.1") == ["0.0.0.0-1.1.1.0", "1.1.1.2-255.255.255.255"]
    assert complement_ranges("0.0.0.0") == ["0.0.0.1-255.255.255.255"]
    assert complement_ranges("2606:4700:4700::1111")[0].startswith("::-2606:4700:4700::1110")


def processor(tmp_path):
    queue, resolver, notices = EventQueue(tmp_path / "a.db"), FakeResolver(), []
    policy = SimpleNamespace(policy_id=str(uuid4()), version=1, payload={"domains": dict(allow=["dns.google"])})
    return DNSProcessor(lambda: policy, DomainMatcher(), resolver, queue.emit, notices.append, lambda: NOW), \
        queue, resolver, notices


def test_health_name_canary_and_doh_endpoints(tmp_path):
    proxy, queue, resolver, notices = processor(tmp_path)
    ask = lambda host: dns.message.from_wire(proxy.handle(dns.message.make_query(host, "A").to_wire()))
    assert ask(HEALTH_NAME).rcode() == dns.rcode.NOERROR
    assert ask(DOH_CANARY).rcode() == dns.rcode.NXDOMAIN
    assert queue.pending() == [] and resolver.queries == []  # Neither is child activity.
    # DoH endpoints are blocked even when a parent allow-list entry matches them.
    assert ask("dns.google").rcode() == dns.rcode.NXDOMAIN
    assert ask("mozilla.cloudflare-dns.com").rcode() == dns.rcode.NXDOMAIN
    assert [event["type"] for event in queue.pending()] == ["blocked_domain", "blocked_domain"]
    assert notices[0]["reason"] == "doh_endpoint"
    assert ask("example.org").rcode() == dns.rcode.NOERROR


def test_proxy_listens_on_ipv6_loopback_when_available(tmp_path):
    handler, *_ = processor(tmp_path)
    proxy = DNSProxy(handler, port=0)
    proxy.start()
    try:
        query = dns.message.make_query(HEALTH_NAME, "A")
        assert dns.query.udp(query, "127.0.0.1", port=proxy.port, timeout=2).rcode() == dns.rcode.NOERROR
        if proxy.ipv6_bound:
            assert dns.query.udp(query, "::1", port=proxy.port, timeout=2).rcode() == dns.rcode.NOERROR
            assert dns.query.tcp(query, "::1", port=proxy.port, timeout=2).rcode() == dns.rcode.NOERROR
    finally:
        proxy.stop()
    assert proxy.ipv6_bound is False and proxy.servers == []


def test_content_runtime_rebinds_dead_proxy(tmp_path, monkeypatch):
    from service import content_runtime as module
    notices, probes = [], iter([True, False, False, True])
    monkeypatch.setattr(module, "probe_dns", lambda port: next(probes))
    monkeypatch.setattr(module, "DNS_PROBE_SEC", 0)
    client = SimpleNamespace(config=SimpleNamespace(dns_port=0, request_timeout_sec=1))
    runtime = module.ContentRuntime(client, notices.append)
    handler, *_ = processor(tmp_path)
    for _ in range(4):
        runtime._dns_tick(handler)
    runtime._stop_proxy()
    kinds = [(n["type"], n.get("healthy")) for n in notices]
    assert kinds == [("DNS_STARTED", None), ("DNS_HEALTH", True), ("DNS_HEALTH", False),
                     ("DNS_STARTED", None), ("DNS_HEALTH", True)]
