"""SQLite backup and schema readiness helpers; no live database reset operations."""
from pathlib import Path
import sqlite3
from contextlib import closing
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def schema_ready(connection):
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    actual = set(MigrationContext.configure(connection).get_current_heads())
    return actual == expected


def sqlite_file(url):
    parsed = make_url(url)
    if parsed.get_backend_name() != 'sqlite' or not parsed.database or parsed.database == ':memory:':
        raise ValueError('Backup requires a file-backed SQLite database')
    return Path(parsed.database).resolve()


def verify_backup(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite integrity check failed')


def backup_database(url, destination):
    source, destination = sqlite_file(url), Path(destination).resolve()
    if not source.is_file() or destination == source or destination.is_relative_to(ROOT / 'dashboard'):
        raise ValueError('Choose an existing database and a separate non-public backup location')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: never overwrite an existing backup or follow its symlink.
    with destination.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
        verify_backup(destination)
        destination.chmod(0o600)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination
