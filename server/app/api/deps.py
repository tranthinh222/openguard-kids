from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.core.web_security import CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.models.device import Device
from app.models.user import User
from app.models.web_session import WebSession
from app.services.web_session_service import get_web_session


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class ParentAuthContext:
    user: User
    method: Literal["bearer", "session"]
    session: WebSession | None = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _decode_bearer(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    try:
        return decode_access_token(credentials.credentials)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

def get_parent_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ParentAuthContext:
    # Programmatic clients may authenticate with a Bearer token.
    if credentials is not None:
        payload = _decode_bearer(credentials)
        if payload.get("type") != "parent":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Parent token required"
            )

        user = db.get(User, payload.get("sub"))
        if user is None or not user.is_active or user.role != "parent":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid parent account"
            )
        
        return ParentAuthContext(user=user, method="bearer")

    # The dashboard authenticates with an opaque HttpOnly session cookie.
    session = get_web_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Authentication required"
        )

    user = db.get(User, session.user_id)
    if user is None or not user.is_active or user.role != "parent":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid parent account"
        )

    return ParentAuthContext(
        user=user, 
        method="session", 
        session=session
    )


def get_current_parent(
    auth: ParentAuthContext = Depends(get_parent_auth_context),
) -> User:
    return auth.user


def get_current_parent_for_write(
    request: Request,
    auth: ParentAuthContext = Depends(get_parent_auth_context),
) -> User:
    # Bearer requests are not vulnerable to browser cookie CSRF. Cookie-backed
    # dashboard requests must send the per-session CSRF token explicitly.
    if auth.method == "session":
        supplied = request.headers.get(CSRF_HEADER_NAME, "")
        if auth.session is None or supplied != auth.session.csrf_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Invalid CSRF token"
            )
    return auth.user


def get_current_device(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Device:
    payload = _decode_bearer(credentials)

    if payload.get("type") != "device":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Device token required"
        )

    device = db.get(Device, payload.get("sub"))
    if device is None or device.status != "active" or device.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid or revoked device"
        )

    return device
