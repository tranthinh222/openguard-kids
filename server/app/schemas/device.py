from datetime import datetime
from pydantic import BaseModel

class DeviceRefreshRequest(BaseModel):
    refresh_token: str

class DeviceAccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class ParentDeviceResponse(BaseModel):
    id: str
    child_id: str
    device_name: str
    status: str
    last_seen_at: datetime | None
    current_policy_version: int
    online: bool
