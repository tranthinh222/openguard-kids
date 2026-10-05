from datetime import timezone, datetime
from typing import Any
from sqlalchemy.orm import Session

from app.core.security import utc_now
from app.core.config import settings
from app.models.device import Device
from app.services.command_service import as_agent_command, mark_sent, pending_commands
from app.services.policy_service import get_latest_policy

ONLINE_TIMEOUT_SECONDS = 120

def device_is_online(device: Device) -> bool:
    if device.last_seen_at is None or device.status != "active" or device.revoked_at is not None:
        return False

    age = (utc_now() - device.last_seen_at).total_seconds()

    return age < ONLINE_TIMEOUT_SECONDS

def process_heartbeat(
    db: Session, 
    device: Device, 
    agent_policy_version: int,
    quota_used_sec: int = 0,
    agent_wall_clock: datetime | None=None
) -> dict[str, Any]:
    latest_policy = get_latest_policy(db, device.child_id)
    now = utc_now()
    server_now = now.replace(tzinfo=timezone.utc)

    device.last_seen_at = now
    device.current_policy_version = agent_policy_version
    device.quota_used_sec = quota_used_sec

    drift = None
    if agent_wall_clock is not None:
        wall = agent_wall_clock
        if wall.tzinfo is None:
            wall = wall.replace(tzinfo=timezone.utc)

        drift = (wall.astimezone(timezone.utc) - server_now).total_seconds()
    device.clock_drift_sec = drift

    commands = pending_commands(db, device.id)
    for command in commands:
        mark_sent(db, command)

    db.commit()

    return {
        "server_time": server_now,
        "clock_drift_sec": drift,
        "clock_trusted": drift is not None and abs(drift) <= settings.agent_clock_drift_threshold_sec,
        "clock_drift_threshold_sec": settings.agent_clock_drift_threshold_sec,
        "policy_version": latest_policy.version,
        "policy_update_available": agent_policy_version != latest_policy.version,
        "commands": [as_agent_command(command) for command in commands],
    }
