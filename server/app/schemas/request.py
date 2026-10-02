from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

class AgentChildRequestCreate(BaseModel):
    type: Literal["extra_time"] = "extra_time"
    requested_minutes: int = Field(default=15, ge=5, le=120)

class RequestDecision(BaseModel):
    response: str | None = Field(default=None, max_length=255)

class ChildRequestResponse(BaseModel):
    id: str
    child_id: str
    device_id: str
    type: str
    requested_minutes: int
    status: str
    parent_response: str | None
    created_at: datetime
    responded_at: datetime | None

    model_config = {"from_attributes": True}
