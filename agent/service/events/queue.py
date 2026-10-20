"""Durable, privacy-minimal outbox. Retry keeps the original event ID and timestamp."""
import json
import sqlite3
import uuid
from datetime import timedelta
from service.content_rules import domain, process_name

TYPES = {'app_start', 'app_stop', 'domain_query', 'blocked_app', 'blocked_domain',
         'quota_warning', 'locked', 'unlock_request', 'override_granted'}
PERMANENT_ERRORS = {'invalid_event', 'identity_mismatch', 'invalid_policy',
                    'event_id_conflict', 'outside_retention'}


class EventQueue:
    def __init__(self, path, owner=''):
        self.path = path
        self.owner = owner
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    synced INTEGER NOT NULL DEFAULT 0, rejection TEXT, owner TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS events_pending ON events(synced, rejection);
                CREATE TABLE IF NOT EXISTS app_usage_daily (
                    date TEXT, subject TEXT, sha256 TEXT, duration_sec INTEGER NOT NULL, owner TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(date, subject, sha256, owner));
                CREATE TABLE IF NOT EXISTS content_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def emit(self, kind, now, subject=None, duration_sec=0, policy_id=None, sha256=None, event_id=None, connection=None):
        if kind not in TYPES or now.tzinfo is None:
            raise ValueError('Invalid event type or naive timestamp')
        if kind in {'app_start', 'app_stop', 'blocked_app'}:
            subject = process_name(subject)
        elif kind in {'domain_query', 'blocked_domain'}:
            subject = domain(subject)
        elif subject is not None:
            raise ValueError('Free-form event subject is prohibited')
        if type(duration_sec) is not int or not 0 <= duration_sec <= 86400 or (kind != 'app_stop' and duration_sec):
            raise ValueError('Invalid duration')
        identifier = str(uuid.UUID(event_id)) if event_id else str(uuid.uuid4())
        policy_id = str(uuid.UUID(policy_id)) if policy_id else None
        event = dict(event_id=identifier, ts=now.isoformat(), type=kind, subject=subject,
                     duration_sec=duration_sec, policy_id=policy_id)
        def insert(db):
            added = db.execute('INSERT OR IGNORE INTO events(event_id,payload,created_at,owner) VALUES(?,?,?,?)',
                              (identifier, json.dumps(event), now.isoformat(), self.owner)).rowcount
            if added and kind == 'app_stop' and duration_sec:
                db.execute('INSERT INTO app_usage_daily VALUES(?,?,?,?,?) ON CONFLICT(date,subject,sha256,owner) '
                           'DO UPDATE SET duration_sec=duration_sec+excluded.duration_sec',
                           (now.date().isoformat(), subject, sha256 or '', duration_sec, self.owner))
        if connection is not None:
            insert(connection)
        else:
            with self.connect() as db:
                insert(db)
        return identifier

    def pending(self, limit=100):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT payload FROM events WHERE owner=? AND synced=0 AND rejection IS NULL ORDER BY rowid LIMIT ?', (self.owner, limit))]

    def sync(self, post):
        batch = self.pending()
        if not batch:
            return 0
        reply = post('/api/v1/agent/events/batch', {'events': batch})
        if not isinstance(reply, dict) or not isinstance(reply.get('accepted'), list) or not isinstance(reply.get('rejected', []), list):
            raise ValueError('Invalid event ACK')
        submitted = {event['event_id'] for event in batch}
        accepted = {item for item in reply['accepted'] if isinstance(item, str)} & submitted
        with self.connect() as db:
            db.executemany('UPDATE events SET synced=1 WHERE event_id=?', [(item,) for item in accepted])
            for rejected in reply.get('rejected', []):
                index = rejected.get('index')
                if type(index) is int and 0 <= index < len(batch) and rejected.get('reason') in PERMANENT_ERRORS:
                    identifier = batch[index]['event_id']
                    if identifier not in accepted and rejected.get('event_id') in {None, identifier}:
                        db.execute('UPDATE events SET rejection=? WHERE event_id=?', (rejected['reason'], identifier))
        return len(accepted)

    def cache(self, key, payload):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO content_cache VALUES (?,?)', (self.owner + ':' + key, json.dumps(payload)))

    def cached(self, key):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM content_cache WHERE key=?', (self.owner + ':' + key,)).fetchone()
        return json.loads(row[0]) if row else None

    def recent(self, limit=100):
        with self.connect() as db:
            return [dict(json.loads(row[0]), synced=bool(row[1]), rejection=row[2]) for row in db.execute(
                'SELECT payload,synced,rejection FROM events WHERE owner=? ORDER BY rowid DESC LIMIT ?', (self.owner, limit))]

    def prune(self, now):
        cutoff = (now - timedelta(days=90)).isoformat()
        with self.connect() as db:
            db.execute('DELETE FROM events WHERE julianday(created_at)<julianday(?)', (cutoff,))
            db.execute('DELETE FROM app_usage_daily WHERE date<?', (cutoff[:10],))
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('usage_daily', 'warning_state', 'grace_state'):
                if table in tables:
                    db.execute(f'DELETE FROM {table} WHERE date<?', (cutoff[:10],))
            for table in ('security_events', 'clock_events'):
                if table in tables:
                    db.execute(f'DELETE FROM {table} WHERE julianday(created_at)<julianday(?)', (cutoff,))
            if 'policies' in tables:
                db.execute('DELETE FROM policies WHERE is_active=0 AND julianday(activated_at)<julianday(?)', (cutoff,))
            db.execute("DELETE FROM content_cache WHERE key LIKE '%:transparency' "
                       "AND json_extract(payload, '$.date') < ?", (cutoff[:10],))
