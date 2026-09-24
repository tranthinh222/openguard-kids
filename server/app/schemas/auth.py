from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: EmailStr
    role: str

    model_config = {"from_attributes": True}

class ParentTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
