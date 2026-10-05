from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_device, get_current_parent, get_current_parent_for_write, get_db
from app.models.device import Device
from app.models.user import User
from app.schemas.request import AgentChildRequestCreate, ChildRequestResponse, RequestDecision
from app.services.child_service import get_owned_child
from app.services.command_service import push_command
from app.services.request_service import create_child_request, decide_request, list_child_requests

router = APIRouter()


@router.post("/agent/requests", response_model=ChildRequestResponse)
def agent_create_request(
    payload: AgentChildRequestCreate,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
):
    return create_child_request(db, device.child_id, device.id, payload.type, payload.requested_minutes)

@router.get("/children/{child_id}/requests", response_model=list[ChildRequestResponse])
def parent_list_requests(
    child_id: str,
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = get_owned_child(db, parent.id, child_id)

    return list_child_requests(db, child.id)

@router.post("/children/{child_id}/requests/{request_id}/approve", response_model=ChildRequestResponse)
async def approve_request(
    child_id: str,
    request_id: str,
    payload: RequestDecision,
    parent: User = Depends(get_current_parent_for_write),
    db: Session = Depends(get_db),
):
    child = get_owned_child(db, parent.id, child_id)
    item, command = decide_request(db, request_id, child.id, parent.id, True, payload.response)

    if command is not None:
        await push_command(db, command)

    return item

@router.post("/children/{child_id}/requests/{request_id}/reject", response_model=ChildRequestResponse)
async def reject_request(
    child_id: str,
    request_id: str,
    payload: RequestDecision,
    parent: User = Depends(get_current_parent_for_write),
    db: Session = Depends(get_db),
):
    child = get_owned_child(db, parent.id, child_id)
    item, command = decide_request(db, request_id, child.id, parent.id, False, payload.response)

    if command is not None:
        await push_command(db, command)

    return item