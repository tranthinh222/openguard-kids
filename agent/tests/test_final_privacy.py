import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag

from openguard_agent import AgentState, StateStore
from service.dns.matcher import DomainMatcher
from service.runtime import TrayWatchdog


def test_state_encrypted_restart_and_legacy_upgrade(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"access_token": "secret-token", "refresh_token": "refresh-secret"}))
    store = StateStore(path)
    assert store.load().access_token == "secret-token"
    assert "secret-token" not in path.read_text()
    assert StateStore(path).load().refresh_token == "refresh-secret"
    envelope = json.loads(path.read_text())
    import base64
    data = bytearray(base64.b64decode(envelope["data"]))
    data[-1] ^= 1
    envelope["data"] = base64.b64encode(data).decode()
    path.write_text(json.dumps(envelope))
    with pytest.raises(InvalidTag):
        store.load()


def test_safety_exemptions_cannot_be_blocked(monkeypatch):
    monkeypatch.setenv("OGK_SCHOOL_DOMAINS", "school.example.test")
    matcher = DomainMatcher()
    rules = SimpleNamespace(payload={"domains": {
        "block": ["tongdai111.vn", "school.example.test"], "blocked_categories": ["unknown"]}})
    assert matcher.decide("www.tongdai111.vn", rules) == ("allow", "safety_exemption")
    assert matcher.decide("school.example.test", rules) == ("allow", "safety_exemption")
    assert matcher.decide("tongdai111.vn.evil.test", rules) == ("block", "unknown")


def test_watchdog_does_not_trust_arbitrary_polls(monkeypatch):
    now = [0]
    watchdog = TrayWatchdog(session=lambda: 1, monotonic=lambda: now[0])
    caller = SimpleNamespace(session=1, pid=123)
    monkeypatch.setattr(watchdog, "trusted", lambda _: False)
    assert not watchdog.visibility_failed()
    now[0] = 31
    watchdog.seen(caller, visible=True)
    assert watchdog.visibility_failed()
    monkeypatch.setattr(watchdog, "trusted", lambda _: True)
    watchdog.seen(caller, visible=True)
    assert not watchdog.visibility_failed()


@pytest.mark.skipif(os.name != "nt", reason="Windows named pipes")
def test_real_named_pipe_multiple_connections():
    from service.ipc.server import NamedPipeServer
    from service.ipc import IPCClient
    name = r"\\.\pipe\OpenGuardTest-" + str(uuid4())
    server = NamedPipeServer(name, lambda method, params, caller: params)
    server.start()
    try:
        client = IPCClient(name)
        for i in range(5):
            assert client.call("echo", number=i) == {"number": i}
    finally:
        server.stop()


def test_erasure_retries_ack_without_restart_or_collection(tmp_path, monkeypatch):
    import sqlite3
    import httpx
    from unittest.mock import Mock
    from openguard_agent import AgentConfig
    from service.runtime import AgentRuntime
    runtime = AgentRuntime(AgentConfig("http://test", tmp_path / "state.json"))
    runtime.controller.store.save(AgentState(device_id="old", access_token="access", refresh_token="refresh",
                                              erasure_pending=True))
    runtime.heartbeat, runtime.protection = Mock(), Mock()
    monkeypatch.setattr(runtime, "_join_workers", lambda: True)
    calls = []
    def acknowledge(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("ACK lost")
        return {"acknowledged": True}
    monkeypatch.setattr("service.erasure.check", acknowledge)
    with sqlite3.connect(runtime.database) as db:
        db.execute("INSERT INTO clock_events(local_time,server_time,drift_seconds,threshold_seconds,created_at)"
                   " VALUES('private','private',0,120,'2026-10-20')")
    runtime.supervise_once()
    assert runtime.controller.store.load().erasure_pending
    with sqlite3.connect(runtime.database) as db:
        assert db.execute("SELECT count(*) FROM clock_events").fetchone()[0] == 0
    runtime._next_erasure_check = 0
    runtime.supervise_once()
    assert runtime.controller.store.load() == AgentState()
    assert runtime.wait(0)
    runtime.protection.start.assert_not_called()


def test_policy_expires_on_trusted_elapsed_time(tmp_path):
    import httpx
    from datetime import datetime, timezone
    from openguard_agent import AgentConfig, AgentClient
    from service.clock import ClockMonitor
    config = AgentConfig("http://test", tmp_path / "state.json")
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    elapsed = [100.0]
    clock = ClockMonitor(tmp_path / "agent.db", monotonic=lambda: elapsed[0], local_now=lambda: now)
    clock.synchronize(now)
    store = StateStore(config.state_path)
    store.save(AgentState(last_heartbeat_at=now.isoformat()))
    client = AgentClient(config, store, httpx.MockTransport(lambda _: httpx.Response(200)),
                         clock_monitor=clock)
    try:
        assert not client.policy_expired()
        elapsed[0] += 7 * 86400
        assert client.policy_expired()
    finally:
        client.close()


def test_hardening_resets_children_without_stripping_their_inheritance(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows ACL structure")
    import win32security
    from service.windows import hardening
    (tmp_path / "agent.db").write_text("test")
    calls, descriptors = [], []
    monkeypatch.setattr(hardening, "_run", lambda *args: calls.append(args))
    monkeypatch.setattr(win32security, "SetNamedSecurityInfo", lambda *args: descriptors.append(args))
    hardening.harden_data_dir(tmp_path)
    assert descriptors[0][2] & win32security.PROTECTED_DACL_SECURITY_INFORMATION
    assert descriptors[0][5].GetAceCount() == 2
    assert calls == [("icacls.exe", str(tmp_path / "agent.db"), "/reset", "/T", "/Q")]


def test_expired_policy_locks_without_counting_usage(tmp_path):
    from service.screen_time.counter import ScreenTimeCounter, UsageRepository
    calls = []
    counter = ScreenTimeCounter(UsageRepository(tmp_path / "counter.db"), lambda: object(),
                                lambda _: True, lambda: True, lambda: calls.append(True) or True,
                                policy_expired=lambda: True)
    result = counter.tick()
    assert result.reason == "policy_expired" and result.should_lock
    assert calls == [True]
