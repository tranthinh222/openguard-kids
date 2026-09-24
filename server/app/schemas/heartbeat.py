from datetime import datetime

from pydantic import BaseModel, Field

class HeartbeatRequest(BaseModel):
    policy_version: int = Field(ge=0)
    agent_version: str = Field(min_lenth=1, max_length=64)
    quota_used_sec: int = Field(default=0, ge=0)

class HeartbeatResponse(BaseModel):
    server_time: datetime
    policy_version: int
    policy_update_available: bool
    commands: list[dict] = []



