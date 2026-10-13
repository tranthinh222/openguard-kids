"""Run from server/: python -m app.maintenance backup --output ../backups/server.db"""
import argparse
from app.core.config import settings
from app.services.maintenance import backup_database, verify_backup, schema_ready


def main():
    parser = argparse.ArgumentParser(description='OpenGuard server maintenance')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check')
    commands.add_parser('cleanup')
    backup = commands.add_parser('backup')
    backup.add_argument('--output', required=True)
    verify = commands.add_parser('verify-backup')
    verify.add_argument('path')
    args = parser.parse_args()
    if args.command == 'backup':
        backup_database(settings.database_url, args.output)
        print('Backup created and integrity checked')
    elif args.command == 'verify-backup':
        verify_backup(args.path)
        print('Backup integrity OK')
    elif args.command == 'cleanup':
        from app.services.retention import cleanup_once
        print(f'Expired activity rows removed: {cleanup_once()}')
    else:
        from app.core.database import engine
        with engine.connect() as connection:
            if not schema_ready(connection):
                parser.exit(1, 'Database migrations are not current; run alembic upgrade head\n')
        print('Database ready')


if __name__ == '__main__':
    main()
