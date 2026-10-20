from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from app.schemas.content_rules import normalize_domain, process_name

EventType = Literal["app_start", "app_stop", "domain_query", "blocked_app", "blocked_domain",
                    "quota_warning", "locked", "unlock_request", "override_granted"]


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    ts: AwareDatetime
    type: EventType
    subject: str | None = Field(default=None, max_length=253)
    duration_sec: int = Field(default=0, ge=0, le=86400, strict=True)
    policy_id: UUID | None = None
    # Optional legacy identity fields must match the authenticated device.
    device_id: UUID | None = None
    child_id: UUID | None = None

    @model_validator(mode="after")
    def minimal_subject(self):
        if self.type in {"app_start", "app_stop", "blocked_app"}:
            self.subject = process_name(self.subject or "")
        elif self.type in {"domain_query", "blocked_domain"}:
            self.subject = normalize_domain(self.subject or "")
        elif self.subject is not None:
            raise ValueError("This event type must not contain free-form subject data")
        if self.type != "app_stop" and self.duration_sec:
            raise ValueError("Only app_stop carries application duration")
        return self


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[dict[str, Any]] = Field(min_length=1, max_length=500)
