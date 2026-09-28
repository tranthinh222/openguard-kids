from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.child import Child
from app.models.device import Device
from app.services.device_service import device_is_online

def dashboard_summary(db: Session, parent_id: str) -> dict:
    children = list(
        db.scalars(
            select(Child)
            .where(Child.parent_id == parent_id)
            .order_by(Child.created_at.asc())
        )
    )

    rows = list(
        db.execute(
            select(Device, Child.display_name)
            .join(Child, Device.child_id == Child.id)
            .where(Child.parent_id == parent_id)
            .order_by(Device.created_at.desc())
        )
    )

    online_count = sum(1 for device, _ in rows if device_is_online(device))

    recent_devices = [
        {
            "id": device.id,
            "child_id": device.child_id,
            "child_name": child_name,
            "device_name": device.device_name,
            "last_seen_at": device.last_seen_at,
            "current_policy_version": device.current_policy_version,
            "online": device_is_online(device),
        }
        for device, child_name in rows[:8]
    ]

    return {
        "children_count": len(children),
        "device_count": len(rows),
        "online_count": online_count,
        "offline_count": len(rows) - online_count,
        "recent_devices": recent_devices,
    }

