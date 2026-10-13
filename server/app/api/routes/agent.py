import json
import asyncio
import time
from app.core.config import settings
from pydantic import ValidationError

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from jwt import InvalidTokenError
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

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

    device_id = payload['sub']
    connected = False
    try:
        device = db.get(Device, device_id)
        if device is None or device.status != 'active' or device.revoked_at is not None:
            await websocket.close(code=4401)
            return
        await manager.connect(device_id, websocket)
        connected = True
        # Flush queued commands immediately on connection
        for command in pending_commands(db, device.id):
            await asyncio.wait_for(websocket.send_json(as_agent_command(command).model_dump(mode='json')), timeout=2)
            mark_sent(db, command)

        window, count = time.monotonic(), 0
        while True:
            # End the read transaction so revocation in another session becomes visible.
            db.rollback()
            device = db.get(Device, device_id, populate_existing=True)
            try:
                decode_access_token(token)
            except InvalidTokenError:
                await websocket.close(code=4401)
                break
            if device is None or device.status != 'active' or device.revoked_at is not None:
                await websocket.close(code=4401)
                break
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=settings.websocket_auth_interval_sec)
            except asyncio.TimeoutError:
                continue
            if len(raw.encode('utf-8')) > settings.websocket_max_message_bytes:
                await websocket.close(code=1009)
                break
            if time.monotonic() - window >= 60:
                window, count = time.monotonic(), 0
            count += 1
            if count > settings.websocket_messages_per_minute:
                await websocket.close(code=1008, reason='Too many messages')
                break
            # Check again after receive: a device may have been revoked while waiting.
            db.rollback()
            device = db.get(Device, device_id, populate_existing=True)
            if device is None or device.status != 'active' or device.revoked_at is not None:
                await websocket.close(code=4401)
                break
            try:
                decode_access_token(token)
                ack = WebSocketCommandAck.model_validate_json(raw)
            except InvalidTokenError:
                await websocket.close(code=4401)
                break
            except ValidationError:
                await websocket.close(code=1008, reason='Invalid command ACK')
                break
            command = ack_command(db, device_id, ack.command_id, ack.status, ack.error)
            if command is None:
                await websocket.close(code=1008, reason='Unknown command')
                break
    except WebSocketDisconnect:
        pass
    except (asyncio.TimeoutError, KeyError, ValueError):
        await websocket.close(code=1008)
    except SQLAlchemyError:
        await websocket.close(code=1011, reason='Database temporarily unavailable')
    finally:
        if connected:
            await manager.disconnect(device_id, websocket)
        if override_gen is not None:
            try:
                next(override_gen)
            except StopIteration:
                pass
        else:
            db.close()
