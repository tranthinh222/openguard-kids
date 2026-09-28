from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.core.web_security import LOGIN_CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, verify_login_csrf
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    ParentSessionResponse,
    ParentTokenResponse,
    RegisterRequest,
    UserResponse,
)

from app.services.auth_service import authenticate_parent, login_parent, register_parent
from app.services.web_session_service import create_web_session, get_web_session, revoke_web_session

router = APIRouter()

def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        secure=settings.web_cookie_secure,
        samesite="lax",
        max_age=settings.web_session_expire_hours * 3600,
        path="/",
    )

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    return register_parent(db, payload.email, payload.password)

@router.post("/login", response_model=ParentSessionResponse)
def login_dashboard(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Create the browser dashboard session.

    The browser calls this endpoint with JSON. The opaque session token is set
    only as an HttpOnly cookie; it is never returned to JavaScript.
    """
    verify_login_csrf(request)
    user = authenticate_parent(db, payload.email, payload.password)
    raw_token, web_session = create_web_session(db, user)

    _set_session_cookie(response, raw_token)
    response.delete_cookie(LOGIN_CSRF_COOKIE_NAME, path="/")

    return ParentSessionResponse(
        user=UserResponse.model_validate(user),
        csrf_token=web_session.csrf_token,
    )

@router.post("/token", response_model=ParentTokenResponse)
def login_for_token(payload: LoginRequest, db: Session = Depends(get_db)):
    """Programmatic login for Swagger/Postman/CLI clients."""
    token, expires_in = login_parent(db, payload.email, payload.password)
    return ParentTokenResponse(access_token=token, expires_in=expires_in)

@router.get("/session", response_model=ParentSessionResponse)
def current_dashboard_session(
    request: Request,
    db: Session = Depends(get_db),
):
    web_session = get_web_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    if web_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    user = db.get(User, web_session.user_id)
    if user is None or not user.is_active or user.role != "parent":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid parent account")

    return ParentSessionResponse(
        user=UserResponse.model_validate(user),
        csrf_token=web_session.csrf_token,
    )

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_dashboard(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    web_session = get_web_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    if web_session is not None:
        supplied_csrf = request.headers.get("X-CSRF-Token", "")
        if supplied_csrf != web_session.csrf_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
        
        revoke_web_session(db, web_session)

    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
