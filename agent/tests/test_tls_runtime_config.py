import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gui_controller import ProtectionWorker
from openguard_agent import AgentConfig, AgentState
from service.runtime import AgentRuntime


@pytest.mark.parametrize("explicit", [True, False])
def test_runtime_url_precedence_preserves_enrollment(tmp_path, monkeypatch, explicit):
    config = AgentConfig("https://localhost:8000", tmp_path / "state.json",
                         server_url_explicit=explicit, apps_enabled=False, dns_enabled=False)
    runtime = AgentRuntime(config)
    runtime.controller.store.save(AgentState(server_url="http://localhost:8000",
                                             refresh_token="existing-refresh"))
    monkeypatch.setattr("service.runtime.create_server", lambda *args: Mock())
    monkeypatch.setattr("service.runtime.threading.Thread", Mock())
    monkeypatch.setattr(runtime, "_start_workers", Mock())
    runtime.start()
    try:
        assert runtime.controller.config.server_url == (
            "https://localhost:8000" if explicit else "http://localhost:8000")
        assert runtime.controller.store.load().refresh_token == "existing-refresh"
    finally:
        runtime.lease.close()


def test_tls_configuration_error_waits_without_worker_crash(monkeypatch):
    error = ValueError("Certificate pinning requires HTTPS and certificate verification")
    monkeypatch.setattr("gui_controller.AgentClient", Mock(side_effect=error))
    stop = threading.Event()
    events = []

    def report(event):
        events.append(event)
        stop.set()

    controller = SimpleNamespace(config=None, store=None, clock_monitor=None, host=None, transport=None)
    ProtectionWorker(controller, report)._run(stop)
    assert events == [{"type": "PROTECTION_ERROR", "error": error}]
