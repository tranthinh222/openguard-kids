import asyncio
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import update

from app.core.security import utc_now
from app.models.command import DeviceCommand
from app.services import command_service
from test_week02 import parent_headers, enrolled_device


@pytest.fixture
def setup(client):
    parent = parent_headers(client)
    _, device = enrolled_device(client, parent)
    return parent, device, {"Authorization": f"Bearer {device['access_token']}"}


def create(client, parent, device):
    response = client.post(f"/api/v1/devices/{device['device_id']}/commands", headers=parent,
                           json={"type": "ADD_TIME", "minutes": 15})
    assert response.status_code == 201
    return response.json()


def heartbeat(client, auth):
    return client.post("/api/v1/agent/heartbeat", headers=auth,
                       json={"policy_version": 1, "agent_version": "test"}).json()["commands"]


def test_lost_delivery_and_ack_replay_same_id_until_terminal_ack(client, setup):
    parent, device, auth = setup
    command = create(client, parent, device)
    assert command["status"] == "pending"
    # First response is lost after sent_at was committed.
    first = heartbeat(client, auth)
    second = heartbeat(client, auth)
    assert first == second and first[0]["command_id"] == command["id"]
    # Agent executed and saved the result, but its first ACK never reached server.
    assert heartbeat(client, auth) == first
    url = f"/api/v1/agent/commands/{command['id']}/ack"
    ack = client.post(url, headers=auth, json={"status": "completed"}).json()
    assert ack["sent_at"] and ack["ack_at"] and ack["status"] == "completed"
    assert heartbeat(client, auth) == []
    # Server received ACK but its HTTP response was lost: duplicate is harmless.
    duplicate = client.post(url, headers=auth, json={"status": "completed"}).json()
    assert duplicate == ack
    conflicting = client.post(url, headers=auth, json={"status": "failed", "error": "late"}).json()
    assert conflicting == ack


def test_reconnect_replays_sent_command_with_original_id(client, setup):
    parent, device, auth = setup
    with client.websocket_connect("/api/v1/agent/ws", headers=auth) as ws:
        command = create(client, parent, device)
        first = ws.receive_json()
        assert command["sent_at"] and first["command_id"] == command["id"]
        # Disconnect before server receives ACK.
    with client.websocket_connect("/api/v1/agent/ws", headers=auth) as ws:
        assert ws.receive_json() == first
        ws.send_json({"type": "ack", "command_id": command["id"], "status": "completed"})
        # Invalid ACK closes the socket, confirming the prior message was processed.
        ws.send_json({"type": "ack", "command_id": command["id"], "status": "sent"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008
    assert heartbeat(client, auth) == []


def test_fast_ack_during_push_is_not_overwritten(client, setup, db_session, monkeypatch):
    parent, device, auth = setup

    async def ack_before_send_returns(device_id, message):
        command_service.ack_command(db_session, device_id, message["command_id"], "completed")
        return True

    monkeypatch.setattr(command_service.manager, "send", ack_before_send_returns)
    command = create(client, parent, device)
    assert command["status"] == "completed" and command["ack_at"]
    assert heartbeat(client, auth) == []


def test_mark_sent_handles_stale_orm_object(db_session, client, setup):
    _, device, _ = setup
    command = command_service.create_command(db_session, device["device_id"], "LOCK_NOW")
    ack_at = utc_now()
    db_session.execute(update(DeviceCommand).where(DeviceCommand.id == command.id)
                       .values(status="completed", ack_at=ack_at).execution_options(synchronize_session=False))
    db_session.commit()
    assert command.status == "pending"  # stale snapshot of state before ACK
    command_service.mark_sent(db_session, command)
    assert command.status == "completed" and command.ack_at == ack_at


def test_timeout_and_send_error_leave_command_retryable(client, setup, monkeypatch):
    parent, device, auth = setup
    monkeypatch.setattr(command_service.manager, "send", AsyncMock(side_effect=RuntimeError("disconnected")))
    command = create(client, parent, device)
    assert command["status"] == "pending" and not command["ack_at"]

    async def stall(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(command_service.manager, "send", stall)
    monkeypatch.setattr(command_service, "COMMAND_PUSH_TIMEOUT_SEC", 0.01)
    second = create(client, parent, device)
    assert second["status"] == "pending"
    assert {c["command_id"] for c in heartbeat(client, auth)} == {command["id"], second["id"]}


def test_wrong_device_and_invalid_ack_cannot_remove_retry(client, setup):
    parent, device, auth = setup
    command = create(client, parent, device)
    other_parent = parent_headers(client, "other-ack@example.com")
    _, other_device = enrolled_device(client, other_parent)
    other_auth = {"Authorization": f"Bearer {other_device['access_token']}"}
    url = f"/api/v1/agent/commands/{command['id']}/ack"
    assert client.post(url, headers=other_auth, json={"status": "completed"}).status_code == 404
    assert client.post(url, headers=auth, json={"status": "sent"}).status_code == 422
    assert heartbeat(client, auth)[0]["command_id"] == command["id"]
    result = client.post(url, headers=auth, json={"status": "failed", "error": "OS refused"})
    assert result.json()["status"] == "failed"
    assert heartbeat(client, auth) == []
