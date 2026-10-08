import asyncio
from unittest.mock import AsyncMock

from app.models.device import Device
from app.core.security import utc_now
from app.services import policy_service
from test_week02 import parent_headers, enrolled_device


def test_policy_push_reaches_all_connected_devices_with_signed_saved_policy(client):
    parent = parent_headers(client)
    child, first = enrolled_device(client, parent)
    code = client.post(f"/api/v1/children/{child}/enrollment", headers=parent).json()["code"]
    second = client.post("/api/v1/agent/enroll", json={
        "code": code, "device_name": "second", "fingerprint": "second-device",
    }).json()
    auth = {"Authorization": f"Bearer {first['access_token']}"}
    auth2 = {"Authorization": f"Bearer {second['access_token']}"}
    with client.websocket_connect("/api/v1/agent/ws", headers=auth) as ws1:
        with client.websocket_connect("/api/v1/agent/ws", headers=auth2) as ws2:
            updated = client.put(f"/api/v1/children/{child}/policy", headers=parent,
                                 json={"payload": {"screen_time": {"weekday_minutes": 42}}})
            assert updated.status_code == 200
            expected = {"type": "POLICY_UPDATED", "payload": updated.json()}
            assert ws1.receive_json() == expected
            assert ws2.receive_json() == expected
            assert client.get("/api/v1/agent/policy", headers=auth).json() == updated.json()
            # Delivery alone does not establish application, so fallback remains active.
            hb = client.post("/api/v1/agent/heartbeat", headers=auth,
                             json={"policy_version": 1, "agent_version": "test"}).json()
            assert hb["policy_update_available"] is True and hb["commands"] == []
            hb = client.post("/api/v1/agent/heartbeat", headers=auth,
                             json={"policy_version": updated.json()["version"], "agent_version": "test"}).json()
            assert hb["policy_update_available"] is False


def test_offline_policy_is_available_through_heartbeat(client):
    parent = parent_headers(client)
    child, device = enrolled_device(client, parent)
    auth = {"Authorization": f"Bearer {device['access_token']}"}
    response = client.put(f"/api/v1/children/{child}/policy", headers=parent, json={"payload": {}})
    assert response.status_code == 200
    hb = client.post("/api/v1/agent/heartbeat", headers=auth,
                     json={"policy_version": 1, "agent_version": "test"}).json()
    assert hb["policy_update_available"] and hb["policy_version"] == response.json()["version"]


def test_push_failure_and_timeout_do_not_undo_saved_policy(client, monkeypatch):
    parent = parent_headers(client)
    child, _ = enrolled_device(client, parent)
    monkeypatch.setattr(policy_service.manager, "send", AsyncMock(side_effect=RuntimeError("closed")))
    url = f"/api/v1/children/{child}/policy"
    response = client.put(url, headers=parent, json={"payload": {}})
    assert response.status_code == 200
    assert client.get(url, headers=parent).json() == response.json()

    async def stalled(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(policy_service.manager, "send", stalled)
    monkeypatch.setattr(policy_service, "POLICY_PUSH_TIMEOUT_SEC", 0.01)
    response = client.put(url, headers=parent, json={"payload": {}})
    assert response.status_code == 200 and response.json()["version"] == 3


def test_push_excludes_other_children_inactive_revoked_and_rejected_writes(client, db_session, monkeypatch):
    parent = parent_headers(client)
    child, device = enrolled_device(client, parent)
    other = parent_headers(client, "different@example.com")
    enrolled_device(client, other)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(policy_service.manager, "send", send)
    url = f"/api/v1/children/{child}/policy"
    assert client.put(url, headers=other, json={"payload": {}}).status_code == 404
    assert client.put(url, headers=parent, json={"payload": {"weekly_schedule": []}}).status_code == 422
    send.assert_not_called()
    assert client.put(url, headers=parent, json={"payload": {}}).status_code == 200
    assert [call.args[0] for call in send.call_args_list] == [device["device_id"]]
    stored = db_session.get(Device, device["device_id"])
    for status, revoked_at in [("inactive", None), ("active", utc_now())]:
        send.reset_mock()
        stored.status, stored.revoked_at = status, revoked_at
        db_session.commit()
        assert client.put(url, headers=parent, json={"payload": {}}).status_code == 200
        send.assert_not_called()
