from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utc_now
from app.models.command import DeviceCommand
from app.schemas.command import AgentCommandResponse

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
        .order_by(DeviceCommand.created_at.asc())
        .limit(20)
    ))

def mark_sent(db: Session, command: DeviceCommand) -> None:
    if command.status == "pending":
        command.status = "sent"
        command.sent_at = utc_now()

        db.commit()

def ack_command(
    db: Session, 
    device_id: str, 
    command_id: str, 
    status: str, 
    error: str | None = None
) -> DeviceCommand | None:
    command = db.scalar(select(DeviceCommand).where(DeviceCommand.id == command_id, DeviceCommand.device_id == device_id))

    if command is None:
        return None

    command.status = status
    command.error = error
    command.ack_at = utc_now()

    db.commit()
    db.refresh(command)

    return command

def as_agent_command(command: DeviceCommand) -> AgentCommandResponse:
    return AgentCommandResponse(
        command_id=command.id,
        type=command.type,
        payload=command.payload or {},
    )
