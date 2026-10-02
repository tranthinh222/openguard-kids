from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_parent, get_current_parent_for_write, get_db
from app.models.device import Device
from app.models.user import User
from app.schemas.child import ChildCreateRequest, ChildResponse, ChildSummaryResponse
from app.schemas.device import ParentDeviceResponse
from app.schemas.policy import PolicyResponse, PolicyUpdateRequest
from app.services.child_service import create_child, get_owned_child, list_children
from app.services.device_service import device_is_online
from app.services.policy_service import get_latest_policy, update_policy

router = APIRouter()


@router.post("", response_model=ChildResponse, status_code=status.HTTP_201_CREATED)
def create(
    payload: ChildCreateRequest,
    parent: User = Depends(get_current_parent_for_write),
    db: Session = Depends(get_db),
):
    return create_child(
        db=db,
        parent_id=parent.id,
        display_name=payload.display_name,
        birth_year=payload.birth_year,
    )


@router.get("", response_model=list[ChildSummaryResponse])
def list_all(
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    result = []
    for child in list_children(db, parent.id):
        devices = list(db.scalars(select(Device).where(Device.child_id == child.id)))
        result.append(
            ChildSummaryResponse(
                id=child.id,
                parent_id=child.parent_id,
                display_name=child.display_name,
                birth_year=child.birth_year,
                device_count=len(devices),
                online_count=sum(1 for device in devices if device_is_online(device)),
            )
        )
    return result


@router.get("/{child_id}", response_model=ChildResponse)
def get_one(
    child_id: str,
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    return get_owned_child(db, parent.id, child_id)


@router.get("/{child_id}/devices", response_model=list[ParentDeviceResponse])
def get_child_devices(
    child_id: str,
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = get_owned_child(db, parent.id, child_id)
    devices = list(
        db.scalars(
            select(Device)
            .where(Device.child_id == child.id)
            .order_by(Device.created_at.desc())
        )
    )
    return [
        ParentDeviceResponse(
            id=device.id,
            child_id=device.child_id,
            device_name=device.device_name,
            status=device.status,
            last_seen_at=device.last_seen_at,
            current_policy_version=device.current_policy_version,
            quota_used_sec=device.quota_used_sec,
            clock_drift_sec=device.clock_drift_sec,
            online=device_is_online(device),
        )
        for device in devices
    ]


@router.get("/{child_id}/policy", response_model=PolicyResponse)
def get_child_policy(
    child_id: str,
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = get_owned_child(db, parent.id, child_id)
    return get_latest_policy(db, child.id)

@router.put("/{child_id}/policy", response_model=PolicyResponse)
def update_child_policy(
    child_id: str,
    payload: PolicyUpdateRequest,
    parent: User = Depends(get_current_parent_for_write),
    db: Session = Depends(get_db),
):
    child = get_owned_child(db, parent.id, child_id)

    return update_policy(db, child.id, payload.payload)