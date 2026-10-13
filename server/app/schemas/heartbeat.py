from datetime import date, datetime

from pydantic import BaseModel, Field, AwareDatetime, ConfigDict
from app.schemas.command import AgentCommandResponse

class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    policy_version: int = Field(ge=0, strict=True)
    agent_version: str = Field(min_length=1, max_length=64)
    quota_used_sec: int = Field(default=0, ge=0, le=86400, strict=True)
    quota_date: date | None = None
    agent_wall_clock: AwareDatetime | None = None

class HeartbeatResponse(BaseModel):
    server_time: datetime
    clock_drift_sec: float | None = None
    clock_trusted: bool
    clock_drift_threshold_sec: float
    policy_version: int
    policy_update_available: bool
    commands: list[AgentCommandResponse] = Field(default_factory=list)
