from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import utc_now
from app.models.command import DeviceCommand
from app.models.request import ChildRequest
from app.models.device import Device
from app.services.command_service import create_command

def create_child_request(
    db: Session,
    child_id: str,
    device_id: str,
    request_type: str,
    requested_minutes: int,
    subject: str | None = None,
) -> ChildRequest:
    # Avoid flooding parents with duplicate pending requests from the same device.
    existing = db.scalar(
        select(ChildRequest).where(
            ChildRequest.device_id == device_id,
            ChildRequest.type == request_type,
            ChildRequest.status == "pending",
            ChildRequest.subject == subject,
        ).order_by(ChildRequest.created_at.desc()).limit(1))

    if existing:
        return existing

    request = ChildRequest(
        child_id=child_id,
        device_id=device_id,
        type=request_type,
        requested_minutes=requested_minutes,
        subject=subject,
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
    response: str | None,
    source_ip: str | None = None,
) -> tuple[ChildRequest, DeviceCommand | None]:
    item = db.scalar(select(ChildRequest).where(ChildRequest.id == request_id, ChildRequest.child_id == child_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if item .status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request already decided")

    device = db.get(Device, item.device_id)
    if device is None or device.status != 'active' or device.revoked_at is not None:
        raise HTTPException(status_code=409, detail='Device is revoked or inactive')
    claimed = db.execute(update(ChildRequest).where(
        ChildRequest.id == item.id, ChildRequest.child_id == child_id, ChildRequest.status == 'pending',
    ).values(status='approved' if approve else 'rejected', parent_response=response,
             responded_at=utc_now(), responded_by=parent_id).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail='Request already decided')

    # The agent needs a command in both cases so the child sees the decision.
    command = None
    if item.type == "extra_time":
        body = {"minutes": item.requested_minutes, "request_id": item.id}
        if approve:
            command = create_command(db, item.device_id, "ADD_TIME", body, commit=False)
        else:
            command = create_command(db, item.device_id, "REQUEST_REJECTED", {**body, "response": response}, commit=False)
    elif item.type == "false_block":
        # Approval acknowledges the complaint; policy changes remain explicit in
        # the policy editor (especially executable hash rules).
        command = create_command(db, item.device_id, "REQUEST_REVIEWED", {
            "request_id": item.id, "subject": item.subject,
            "approved": approve, "response": response,
        }, commit=False)

    from app.services.control_audit import record
    record(db, child_id, parent_id, source_ip, "request_decided",
           old={"request_id": item.id, "status": "pending"},
           new={"request_id": item.id, "status": "approved" if approve else "rejected"})
    db.commit()
    db.refresh(item)

    return item, command
