import json
from pydantic import ValidationError

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from app.api.deps import get_current_device, get_db
from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models.device import Device
from app.schemas.device import DeviceAccessTokenResponse, DeviceRefreshRequest
from app.schemas.heartbeat import HeartbeatRequest, HeartbeatResponse
from app.schemas.policy import PolicyResponse
from app.schemas.command import WebSocketCommandAck
from app.services.command_service import ack_command, as_agent_command, mark_sent, pending_commands
from app.services.device_service import process_heartbeat
from app.services.enrollment_service import refresh_device_access_token
from app.services.policy_service import get_latest_policy
from app.services.realtime import manager

router = APIRouter()

@router.post(
    "/token/refresh", 
    response_model=DeviceAccessTokenResponse, 
    status_code=status.HTTP_200_OK
)
def refresh_token(
    payload: DeviceRefreshRequest,
    db: Session = Depends(get_db),
):
    token, expires_in = refresh_device_access_token(db, payload.refresh_token)

    return DeviceAccessTokenResponse(
        access_token=token,
        expires_in=expires_in
    )

@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    status_code=status.HTTP_200_OK,
)
def heartbeat(
    payload: HeartbeatRequest,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
):
    return process_heartbeat(
        db=db,
        device=device,
        agent_policy_version=payload.policy_version,
        quota_used_sec=payload.quota_used_sec,
        agent_wall_clock=payload.agent_wall_clock,
        quota_date=payload.quota_date,
    )

@router.get("/policy", response_model=PolicyResponse)
def get_policy(
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
):
    return get_latest_policy(db, device.child_id)

@router.websocket("/ws")
async def device_websocket(websocket: WebSocket):
    authorization = websocket.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        await websocket.close(code=4401)
        return

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        await websocket.close(code=4401)
        return

    if payload.get("type") != "device":
        await websocket.close(code=4403)
        return

    override = websocket.app.dependency_overrides.get(get_db)
    override_gen = None

    if override is not None:
        override_gen = override()
        db = next(override_gen)
    else:
        db = SessionLocal()

    device = db.get(Device, payload.get("sub"))
    if device is None or device.status != "active" or device.revoked_at is not None:
        db.close()
        await websocket.close(code=4401)
        return

    await manager.connect(device.id, websocket)

    try:
        # Flush queued commands immediately on connection
        for command in pending_commands(db, device.id):
            await websocket.send_json(as_agent_command(command).model_dump(mode="json"))
            mark_sent(db, command)

        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("type") == "ack":
                try:
                    ack = WebSocketCommandAck.model_validate(message)
                except ValidationError:
                    await websocket.close(code=1008, reason="Invalid command ACK")
                    break
                ack_command(
                    db, device.id, ack.command_id, ack.status, ack.error,
                )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(device.id, websocket)
        if override_gen is not None:
            try:
                next(override_gen)
            except StopIteration:
                pass
        else:
            db.close()
