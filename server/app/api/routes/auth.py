from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.auth import (
    LoginRequest,
    ParentTokenResponse,
    RegisterRequest,
    UserResponse,
)

from app.services.auth_service import login_parent, register_parent

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    return register_parent(db, payload.email, payload.password)

@router.post("/login", response_model=ParentTokenResponse, status_code=status.HTTP_200_OK)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> tuple[str, int]:
    token, expires_in = login_parent(db, payload.email, payload.password)

    return ParentTokenResponse(
        access_token=token,
        expires_in=expires_in,
    )
