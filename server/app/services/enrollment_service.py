from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_enrollment_code,
    generate_refresh_token,
    hash_device_fingerprint,
    hash_secret,
    utc_now,
)

from app.models.child import Child
from app.models.device import Device
from app.models.enrollment import EnrollmentCode
from app.models.token import DeviceRefreshToken

def create_enrollment_code(db: Session, parent_id: str, child: Child) -> tuple[str, EnrollmentCode]:
    code = generate_enrollment_code(8)
    record = EnrollmentCode(
        parent_id=parent_id,
        child_id=child.id,
        code_hash=hash_secret(code),
        expires_at=utc_now() + timedelta(minutes=settings.enrollment_code_expire_minutes),
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return code, record

def enroll_device(
    db: Session,
    code: str,
    device_name: str,
    fingerprint: str,
) -> tuple[Device, str, str, int]:
    now = utc_now()

    record = db.scalar(select(EnrollmentCode).where(EnrollmentCode.code_hash == hash_secret(code)))

    if record is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid enrollment code")

    if record.used_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enrollment code already used")

    if record.expires_at < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enrollment code expired")

    device = Device(
        child_id=record.child_id,
        device_name=device_name,
        fingerprint_hash=hash_device_fingerprint(fingerprint),
        status="active",
        current_policy_version=0,
    )

    db.add(device)
    db.flush()

    refresh_token = generate_refresh_token()
    refresh_record = DeviceRefreshToken(
        device_id=device.id,
        token_hash=hash_secret(refresh_token),
        expires_at=now + timedelta(settings.device_refresh_token_expire_days),
    )
    db.add(refresh_record)

    record.used_at = now
    db.commit()
    db.refresh(device)

    access_token = create_access_token(
        subject=device.id,
        token_type="device",
        expires_minutes=settings.device_access_token_expire_minutes,
    )

    return (
        device,
        access_token,
        refresh_token,
        settings.device_access_token_expire_minutes * 60
    )

def refresh_device_access_token(db: Session, refresh_token: str) -> tuple[str, int]:
    now = utc_now()

    record = db.scalar(
        select(DeviceRefreshToken).where(DeviceRefreshToken.token_hash == hash_secret(refresh_token))
    )

    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at < now
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    device = db.get(Device, record.device_id)
    if (
        device is None 
        or device.status != "active" 
        or device.revoked_at is not None
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device revoked")

    access_token = create_access_token(
        subject=device.id,
        token_type="device",
        expires_minutes=settings.device_access_token_expire_minutes,
    )

    return (
        access_token,
        settings.device_access_token_expire_minutes * 60
    )
