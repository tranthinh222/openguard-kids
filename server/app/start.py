"""Single-worker deployment entry point; migration is an explicit operator step."""
import os
import uvicorn
from app.core.config import settings
from app.core.database import engine
from app.services.maintenance import schema_ready


def main():
    with engine.connect() as connection:
        if not schema_ready(connection):
            raise SystemExit('Database not ready. Run alembic upgrade head before startup.')
    uvicorn.run('app.main:app', host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '8000')),
                workers=1, reload=False, log_level=settings.log_level.lower(), access_log=False,
                proxy_headers=True, forwarded_allow_ips=os.getenv('FORWARDED_ALLOW_IPS', '127.0.0.1'),
                ws_max_size=settings.websocket_max_message_bytes, ws_max_queue=16,
                timeout_keep_alive=5, timeout_graceful_shutdown=20)


if __name__ == '__main__':
    main()
