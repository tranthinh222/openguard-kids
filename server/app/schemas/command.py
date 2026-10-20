from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.schemas.device import UTCDateTime

ParentCommandType = Literal["LOCK_NOW", "UNLOCK", "ADD_TIME"]
# REQUEST_REJECTED is created only by the server when a parent rejects a request.
CommandType = Literal["LOCK_NOW", "UNLOCK", "ADD_TIME", "REQUEST_REJECTED", "REQUEST_REVIEWED"]

class CommandCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: ParentCommandType
    minutes: int | None = Field(default=None, ge=1, le=240, strict=True)

    @model_validator(mode='after')
    def validate_minutes(self):
        if (self.type == 'ADD_TIME') != (self.minutes is not None):
            raise ValueError('minutes is required only for ADD_TIME')
        return self

class AgentCommandResponse(BaseModel):
    command_id: str
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)

class CommandAckRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal["completed", "failed"]
    error: str | None = Field(default=None, max_length=255)

class WebSocketCommandAck(CommandAckRequest):
    type: Literal["ack"]
    command_id: str = Field(min_length=1, max_length=36)

class ParentCommandResponse(BaseModel):
    id: str
    device_id: str
    type: str
    payload: dict[str, Any]
    status: str
    created_at: UTCDateTime
    sent_at: UTCDateTime | None
    ack_at: UTCDateTime | None

    model_config = {"from_attributes": True}
