from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

class EnrollmentCodeResponse(BaseModel):
    enrollment_id: str
    code: str
    expires_at: datetime

class EnrollmentStatusResponse(BaseModel):
    enrollment_id: str
    status: Literal["pending", "used", "expired"]


class AgentEnrollRequest(BaseModel):
    code: str = Field(min_length=8, max_length=8)
    device_name: str = Field(min_length=1, max_length=255)
    fingerprint: str = Field(min_length=8, max_length=2048)

class AgentEnrollResponse(BaseModel):
    device_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_in: int
