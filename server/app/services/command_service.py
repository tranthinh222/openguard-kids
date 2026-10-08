import asyncio
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import utc_now
from app.models.command import DeviceCommand
from app.schemas.command import AgentCommandResponse
from app.services.realtime import manager

LOGGER = logging.getLogger(__name__)
COMMAND_PUSH_TIMEOUT_SEC = 2.0

def create_command(
    db: Session, 
    device_id: str, 
    command_type: str, 
    payload: dict | None = None
) -> DeviceCommand:
    command = DeviceCommand(
        device_id=device_id,
        type=command_type,
        payload=payload or {},
        status="pending",
    )

    db.add(command)
    db.commit()
    db.refresh(command)

    return command

def pending_commands(db: Session, device_id: str) -> list[DeviceCommand]:
    return list(db.scalars(
        select(DeviceCommand)
        .where(DeviceCommand.device_id == device_id, DeviceCommand.status.in_(["pending", "sent"]))
        .order_by(DeviceCommand.created_at.asc(), DeviceCommand.id.asc())
        .limit(20)
    ))

def mark_sent(db: Session, command: DeviceCommand) -> None:
    now = utc_now()
    # A fast ACK may already have completed the command in another session.
    # Compare-and-set in SQL, never overwrite that result from a stale ORM object.
    db.execute(update(DeviceCommand).where(
        DeviceCommand.id == command.id, DeviceCommand.status == "pending",
    ).values(status="sent", sent_at=now, updated_at=now).execution_options(synchronize_session=False))
    db.commit()
    db.refresh(command)

async def push_command(db: Session, command: DeviceCommand) -> bool:
    """Deliver a queued command over WebSocket now; heartbeat remains the fallback."""
    try:
        delivered = await asyncio.wait_for(
            manager.send(command.device_id, as_agent_command(command).model_dump(mode="json")),
            timeout=COMMAND_PUSH_TIMEOUT_SEC,
        )
    except Exception:
        LOGGER.warning("Command push failed; retained for heartbeat retry: %s", command.id, exc_info=True)
        return False

    if delivered:
        mark_sent(db, command)

    return delivered

def ack_command(
    db: Session, 
    device_id: str, 
    command_id: str, 
    status: str, 
    error: str | None = None
) -> DeviceCommand | None:
    if status not in {"completed", "failed"}:
        raise ValueError("ACK must be completed or failed")
    now = utc_now()
    # First terminal ACK wins. Repeated/delayed ACKs do not change the result or time.
    db.execute(update(DeviceCommand).where(
        DeviceCommand.id == command_id, DeviceCommand.device_id == device_id,
        DeviceCommand.status.in_(["pending", "sent"]),
    ).values(status=status, error=error if status == "failed" else None,
             ack_at=now, updated_at=now).execution_options(synchronize_session=False))
    db.commit()
    return db.scalar(select(DeviceCommand).where(
        DeviceCommand.id == command_id, DeviceCommand.device_id == device_id,
    ).execution_options(populate_existing=True))

def as_agent_command(command: DeviceCommand) -> AgentCommandResponse:
    return AgentCommandResponse(
        command_id=command.id,
        type=command.type,
        payload=command.payload or {},
    )
