from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_device, get_current_parent_for_write, get_db
from app.models.child import Child
from app.models.device import Device
from app.models.user import User
from app.schemas.command import CommandAckRequest, CommandCreateRequest, ParentCommandResponse
from app.services.command_service import ack_command, create_command, push_command

router = APIRouter()

def owned_device(
    db: Session,
    parent_id: str,
    device_id: str,
) -> Device:
    device = db.scalar(
        select(Device).join(Child, Device.child_id == Child.id)
        .where(Device.id == device_id, Child.parent_id == parent_id)
    )

    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    return device

@router.post("/devices/{device_id}/commands", response_model=ParentCommandResponse, status_code=status.HTTP_201_CREATED)
async def parent_create_command(
    device_id: str,
    payload: CommandCreateRequest,
    parent: User = Depends(get_current_parent_for_write),
    db: Session = Depends(get_db),
):
    device = owned_device(db, parent.id, device_id)
    body = {"minutes": payload.minutes} if payload.type == "ADD_TIME" else {}

    if payload.type == "ADD_TIME" and payload.minutes is None:
        raise HTTPException(status_code=422, detail="minutes is required for ADD_TIME")

    command = create_command(db, device.id, payload.type, body)
    await push_command(db, command)

    return command

@router.post("/agent/commands/{command_id}/ack", response_model=ParentCommandResponse)
def agent_ack_command(
    command_id: str,
    payload: CommandAckRequest,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
):
    command = ack_command(db, device.id, command_id, payload.status, payload.error)
    if command is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command not found")

    return command
