from pydantic import BaseModel, EmailStr, Field, ConfigDict

class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class UserResponse(BaseModel):
    id: str
    email: EmailStr
    role: str

    model_config = {"from_attributes": True}

class ParentTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class ParentSessionResponse(BaseModel):
    authenticated: bool = True
    user: UserResponse
    csrf_token: str
