"""Local erasure runs only after protection/IPC workers stop using the database."""
import sqlite3
import httpx
from service.tls import tls_context

PRIVATE_TABLES = (
    "events", "app_usage_daily", "content_cache", "usage_daily", "warning_state",
    "grace_state", "remote_lock", "policies", "security_events", "clock_events",
    "clock_anchor", "processed_commands",
)


def check(config, refresh_token, acknowledge=False, transport=None):
    with httpx.Client(base_url=config.server_url, timeout=config.request_timeout_sec, trust_env=False,
                      verify=tls_context(config.server_url, config.verify_tls,
                                         config.tls_cert_sha256, config.tls_ca_file), transport=transport) as client:
        result = client.post("/api/v1/agent/erasure", json={
            "refresh_token": refresh_token, "acknowledge": acknowledge})
        result.raise_for_status()
        return result.json()


def erase_database(path):
    with sqlite3.connect(path, timeout=10) as db:
        db.execute("PRAGMA secure_delete=ON")
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in PRIVATE_TABLES:
            if table in names:
                db.execute(f'DELETE FROM "{table}"')
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("VACUUM")
    # DNS/browser restore backups are operational state, not child activity;
    # retain them if OS restoration failed, so an administrator can retry.
