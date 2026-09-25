from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models.device import Device
from app.models.user import User

bearer_theme = HTTPBearer(auto_error=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _decode_bearer(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        return decode_access_token(credentials.credentials)
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

def get_current_parent(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_theme), 
        db: Session = Depends(get_db)
) -> User:
    payload = _decode_bearer(credentials)

    if payload.get("type") != "parent":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Parent token required")

    user = db.get(User, payload.get("sub"))
    if (
        user is None 
        or not user.is_active 
        or user.role != "parent"
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid parent account")

    return user

def get_current_device(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_theme), 
        db: Session = Depends(get_db)
) -> Device:
    payload = _decode_bearer(credentials)

    if payload.get("type") != "device":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device token required")

    device = db.get(Device, payload.get("sub"))
    if (
        device is None
        or device.status != "active"
        or device.revoked_at is not None
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked device")

    return device