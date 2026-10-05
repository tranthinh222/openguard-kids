import pytest

from service.requests import ExtraTimeClient


def test_extra_time_request_payload():
    calls = []
    client = ExtraTimeClient(lambda path, body: calls.append((path, body)) or {"status": "pending"})
    assert client.request(15)["status"] == "pending"
    assert calls == [("/api/v1/agent/requests", {"type": "extra_time", "requested_minutes": 15})]


def test_extra_time_range():
    client = ExtraTimeClient(lambda _path, _body: {})
    with pytest.raises(ValueError):
        client.request(4)
