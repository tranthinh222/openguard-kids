import json
from pathlib import Path

import httpx

from openguard_agent import AgentClient, AgentConfig, AgentState, StateStore


def make_client(tmp_path: Path, handler):
    config = AgentConfig("https://server.test", tmp_path / "state.json")
    store = StateStore(config.state_path)
    return AgentClient(config, store, httpx.MockTransport(handler)), store


def test_enroll_saves_credentials(tmp_path):
    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/api/v1/agent/enroll"
        assert payload["code"] == "ABCD1234"
        assert len(payload["fingerprint"]) == 64
        return httpx.Response(201, json={
            "device_id": "device-1",
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "access_token_expires_in": 900,
        })

    client, store = make_client(tmp_path, handler)
    try:
        client.enroll("abcd1234")
    finally:
        client.close()
    assert store.load().device_id == "device-1"
    assert store.load().refresh_token == "refresh-1"


def test_heartbeat_refreshes_expired_token(tmp_path):
    heartbeat_count = 0

    def handler(request):
        nonlocal heartbeat_count
        if request.url.path.endswith("/heartbeat"):
            heartbeat_count += 1
            if request.headers["Authorization"] == "Bearer expired":
                return httpx.Response(401)
            payload = json.loads(request.content)
            assert payload["policy_version"] == 2
            assert payload["quota_used_sec"] == 30
            return httpx.Response(200, json={
                "server_time": "2026-09-27T10:00:00Z",
                "policy_version": 3,
                "policy_update_available": True,
                "commands": [],
            })
        assert request.url.path.endswith("/token/refresh")
        assert json.loads(request.content) == {"refresh_token": "refresh"}
        return httpx.Response(200, json={"access_token": "fresh", "expires_in": 900})

    client, store = make_client(tmp_path, handler)
    store.save(AgentState(
        device_id="device-1",
        access_token="expired",
        refresh_token="refresh",
        policy_version=2,
        quota_used_sec=30,
    ))
    try:
        response = client.heartbeat()
    finally:
        client.close()
    assert heartbeat_count == 2
    assert response["policy_version"] == 3
    assert store.load().access_token == "fresh"
    assert store.load().last_heartbeat_at is not None


def test_state_file_is_private(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save(AgentState(device_id="device-1"))
    assert store.path.stat().st_mode & 0o777 == 0o600

