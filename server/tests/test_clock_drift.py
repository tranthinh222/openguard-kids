from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.device import Device
from test_week02 import parent_headers, enrolled_device


@pytest.mark.parametrize("offset,trusted", [(0, True), (120, True), (-120, True),
                                           (121, False), (-121, False), (43200, False)])
def test_heartbeat_classifies_drift_and_recovers(client, db_session, monkeypatch, offset, trusted):
    headers = parent_headers(client)
    _, device = enrolled_device(client, headers)
    auth = {"Authorization": f"Bearer {device['access_token']}"}
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    monkeypatch.setattr("app.services.device_service.utc_now", lambda: now.replace(tzinfo=None))
    monkeypatch.setattr(settings, "agent_clock_drift_threshold_sec", 120)
    body = {"policy_version": 1, "agent_version": "test",
            "agent_wall_clock": (now + timedelta(seconds=offset)).isoformat()}
    response = client.post("/api/v1/agent/heartbeat", headers=auth, json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["clock_trusted"] is trusted
    assert data["clock_drift_sec"] == offset
    assert data["clock_drift_threshold_sec"] == 120
    assert datetime.fromisoformat(data["server_time"]) == now
    stored = db_session.get(Device, device["device_id"])
    assert stored.clock_drift_sec == offset
    assert stored.last_seen_at == now.replace(tzinfo=None)
    body["agent_wall_clock"] = now.isoformat()
    assert client.post("/api/v1/agent/heartbeat", headers=auth, json=body).json()["clock_trusted"] is True
    del body["agent_wall_clock"]
    unknown = client.post("/api/v1/agent/heartbeat", headers=auth, json=body).json()
    assert unknown["clock_trusted"] is False
    assert unknown["clock_drift_sec"] is None


def test_custom_threshold_and_business_request_timestamp(client, monkeypatch):
    headers = parent_headers(client)
    _, device = enrolled_device(client, headers)
    auth = {"Authorization": f"Bearer {device['access_token']}"}
    monkeypatch.setattr(settings, "agent_clock_drift_threshold_sec", 30)
    now = datetime.now(timezone.utc)
    heartbeat = client.post("/api/v1/agent/heartbeat", headers=auth, json={
        "policy_version": 1, "agent_version": "test",
        "agent_wall_clock": (now + timedelta(days=5000)).isoformat(),
    })
    assert heartbeat.status_code == 200
    assert heartbeat.json()["clock_trusted"] is False
    assert heartbeat.json()["clock_drift_threshold_sec"] == 30
    request = client.post("/api/v1/agent/requests", headers=auth,
                          json={"type": "extra_time", "requested_minutes": 15})
    assert request.status_code == 200
    created = datetime.fromisoformat(request.json()["created_at"]).replace(tzinfo=timezone.utc)
    assert now <= created <= datetime.now(timezone.utc)
    assert client.get("/api/v1/agent/policy", headers=auth).status_code == 200
