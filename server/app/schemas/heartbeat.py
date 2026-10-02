from datetime import datetime

from pydantic import BaseModel, Field
from app.schemas.command import AgentCommandResponse

class HeartbeatRequest(BaseModel):
    policy_version: int = Field(ge=0)
    agent_version: str = Field(min_length=1, max_length=64)
    quota_used_sec: int = Field(default=0, ge=0)
    agent_wall_clock: datetime | None = None

class HeartbeatResponse(BaseModel):
    server_time: datetime
    policy_version: int
    policy_update_available: bool
    commands: list[AgentCommandResponse] = Field(default_factory=list)
