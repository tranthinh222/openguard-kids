import threading
from datetime import datetime, timezone

import httpx

import gui_controller
from gui_controller import AgentController, ProtectionWorker
from openguard_agent import AgentClient, AgentConfig, AgentState
from service.clock import ClockMonitor
from service.screen_time.counter import ScreenTimeCounter, UsageRepository
from test_screen_time import policy


def test_clock_jump_cannot_reset_quota_or_change_schedule(tmp_path):
    mono = [0.0]
    wall = [datetime(2026, 10, 5, 12, tzinfo=timezone.utc)]
    monitor = ClockMonitor(tmp_path / "agent.db", monotonic=lambda: mono[0], local_now=lambda: wall[0])
    monitor.synchronize(wall[0])
    locks = []
    counter = ScreenTimeCounter(UsageRepository(tmp_path / "agent.db"), lambda: policy(1),
                                lambda _: True, lambda: True, lambda: locks.append(True) or True,
                                monotonic=lambda: mono[0], now=monitor.trusted_now,
                                clock_ready=lambda: monitor.ready)
    mono[0] = 30
    assert counter.tick().used_seconds == 30
    wall[0] = datetime(2040, 1, 1, tzinfo=timezone.utc)
    mono[0] = 60
    assert counter.tick().should_lock
    wall[0] = datetime(2000, 1, 1, tzinfo=timezone.utc)
    mono[0] = 61
    assert counter.tick().used_seconds == 60
    assert len(locks) == 1
    schedule = [True] * 336
    moment = monitor.trusted_now()
    schedule[moment.weekday() * 48 + moment.hour * 2 + moment.minute // 30] = False
    counter.policy_provider = lambda: policy(90, schedule)
    assert counter.tick().reason == "outside_schedule"


def test_offline_start_does_not_create_usage_day_from_untrusted_clock(tmp_path):
    monitor = ClockMonitor(tmp_path / "agent.db")
    locks = []
    mono = [0.0]
    counter = ScreenTimeCounter(UsageRepository(tmp_path / "agent.db"), lambda: policy(),
                                lambda _: True, lambda: True, lambda: locks.append(True) or True,
                                now=monitor.trusted_now, clock_ready=lambda: monitor.ready,
                                monotonic=lambda: mono[0])
    for second in (0, 1, 10, 29.99):
        mono[0] = second
        pending = counter.tick()
        assert pending.reason == "clock_sync_pending" and not pending.should_lock
        assert locks == []
    mono[0] = 30
    result = counter.tick()
    assert result.reason == "clock_unverified" and result.should_lock
    assert locks == [True]
    monitor.synchronize("2026-10-05T12:00:00Z")
    assert counter.tick().reason == "counted"


def test_successful_startup_sync_does_not_lock_or_delay_policy(tmp_path):
    mono = [0.0]
    monitor = ClockMonitor(tmp_path / "agent.db", monotonic=lambda: mono[0])
    locks = []
    counter = ScreenTimeCounter(UsageRepository(tmp_path / "agent.db"), lambda: policy(),
                                lambda _: True, lambda: True, lambda: locks.append(True) or True,
                                now=monitor.trusted_now, clock_ready=lambda: monitor.ready,
                                monotonic=lambda: mono[0])
    assert counter.tick().reason == "clock_sync_pending"
    mono[0] = 1
    monitor.synchronize("2026-10-05T12:00:00Z")
    assert counter.tick().reason == "counted"
    assert locks == []
    # A real schedule restriction applies immediately, before the 30s deadline.
    counter.policy_provider = lambda: policy(schedule=[False] * 336)
    assert counter.tick().reason == "outside_schedule"
    assert locks == [True]


def test_parent_lock_is_not_delayed_by_startup_clock_sync(tmp_path):
    locks = []
    counter = ScreenTimeCounter(UsageRepository(tmp_path / "agent.db"), lambda: policy(),
                                lambda _: True, lambda: True, lambda: locks.append(True) or True,
                                clock_ready=lambda: False, remote_locked=lambda: True)
    result = counter.tick()
    assert result.reason == "remote_lock" and result.should_lock
    assert locks == [True]


def test_gui_heartbeat_and_protection_share_clock(tmp_path, monkeypatch):
    config = AgentConfig("https://server.test", tmp_path / "state.json", policy_hmac_secret="secret")
    controller = AgentController(config)
    controller.store.save(AgentState(device_id="d", access_token="a", refresh_token="r"))
    controller.clock_monitor.local_now = lambda: datetime(2040, 1, 1, tzinfo=timezone.utc)
    clients = []
    stop = threading.Event()

    class FakeWebSocket:
        def start(self):
            pass

        def stop(self):
            pass

    def make_client(*args, **kwargs):
        client = AgentClient(*args, **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "server_time": "2026-10-05T12:00:00Z", "clock_trusted": False,
            "clock_drift_sec": 999999, "clock_drift_threshold_sec": 120,
            "policy_version": 0, "policy_update_available": False, "commands": [],
        })))
        clients.append(client)
        original = client.screen_time_counter

        def counter(on_event):
            value = original(on_event)
            def tick():
                assert value.now().astimezone(timezone.utc).year == 2026
                assert value.clock_ready()
                stop.set()
                from service.screen_time.counter import TickResult
                return TickResult(0, 0, 0, False, "no_policy")
            value.tick = tick
            return value

        client.screen_time_counter = counter
        client.websocket_worker = lambda: FakeWebSocket()
        return client

    monkeypatch.setattr(gui_controller, "AgentClient", make_client)
    controller.heartbeat()
    events = []
    ProtectionWorker(controller, events.append)._run(stop)
    assert events == []
    assert len(clients) == 2
    assert all(client.clock_monitor is controller.clock_monitor for client in clients)
    assert controller.clock_monitor.status.drifted
    assert controller.state().last_heartbeat_at == "2026-10-05T12:00:00Z"


def test_heartbeat_add_time_uses_server_day_before_ack(tmp_path):
    from openguard_agent import StateStore

    config = AgentConfig("https://server.test", tmp_path / "state.json")
    store = StateStore(config.state_path)
    store.save(AgentState(device_id="d", access_token="a", refresh_token="r"))
    monitor = ClockMonitor(tmp_path / "agent.db",
                           local_now=lambda: datetime(2040, 1, 1, tzinfo=timezone.utc))
    acks = []

    def handler(request):
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={
                "server_time": "2026-10-05T12:00:00Z", "clock_trusted": False,
                "clock_drift_sec": 999999, "clock_drift_threshold_sec": 120,
                "policy_version": 0, "policy_update_available": False,
                "commands": [{"command_id": "bonus-1", "type": "ADD_TIME", "payload": {"minutes": 15}}],
            })
        acks.append(request.url.path)
        return httpx.Response(200, json={"status": "completed"})

    client = AgentClient(config, store, httpx.MockTransport(handler), clock_monitor=monitor)
    try:
        client.heartbeat()
        assert client.usage_repository.get(monitor.trusted_now().date()).bonus_seconds == 900
        assert client.usage_repository.get_if_exists(datetime(2040, 1, 1).date()) is None
        assert acks == ["/api/v1/agent/commands/bonus-1/ack"]
    finally:
        client.close()
