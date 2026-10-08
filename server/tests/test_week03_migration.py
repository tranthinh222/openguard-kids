from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.core.config import settings
from app.models.base import Base


def test_week03_migration_upgrade_downgrade_preserves_existing_tables(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    monkeypatch.setattr(settings, "database_url", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    command.upgrade(config, "c8d1f2a7b901")
    engine = create_engine(url)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == "e31008a1"
        names = inspect(connection).get_table_names()
        assert {"activity_events", "screen_usage_daily", "policy_audits", "users", "policies"} <= set(names)
        diffs = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert not diffs
    command.downgrade(config, "c8d1f2a7b901")
    with engine.connect() as connection:
        names = inspect(connection).get_table_names()
        assert "activity_events" not in names and "policies" in names
    command.upgrade(config, "head")
    engine.dispose()
