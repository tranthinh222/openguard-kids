from datetime import timezone
from typing import Any
from sqlalchemy.orm import Session

from app.core.security import utc_now, utc_now_aware
from app.models.device import Device
from app.services.policy_service import get_latest_policy

def device_is_online(device: Device, threshold_seconds: int = 120) -> bool:
    if device.last_seen_at is None:
        return False

    last_seen = device.last_seen_at
    if last_seen.tzinfo is not None:
        last_seen = last_seen.astimezone(timezone.utc).replace(tzinfo=None)

    return (utc_now() - last_seen).total_seconds() < threshold_seconds

def process_heartbeat(db: Session, device: Device, agent_policy_version: int) -> dict[str, Any]:
    latest_policy = get_latest_policy(db, device.child_id)

    device.last_seen_at = utc_now()
    device.current_policy_version = agent_policy_version
    db.commit()

    return {
        "server_time": utc_now_aware(),
        "policy_version": latest_policy.version,
        "policy_update_available": agent_policy_version != latest_policy.version,
        "commands": [],
    }
