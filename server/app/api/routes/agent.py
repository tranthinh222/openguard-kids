from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_device, get_db
from app.models.device import Device
from app.schemas.device import DeviceAccessTokenResponse, DeviceRefreshRequest
from app.schemas.heartbeat import HeartbeatRequest, HeartbeatResponse
from app.schemas.policy import PolicyResponse
from app.services.device_service import process_heartbeat
from app.services.enrollment_service import refresh_device_access_token
from app.services.policy_service import get_latest_policy

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
    )

@router.get("/policy", response_model=PolicyResponse)
def get_policy(
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
):
    return get_latest_policy(db, device.child_id)