from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utc_now
from app.models.command import DeviceCommand
from app.models.request import ChildRequest
from app.services.command_service import create_command

def create_child_request(
    db: Session,
    child_id: str,
    device_id: str,
    request_type: str,
    requested_minutes: int
) -> ChildRequest:
    # Avoid flooding parents with duplicate pending requests from the same device.
    existing = db.scalar(
        select(ChildRequest).where(
            ChildRequest.device_id == device_id,
            ChildRequest.type == request_type,
            ChildRequest.status == "pending",
        ).order_by(ChildRequest.created_at.desc()).limit(1))

    if existing:
        return existing

    request = ChildRequest(
        child_id=child_id,
        device_id=device_id,
        type=request_type,
        requested_minutes=requested_minutes,
        status="pending",
    )

    db.add(request)
    db.commit()
    db.refresh(request)

    return request

def list_child_requests(
    db: Session,
    child_id: str,
) -> list[ChildRequest]:
    return list(db.scalars(
        select(ChildRequest)
        .where(ChildRequest.child_id == child_id)
        .order_by(ChildRequest.created_at.desc())
    ))

def decide_request(
    db: Session,
    request_id: str,
    child_id: str,
    parent_id: str,
    approve: bool,
    response: str | None
) -> tuple[ChildRequest, DeviceCommand | None]:
    item = db.scalar(select(ChildRequest).where(ChildRequest.id == request_id, ChildRequest.child_id == child_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if item .status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request already decided")

    item.status = "approved" if approve else "rejected"
    item.parent_response = response
    item.responded_at = utc_now()
    item.responded_by = parent_id

    # The agent needs a command in both cases so the child sees the decision.
    command = None
    if item.type == "extra_time":
        body = {"minutes": item.requested_minutes, "request_id": item.id}
        if approve:
            command = create_command(db, item.device_id, "ADD_TIME", body)
        else:
            command = create_command(db, item.device_id, "REQUEST_REJECTED", {**body, "response": response})

    db.commit()
    db.refresh(item)

    return item, command
