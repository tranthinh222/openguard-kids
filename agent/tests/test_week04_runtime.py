"""Week 04 A1/A2/A5: one runtime behind local IPC; the tray can come and go."""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from openguard_agent import AgentClient, AgentConfig, AgentState, StateStore
from service.host import IdleReports, ServiceHost
from service.ipc import Caller, IPCClient, IPCError, ServiceUnavailableError, create_server
from service.runtime import MAX_RESTARTS, AgentRuntime, EventBuffer, TrayWatchdog, json_safe

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Unix socket transport; Windows uses the named pipe")

FAKE_HOST = SimpleNamespace(name="test", active=lambda _timeout: True, unlocked=lambda: True,
                            lock=lambda: True, processes=lambda: iter(()))


def quiet_config(tmp_path, **changes):
    return AgentConfig("http://testserver", tmp_path / "state.json", apps_enabled=False, dns_enabled=False,
                       **changes)


def test_event_buffer_cursor_skips_backlog_for_new_tray():
    buffer = EventBuffer(size=3)
    for index in range(5):
        buffer.publish({"type": "X", "n": index})
    assert buffer.since(-1) == {"seq": 5, "events": []}
    assert [event["n"] for event in buffer.since(3)["events"]] == [3, 4]
    assert json_safe({"type": "PROTECTION_ERROR", "error": RuntimeError("x"), "obj": object()}) == {
        "type": "PROTECTION_ERROR", "error": "Không đọc được dữ liệu agent trên máy này."}


def test_ipc_round_trip_reports_os_identity_and_hides_internal_errors(tmp_path):
    seen = []

    def handler(method, params, caller):
        seen.append(caller)
        if method == "boom":
            raise KeyError("secret detail")
        return {"echo": params}

    server = create_server(str(tmp_path / "s.sock"), handler)
    server.start()
    try:
        client = IPCClient(str(tmp_path / "s.sock"))
        assert client.call("echo", value=1) == {"echo": {"value": 1}}
        with pytest.raises(IPCError) as error:
            client.call("boom")
        assert error.value.code == "internal" and "secret" not in str(error.value)
        assert seen[0].pid == os.getpid() and seen[0].admin is (os.geteuid() == 0)
    finally:
        server.stop()
    with pytest.raises(ServiceUnavailableError):
        IPCClient(str(tmp_path / "s.sock")).call("echo")


def test_second_runtime_on_same_database_is_refused(tmp_path):
    first = AgentRuntime(quiet_config(tmp_path), host=FAKE_HOST, ipc_address=str(tmp_path / "a.sock"))
    first.start()
    try:
        second = AgentRuntime(quiet_config(tmp_path), host=FAKE_HOST, ipc_address=str(tmp_path / "b.sock"))
        with pytest.raises(RuntimeError, match="already running"):
            second.start()
    finally:
        first.stop()


def test_child_cannot_repair_or_pause_sync_without_admin(tmp_path):
    runtime = AgentRuntime(quiet_config(tmp_path), host=FAKE_HOST, ipc_address=str(tmp_path / "s.sock"))
    StateStore(runtime.config.state_path).save(AgentState(device_id="d", access_token="a", refresh_token="r"))
    child = Caller(pid=123, admin=False)
    with pytest.raises(PermissionError, match="quản trị viên"):
        runtime.handle("enroll", {"code": "ABCD1234"}, child)
    with pytest.raises(PermissionError):
        runtime.handle("set_sync_paused", {"paused": True}, child)
    with pytest.raises(IPCError) as error:
        runtime.handle("stop", {}, child)
    assert error.value.code == "unknown_method"
    assert runtime.handle("set_sync_paused", {"paused": True}, Caller(1, True)) == {"sync_paused": True}


def test_rate_limit_on_child_requests(tmp_path):
    now = [0.0]
    runtime = AgentRuntime(quiet_config(tmp_path), host=FAKE_HOST, monotonic=lambda: now[0])
    runtime.controller.request_extra_time = lambda minutes: {"minutes": minutes}
    assert runtime.handle("request_extra_time", {"minutes": 15}, Caller(1, False)) == {"ok": True}
    with pytest.raises(IPCError) as error:
        runtime.handle("request_extra_time", {"minutes": 15}, Caller(1, False))
    assert error.value.code == "rate_limited"
    now[0] = 11
    assert runtime.handle("request_extra_time", {"minutes": 15}, Caller(1, False))["ok"]


class FakeWorker:
    def __init__(self, running=False):
        self.running, self.starts, self._thread = running, 0, None

    def start(self):
        self.starts += 1

    def stop(self):
        pass


def test_supervisor_restarts_crashed_protection_then_exits_for_scm(tmp_path):
    now = [0.0]
    runtime = AgentRuntime(quiet_config(tmp_path), host=FAKE_HOST, monotonic=lambda: now[0])
    StateStore(runtime.config.state_path).save(AgentState(device_id="d", access_token="a", refresh_token="r"))
    runtime.protection, runtime.heartbeat = FakeWorker(), FakeWorker(running=True)
    runtime._protection_started = True
    for attempt in range(MAX_RESTARTS):
        now[0] = attempt
        runtime.supervise_once()
    assert runtime.protection.starts == MAX_RESTARTS and runtime.fatal is None
    assert [e["type"] for e in runtime.buffer.since(0)["events"]] == ["PROTECTION_RESTARTED"] * MAX_RESTARTS
    runtime.supervise_once()
    assert runtime.fatal == "protection_crash_loop" and runtime.wait(0)


def test_supervisor_restarts_heartbeat_unless_paused(tmp_path):
    runtime = AgentRuntime(quiet_config(tmp_path), host=FAKE_HOST)
    StateStore(runtime.config.state_path).save(AgentState(device_id="d", access_token="a", refresh_token="r"))
    runtime.protection, runtime.heartbeat = FakeWorker(running=True), FakeWorker()
    runtime._protection_started = True
    runtime.supervise_once()
    assert runtime.heartbeat.starts == 1
    runtime.sync_paused = True
    runtime.supervise_once()
    assert runtime.heartbeat.starts == 1


def test_service_host_counts_time_without_trusted_idle_report():
    now = [0.0]
    idle = IdleReports(monotonic=lambda: now[0])
    host = ServiceHost(idle=idle, session=lambda: None)
    assert host.active(300)  # Tray gone: stricter, never free time.
    idle.report(400)
    assert not host.active(300)
    now[0] = 16
    assert host.active(300)  # Stale report expires.
    assert host.unlocked() is False and list(host.processes()) == []  # No console session.


def test_tray_watchdog_relaunches_and_trusts_only_its_own_tray():
    now, launched = [0.0], []
    session = [1]

    def launch(sid, command, cwd, hidden):
        launched.append(sid)
        return os.getpid()

    watchdog = TrayWatchdog("tray", ".", session=lambda: session[0], launch=launch, monotonic=lambda: now[0])
    watchdog.tick()
    assert launched == [1] and watchdog.trusted(Caller(os.getpid(), False, 1))
    assert not watchdog.trusted(Caller(os.getpid() + 1, False, 1))
    watchdog.tick()
    assert launched == [1]  # Still alive in the same session.
    watchdog.pid = 2**22 + 12345  # Tray killed.
    now[0] = 5
    watchdog.tick()
    assert launched == [1]  # Relaunches are throttled.
    now[0] = 11
    watchdog.tick()
    assert launched == [1, 1]
    watchdog.pid, session[0], now[0] = 2**22 + 12345, 2, 30
    watchdog.seen(Caller(999, False, 2))  # A tray the user started is polling in session 2.
    watchdog.tick()
    assert launched == [1, 1]


def test_trusted_idle_report_only_from_watchdog_tray(tmp_path):
    host = ServiceHost(session=lambda: None)
    tray = SimpleNamespace(trusted=lambda caller: caller.pid == 42, tick=lambda: None, seen=lambda caller: None)
    runtime = AgentRuntime(quiet_config(tmp_path), host=host, tray=tray)
    assert runtime.handle("report_idle", {"idle_seconds": 999}, Caller(7, False)) == {"accepted": False}
    assert host.active(300)
    assert runtime.handle("report_idle", {"idle_seconds": 999}, Caller(42, False)) == {"accepted": True}
    assert not host.active(300)


@pytest.fixture
def api(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
    from app.api.deps import get_db
    from app.core.config import settings
    from app.main import app
    from app.models.base import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: (yield session)
    server = TestClient(app)
    credentials = {"email": "week04-runtime@example.com", "password": "StrongPass123!"}
    assert server.post("/api/v1/auth/register", json=credentials).status_code == 201
    token = server.post("/api/v1/auth/token", json=credentials).json()["access_token"]
    parent = {"Authorization": "Bearer " + token}
    child = server.post("/api/v1/children", headers=parent, json={"display_name": "Demo"}).json()["id"]
    mode = ["online"]

    def handler(request):
        if mode[0] == "offline":
            raise httpx.ConnectError("Offline")
        response = server.request(request.method, request.url.raw_path.decode(), content=request.content,
                                  headers=dict(request.headers))
        return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))

    yield SimpleNamespace(server=server, parent=parent, child=child, mode=mode, settings=settings,
                          transport=httpx.MockTransport(handler))
    app.dependency_overrides = previous
    session.close()


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached")


def test_tray_closed_and_service_restarted_keep_protection_and_state(tmp_path, api, monkeypatch):
    monkeypatch.setattr(AgentClient, "websocket_worker",
                        lambda self: SimpleNamespace(start=lambda: None, stop=lambda: None))
    code = api.server.post(f"/api/v1/children/{api.child}/enrollment", headers=api.parent).json()["code"]
    config = quiet_config(tmp_path, policy_hmac_secret=api.settings.policy_hmac_secret, usage_tick_sec=0.1)
    address = str(tmp_path / "s.sock")

    def boot():
        runtime = AgentRuntime(config, host=FAKE_HOST, ipc_address=address, transport=api.transport)
        runtime.start()
        return runtime

    runtime = boot()
    try:
        tray = IPCClient(address)
        assert tray.call("status", tray=True)["enrolled"] is False
        assert tray.call("enroll", code=code, server_url="http://testserver")["ok"] is True
        status = wait_for(lambda: (lambda s: s if s["clock"]["ready"] and s["tick"] else None)(tray.call("status")))
        assert status["protection_running"] and status["connection"] == "ok" and status["policy"]["version"] >= 1
        tray = None  # "Close the tray": the service does not notice or care.
        assert IPCClient(address).call("status")["protection_running"]
        api.mode[0] = "offline"  # Server down: protection keeps the cached policy.
        reply = IPCClient(address).call("heartbeat_now")
        assert reply["ok"] is False and reply["connection"] == "offline"
        assert IPCClient(address).call("status")["protection_running"]
    finally:
        runtime.stop()
    # Service killed and restarted by SCM while offline: same enrollment, restored clock.
    runtime = boot()
    try:
        status = IPCClient(address).call("status")
        assert status["enrolled"] and status["clock"]["mode"] in {"restored", "provisional"}
        assert status["server_url"] == "http://testserver"
        wait_for(lambda: IPCClient(address).call("status")["tick"])
    finally:
        runtime.stop()
