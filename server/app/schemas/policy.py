from typing import Any

from pydantic import BaseModel, Field, field_validator
from app.schemas.content_rules import AppRule, DomainPolicy

class ScreenTimePolicy(BaseModel):
    weekday_minutes: int = Field(default=90, ge=1, le=1440)
    weekend_minutes: int = Field(default=120, ge=1, le=1440)
    idle_timeout_sec: int = Field(default=300, ge=60, le=3600)
    grace_period_sec: int = Field(default=60, ge=0, le=300)
    warning_minutes: list[int] = Field(default_factory=lambda: [10, 5, 1])

    @field_validator("warning_minutes")
    @classmethod
    def validate_warnings(cls, value: list[int]) -> list[int]:
        cleaned = sorted(set(value), reverse=True)
        if any(item < 1 or item > 60 for item in cleaned):
            raise ValueError("warning minutes must be between 1 and 60")
        return cleaned

class PolicyPayload(BaseModel):
    screen_time: ScreenTimePolicy = Field(default_factory=ScreenTimePolicy)
    # 7 days x 48 half-hour slots. True means usage is allowed.
    weekly_schedule: list[bool] = Field(default_factory=lambda: [True] * 336)
    apps: list[AppRule] = Field(default_factory=list, max_length=500)
    domains: DomainPolicy = Field(default_factory=DomainPolicy)

    @field_validator("domains", mode="before")
    @classmethod
    def legacy_domains(cls, value):
        # Week 02's empty placeholder remains valid input, never rewrite stored signatures.
        return {} if value == [] else value

    @field_validator("apps")
    @classmethod
    def unique_apps(cls, value):
        names = [rule.name for rule in value]
        hashes = [rule.sha256 for rule in value if rule.sha256]
        if len(set(names)) != len(names) or len(set(hashes)) != len(hashes):
            raise ValueError("Duplicate executable name or hash")
        return value

    @field_validator("weekly_schedule")
    @classmethod
    def validate_schedule(cls, value: list[bool]) -> list[bool]:
        if len(value) != 336:
            raise ValueError("weekly_schedule must contain exactly 336 half-hour slots")
        return value

class PolicyUpdateRequest(BaseModel):
    payload: PolicyPayload

class PolicyResponse(BaseModel):
    id: str
    version: int
    payload: dict[str, Any]
    signature: str

    model_config = {"from_attributes": True}

