from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.core.config import settings
from app.models.base import Base
from app.services.maintenance import schema_ready


def test_week03_migration_upgrade_downgrade_preserves_existing_tables(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    monkeypatch.setattr(settings, "database_url", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    command.upgrade(config, "c8d1f2a7b901")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users(id,email,password_hash,role,is_active,failed_login_attempts,created_at,updated_at)"
                                " VALUES('parent-old','old@example.com','hash','parent',1,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO children(id,parent_id,display_name,birth_year,created_at,updated_at)"
                                " VALUES('child-old','parent-old','Legacy Child',2018,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO devices(id,child_id,device_name,fingerprint_hash,status,current_policy_version,quota_used_sec,created_at,updated_at)"
                                " VALUES('device-old','child-old','Legacy Laptop','hash','active',0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    with engine.connect() as connection:
        assert not schema_ready(connection)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == "f420_privacy"
        assert schema_ready(connection)
        assert connection.scalar(text("SELECT display_name FROM children WHERE id='child-old'")).startswith("ogk:gcm:v1:")
        assert connection.scalar(text("SELECT device_name FROM devices WHERE id='device-old'")).startswith("ogk:gcm:v1:")
        names = inspect(connection).get_table_names()
        assert {"activity_events", "screen_usage_daily", "policy_audits", "users", "policies"} <= set(names)
        diffs = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert not diffs
    command.downgrade(config, "c8d1f2a7b901")
    with engine.connect() as connection:
        names = inspect(connection).get_table_names()
        assert "activity_events" not in names and "policies" in names
        assert connection.scalar(text("SELECT display_name FROM children WHERE id='child-old'")) == "Legacy Child"
        assert connection.scalar(text("SELECT device_name FROM devices WHERE id='device-old'")) == "Legacy Laptop"
    command.upgrade(config, "head")
    engine.dispose()
