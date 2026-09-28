from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_parent, get_db
from app.models.user import User
from app.models.enrollment import EnrollmentCode
from app.core.security import utc_now_aware
from app.schemas.device import as_utc
from app.schemas.enrollment import (
    AgentEnrollRequest,
    AgentEnrollResponse,
    EnrollmentCodeResponse,
    EnrollmentStatusResponse,
)

from app.services.child_service import get_owned_child
from app.services.enrollment_service import create_enrollment_code, enroll_device

router = APIRouter()

@router.post(
    "/children/{child_id}/enrollment",
    response_model=EnrollmentCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_code(
    child_id: str,
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = get_owned_child(db, parent.id, child_id)
    code, record = create_enrollment_code(db, parent.id, child)

    return EnrollmentCodeResponse(
        enrollment_id=record.id,
        code=code,
        expires_at=(
            record.expires_at.replace(tzinfo=timezone.utc)
            if record.expires_at.tzinfo is None
            else record.expires_at.astimezone(timezone.utc)
        ),
    )

@router.get(
    "/children/{child_id}/enrollment/{enrollment_id}",
    response_model=EnrollmentStatusResponse,
)
def enrollment_status(
    child_id: str,
    enrollment_id: str,
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    get_owned_child(db, parent.id, child_id)
    record = db.scalar(select(EnrollmentCode).where(
        EnrollmentCode.id == enrollment_id,
        EnrollmentCode.child_id == child_id,
        EnrollmentCode.parent_id == parent.id,
    ))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found")

    # Consumption is final, even when the original expiry has since passed.
    state = "used" if record.used_at is not None else (
        "expired" if as_utc(record.expires_at) <= utc_now_aware() else "pending"
    )
    return EnrollmentStatusResponse(enrollment_id=record.id, status=state)


@router.post(
    "/agent/enroll",
    response_model=AgentEnrollResponse,
    status_code=status.HTTP_201_CREATED,
)
def enroll(
    payload: AgentEnrollRequest,
    db: Session = Depends(get_db)
):
    device, access_token, refresh_token, expires_in = enroll_device(
        db=db,
        code=payload.code,
        device_name=payload.device_name,
        fingerprint=payload.fingerprint,
    )

    return AgentEnrollResponse(
        device_id=device.id,
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_expires_in=expires_in,
    )

