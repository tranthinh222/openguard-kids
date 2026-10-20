from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.schemas.content_rules import normalize_domain, process_name
from app.schemas.device import UTCDateTime

class AgentChildRequestCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal["extra_time", "false_block"] = "extra_time"
    requested_minutes: int = Field(default=15, ge=5, le=120, strict=True)
    subject: str | None = Field(default=None, max_length=253)

    @model_validator(mode="after")
    def validate_subject(self):
        if self.type == "false_block":
            if not self.subject:
                raise ValueError("A blocked domain or executable name is required")
            self.subject = (process_name(self.subject) if self.subject.lower().endswith(".exe")
                            else normalize_domain(self.subject))
        elif self.subject is not None:
            raise ValueError("subject is only valid for false_block")
        return self

class RequestDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    response: str | None = Field(default=None, max_length=255)

class ChildRequestResponse(BaseModel):
    id: str
    child_id: str
    device_id: str
    type: str
    subject: str | None = None
    requested_minutes: int
    status: str
    parent_response: str | None
    created_at: UTCDateTime
    responded_at: UTCDateTime | None

    model_config = {"from_attributes": True}
