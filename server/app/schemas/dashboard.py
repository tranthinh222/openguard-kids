from pydantic import BaseModel

from app.schemas.device import UTCDateTime

class DashboardDeviceResponse(BaseModel):
    id: str
    child_id: str
    child_name: str
    device_name: str
    last_seen_at: UTCDateTime | None
    current_policy_version: int
    online: bool

class DashboardSummaryResponse(BaseModel):
    children_count: int
    device_count: int
    online_count: int
    offline_count: int
    recent_devices: list[DashboardDeviceResponse]
