from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_current_admin, get_current_parent_for_write, get_db
from app.core.security import create_access_token
from app.models.device import Device
from app.models.child import Child
from app.models.user import User
from app.services.child_service import get_owned_child

router = APIRouter()


@router.post("/children/{child_id}/devices/{device_id}/child-view-token")
def child_view_token(child_id: str, device_id: str,
                     parent: User = Depends(get_current_parent_for_write), db: Session = Depends(get_db)):
    get_owned_child(db, parent.id, child_id)
    device = db.get(Device, device_id)
    if device is None or device.child_id != child_id or device.status != "active" or device.revoked_at:
        raise HTTPException(404, "Device not found")
    return {"access_token": create_access_token(device.id, "child-view", 15),
            "token_type": "bearer", "expires_in": 900}


@router.get("/admin/summary")
def admin_summary(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    # Operator role is intentionally separate from parent access to children's reports.
    return {"parents": db.scalar(select(func.count()).select_from(User).where(User.role == "parent")),
            "children": db.scalar(select(func.count()).select_from(Child)),
            "devices": db.scalar(select(func.count()).select_from(Device))}
