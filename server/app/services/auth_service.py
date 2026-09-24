from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password, utc_now, verify_password
from app.models.user import User

def register_parent(db: Session, email: str, password: str) -> User:
    normalized_email = email.strip().lower()

    existing = db.scalar(select(User).where(User.email == normalized_email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        role="parent",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user

def login_parent(db: Session, email: str, password: str) -> tuple[str, int]:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    now = utc_now()
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1

        if user.failed_login_attempts >= settings.login_max_failed_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            user.failed_login_attempts = 0

        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    token = create_access_token(
        subject=user.id,
        token_type="parent",
        expires_minutes=settings.parent_access_token_expire_minutes,
    )

    return token, settings.parent_access_token_expire_minutes * 60
