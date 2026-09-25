import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_secret, utc_now
from app.models.user import User
from app.models.web_session import WebSession

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value

    return value.astimezone(timezone.utc).replace(tzinfo=None)

def create_web_session(db: Session, user: User) -> tuple[str, WebSession]:
    raw_token = secrets.token_urlsafe(48)
    session = WebSession(
        user_id=user.id,
        token_hash=hash_secret(raw_token),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=utc_now() + timedelta(hours=settings.web_session_expire_hours),
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    return raw_token, session

def get_web_session(db: Session, raw_token: str | None) -> WebSession | None:
    if not raw_token:
        return None

    session = db.scalar(
        select(WebSession).where(WebSession.token_hash == hash_secret(raw_token))
    )

    if session is None or session.revoked_at is not None:
        return None

    if _as_utc(session.expires_at) <= utc_now():
        return None

    return session

def revoke_web_session(db: Session, session: WebSession) -> None:
    session.revoked_at = utc_now()
    db.commit()
