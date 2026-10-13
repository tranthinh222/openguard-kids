import asyncio
import logging
from datetime import timedelta

from app.core.database import SessionLocal
from app.services.activity_service import cleanup_activity
from app.core.config import settings
from app.core.security import utc_now
from app.models.web_session import WebSession
from app.models.token import DeviceRefreshToken
from app.models.enrollment import EnrollmentCode
from sqlalchemy import delete, or_

LOGGER = logging.getLogger(__name__)


def cleanup_once():
    with SessionLocal() as db:
        now = utc_now()
        for model in (WebSession, DeviceRefreshToken):
            db.execute(delete(model).where(or_(model.expires_at <= now, model.revoked_at.is_not(None))))
        # Keep final enrollment status briefly so dashboard polling can observe it.
        cutoff = now - timedelta(days=1)
        db.execute(delete(EnrollmentCode).where(or_(EnrollmentCode.expires_at <= cutoff, EnrollmentCode.used_at <= cutoff)))
        return cleanup_activity(db, now)


async def retention_loop():
    while True:
        try:
            await asyncio.to_thread(cleanup_once)
        except Exception:
            LOGGER.error('Retention cleanup failed; retry in %s seconds', settings.retention_retry_sec)
            await asyncio.sleep(settings.retention_retry_sec)
        else:
            await asyncio.sleep(settings.retention_interval_sec)
