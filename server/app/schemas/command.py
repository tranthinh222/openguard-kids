from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ParentCommandType = Literal["LOCK_NOW", "UNLOCK", "ADD_TIME"]
# REQUEST_REJECTED is created only by the server when a parent rejects a request.
CommandType = Literal["LOCK_NOW", "UNLOCK", "ADD_TIME", "REQUEST_REJECTED"]

class CommandCreateRequest(BaseModel):
    type: ParentCommandType
    minutes: int | None = Field(default=None, ge=1, le=240)

class AgentCommandResponse(BaseModel):
    command_id: str
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)

class CommandAckRequest(BaseModel):
    status: Literal["completed", "failed"]
    error: str | None = Field(default=None, max_length=255)

class ParentCommandResponse(BaseModel):
    id: str
    device_id: str
    type: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    sent_at: datetime | None
    ack_at: datetime | None

    model_config = {"from_attributes": True}
