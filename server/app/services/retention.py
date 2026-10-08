import asyncio
import logging

from app.core.database import SessionLocal
from app.services.activity_service import cleanup_activity

LOGGER = logging.getLogger(__name__)


def cleanup_once():
    with SessionLocal() as db:
        return cleanup_activity(db)


async def retention_loop():
    while True:
        try:
            await asyncio.to_thread(cleanup_once)
        except Exception:
            LOGGER.exception("Activity retention cleanup failed; retrying in one hour")
            await asyncio.sleep(3600)
        else:
            await asyncio.sleep(86400)
