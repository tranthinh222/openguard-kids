"""Regression tests for server source changes; no live deployment or evidence collection."""
import asyncio
import json
import sqlite3
import re
from contextlib import closing
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select, func
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.http_security import SecurityMiddleware
from app.core.security import utc_now, decode_access_token
from app.models.device import Device
from app.models.child import Child
from app.models.command import DeviceCommand
from app.models.request import ChildRequest
from app.models.activity import ActivityEvent
from app.services.maintenance import backup_database, verify_backup
from test_week02 import parent_headers, enrolled_device


def family(client):
    parent = parent_headers(client, 'week4@example.com')
    child, device = enrolled_device(client, parent)
    return parent, child, device, {'Authorization': 'Bearer ' + device['access_token']}


def test_request_limit_body_limit_and_security_headers():
    config = Settings(_env_file=None, rate_limit_enabled=True, auth_requests_per_minute=2, max_request_bytes=1024)
    app = FastAPI()
    app.add_middleware(SecurityMiddleware, config=config)
    @app.post('/api/v1/auth/token')
    def token():
        return {'ok': True}
    with TestClient(app) as client:
        assert client.post('/api/v1/auth/token').status_code == 200
        assert client.post('/api/v1/auth/token').status_code == 200
        limited = client.post('/api/v1/auth/token')
        assert limited.status_code == 429 and int(limited.headers['retry-after']) > 0
        assert limited.headers['cache-control'] == 'no-store'
        assert limited.headers['x-frame-options'] == 'DENY'
        assert limited.headers['x-request-id']
        assert client.post('/other', content=b'x' * 1025).status_code == 413


def test_chunked_request_limit_before_application():
    from types import SimpleNamespace
    calls = []
    async def app(*_):
        pytest.fail('Oversized body reached app')
    middleware = SecurityMiddleware(app, SimpleNamespace(rate_limit_enabled=False, max_request_bytes=5))
    messages = iter([{'type': 'http.request', 'body': b'123', 'more_body': True},
                     {'type': 'http.request', 'body': b'456', 'more_body': False}])
    async def receive(): return next(messages)
    async def send(message): calls.append(message)
    asyncio.run(middleware({'type': 'http', 'path': '/api/upload', 'headers': [], 'method': 'POST'}, receive, send))
    assert calls[0]['status'] == 413


def test_production_config_rejects_insecure_defaults():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment='production', jwt_secret='dev-only', policy_hmac_secret='dev-only')
    valid = Settings(_env_file=None, environment='production', jwt_secret='x' * 32,
                     policy_hmac_secret='y' * 32, web_cookie_secure=True, allowed_hosts=['example.com'])
    assert valid.web_cookie_secure


def test_jwt_requires_expiry_and_type():
    token = jwt.encode({'sub': 'test', 'type': 'device'}, settings.jwt_secret, algorithm='HS256')
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_cookie_enrollment_requires_csrf(client):
    credentials = {'email': 'csrf-week4@example.com', 'password': 'StrongPass123!'}
    assert client.post('/api/v1/auth/register', json=credentials).status_code == 201
    login = client.get('/login')
    csrf = re.search(r'data-login-csrf="([^"]+)"', login.text).group(1)
    session = client.post('/api/v1/auth/login', json=credentials, headers={'X-CSRF-Token': csrf}).json()
    header = {'X-CSRF-Token': session['csrf_token']}
    child = client.post('/api/v1/children', json={'display_name': 'Test'}, headers=header).json()['id']
    url = f'/api/v1/children/{child}/enrollment'
    assert client.post(url).status_code == 403
    assert client.post(url, headers=header).status_code == 201


def test_request_decision_is_one_transaction(client, db_session, monkeypatch):
    parent, child, device, auth = family(client)
    request = client.post('/api/v1/agent/requests', headers=auth, json={'requested_minutes': 15}).json()
    from app.services.request_service import decide_request
    original = __import__('app.services.request_service', fromlist=['create_command']).create_command
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Simulated crash before outer commit')
    monkeypatch.setattr('app.services.request_service.create_command', crash)
    with pytest.raises(RuntimeError):
        decide_request(db_session, request['id'], child, db_session.get(Child, child).parent_id, True, None)
    db_session.rollback()
    assert db_session.get(ChildRequest, request['id']).status == 'pending'
    assert db_session.scalar(select(func.count()).select_from(DeviceCommand)) == 0
    monkeypatch.setattr('app.services.request_service.create_command', original)
    url = f"/api/v1/children/{child}/requests/{request['id']}/approve"
    assert client.post(url, headers=parent, json={}).status_code == 200
    assert client.post(url, headers=parent, json={}).status_code == 409
    assert db_session.scalar(select(func.count()).select_from(DeviceCommand)) == 1


def test_revoked_device_cannot_ack_over_existing_socket(client, db_session):
    parent, child, device, auth = family(client)
    command = client.post(f"/api/v1/devices/{device['device_id']}/commands", headers=parent,
                          json={'type': 'LOCK_NOW'}).json()
    with client.websocket_connect('/api/v1/agent/ws', headers=auth) as socket:
        assert socket.receive_json()['command_id'] == command['id']
        record = db_session.get(Device, device['device_id'])
        record.revoked_at = utc_now()
        db_session.commit()
        socket.send_json({'type': 'ack', 'command_id': command['id'], 'status': 'completed'})
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_json()
        assert error.value.code == 4401
    assert db_session.get(DeviceCommand, command['id']).ack_at is None
    assert client.post(f"/api/v1/devices/{device['device_id']}/commands", headers=parent,
                       json={'type': 'LOCK_NOW'}).status_code == 409


def test_websocket_malformed_json_closes_cleanly(client):
    _, _, _, auth = family(client)
    with client.websocket_connect('/api/v1/agent/ws', headers=auth) as socket:
        socket.send_text('{invalid')
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_json()
        assert error.value.code == 1008


def test_naive_clock_and_coerced_command_rejected(client):
    parent, _, device, auth = family(client)
    response = client.post('/api/v1/agent/heartbeat', headers=auth, json={
        'policy_version': 1, 'agent_version': 'test', 'agent_wall_clock': '2026-10-14T12:00:00'})
    assert response.status_code == 422
    for body in ({'type': 'ADD_TIME', 'minutes': True}, {'type': 'UNLOCK', 'minutes': 15}):
        assert client.post(f"/api/v1/devices/{device['device_id']}/commands", headers=parent, json=body).status_code == 422


def test_unknown_recent_clock_uses_received_time(client, db_session):
    _, _, _, auth = family(client)
    client.post('/api/v1/agent/heartbeat', headers=auth, json={'policy_version': 1, 'agent_version': 'test'})
    identifier = str(uuid4())
    event = {'event_id': identifier, 'type': 'domain_query', 'subject': 'example.com',
             'ts': (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()}
    assert client.post('/api/v1/agent/events/batch', headers=auth, json={'events': [event]}).json()['accepted'] == [identifier]
    stored = db_session.get(ActivityEvent, identifier)
    assert not stored.clock_trusted and stored.effective_at == stored.received_at


def test_api_timestamps_include_utc(client):
    parent, child, device, auth = family(client)
    command = client.post(f"/api/v1/devices/{device['device_id']}/commands", headers=parent, json={'type': 'UNLOCK'}).json()
    request = client.post('/api/v1/agent/requests', headers=auth, json={}).json()
    for value in (command['created_at'], request['created_at']):
        assert datetime.fromisoformat(value).utcoffset() == timedelta(0)


def test_backup_includes_committed_wal_and_refuses_overwrite(tmp_path):
    source, backup = tmp_path / 'live.db', tmp_path / 'backup.db'
    with closing(sqlite3.connect(source)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE sample (value TEXT)')
        db.execute("INSERT INTO sample VALUES ('committed')")
        db.commit()
        backup_database('sqlite:///' + str(source), backup)
        with closing(sqlite3.connect(backup)) as copied:
            assert copied.execute('SELECT value FROM sample').fetchone() == ('committed',)
        with pytest.raises(FileExistsError):
            backup_database('sqlite:///' + str(source), backup)
    verify_backup(backup)


def test_retention_loop_retries_then_uses_normal_interval(monkeypatch):
    from app.services import retention
    calls, delays = [], []
    def cleanup():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError('Transient failure')
        return 0
    async def sleep(seconds):
        delays.append(seconds)
        if len(delays) == 2:
            raise asyncio.CancelledError()
    monkeypatch.setattr(retention, 'cleanup_once', cleanup)
    monkeypatch.setattr(retention.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(retention.retention_loop())
    assert delays == [settings.retention_retry_sec, settings.retention_interval_sec]
