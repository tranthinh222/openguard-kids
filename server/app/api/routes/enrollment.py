from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_parent, get_db
from app.models.user import User
from app.schemas.enrollment import (
    AgentEnrollRequest,
    AgentEnrollResponse,
    EnrollmentCodeResponse,
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
        code=code,
        expires_at=record.expires_at
    )

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

