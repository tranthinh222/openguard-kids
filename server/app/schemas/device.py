from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def as_utc(value: datetime) -> datetime:
    # SQLite stores UTC timestamps without timezone information.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


UTCDateTime = Annotated[datetime, AfterValidator(as_utc)]

class DeviceRefreshRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    refresh_token: str = Field(min_length=1, max_length=256)

class DeviceAccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class ParentDeviceResponse(BaseModel):
    id: str
    child_id: str
    device_name: str
    status: str
    last_seen_at: UTCDateTime | None
    current_policy_version: int
    quota_used_sec: int = 0
    clock_drift_sec: float | None = None
    online: bool
