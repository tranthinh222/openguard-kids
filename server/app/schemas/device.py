from pydantic import BaseModel

class DeviceRefreshRequest(BaseModel):
    refresh_token: str

class DeviceAccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
