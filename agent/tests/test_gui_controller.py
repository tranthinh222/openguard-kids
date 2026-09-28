from datetime import datetime
from pathlib import Path

import httpx
import pytest

from gui_controller import (
    AgentController,
    HeartbeatWorker,
    describe_error,
    format_sync_time,
    normalize_enrollment_code,
    normalize_server_url,
)
from openguard_agent import AgentConfig


def test_normalize_enrollment_code():
    assert normalize_enrollment_code(" abcd 1234 ") == "ABCD1234"


@pytest.mark.parametrize("code", ["short", "ABCD-123", "ABCDEFGHI"])
def test_reject_invalid_enrollment_code(code):
    with pytest.raises(ValueError, match="8"):
        normalize_enrollment_code(code)


def test_controller_updates_valid_server_url(tmp_path: Path):
    controller = AgentController(AgentConfig("http://old.test", tmp_path / "state.json"))
    controller.set_server_url(" https://server.test/ ")
    assert controller.config.server_url == "https://server.test"


@pytest.mark.parametrize("url", ["", "server.test", "ftp://server.test"])
def test_reject_invalid_server_url(url):
    with pytest.raises(ValueError, match="http"):
        normalize_server_url(url)


def _status_error(status: int, message: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://server.test/api/v1/agent/enroll")
    response = httpx.Response(status, json={"code": f"HTTP_{status}", "message": message}, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_describe_expired_code():
    assert "hết hạn" in describe_error(_status_error(400, "Enrollment code expired"))


def test_describe_network_error_separately_from_invalid_code():
    network = describe_error(httpx.ConnectError("refused"))
    invalid = describe_error(_status_error(400, "Invalid enrollment code"))
    assert "Internet" in network
    assert "Mã không đúng" in invalid


def test_describe_error_hides_technical_details():
    message = describe_error(_status_error(500, "Internal Server Error"))
    assert "HTTPStatusError" not in message and "sự cố" in message


def test_format_sync_time_today_and_other_day():
    now = datetime(2026, 9, 28, 15, 0).astimezone()
    assert format_sync_time(now.replace(hour=14, minute=30).isoformat(), now) == "14:30"
    assert format_sync_time(now.replace(day=27, hour=9, minute=5).isoformat(), now) == "09:05, 27/09/2026"
    assert format_sync_time(None, now) == "chưa đồng bộ"


def test_heartbeat_worker_restarts_while_previous_run_is_finishing():
    import threading

    release = threading.Event()
    calls = []

    class SlowController:
        config = AgentConfig("http://server.test", Path("unused"), heartbeat_interval_sec=3600)

        def heartbeat(self):
            calls.append(threading.current_thread())
            release.wait(2)
            return {"policy_version": 1}

    results = []
    worker = HeartbeatWorker(SlowController(), lambda result, error: results.append(result))
    worker.start()
    first = worker._thread
    worker.stop()
    assert not worker.running
    worker.start()
    second = worker._thread
    assert worker.running and second is not first
    worker.stop()
    release.set()
    first.join(2)
    second.join(2)
    assert results == []  # stopped runs never report stale results to the GUI
