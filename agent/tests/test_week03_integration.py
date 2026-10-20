"""A–D against the real server API, isolated DB and fake OS/upstream boundaries."""
import sys
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace

import dns.message
import dns.rcode
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))

from app.main import app
from app.api.deps import get_db
from app.models.base import Base
from app.core.config import settings
from openguard_agent import AgentClient, AgentConfig, StateStore
from service.apps.monitor import AppMonitor, Process
from service.dns.matcher import DomainMatcher
from service.dns.proxy import DNSProcessor
from test_week03_agent import FakeResolver


def test_scenarios_app_domain_offline_retry_and_transparency(tmp_path):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    def database():
        yield session
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    # No lifespan: never start the production database/cleanup scheduler in this test.
    server = TestClient(app)
    client = None
    try:
        credentials = {'email': 'agent-integration@example.com', 'password': 'StrongPass123!'}
        assert server.post('/api/v1/auth/register', json=credentials).status_code == 201
        token = server.post('/api/v1/auth/token', json=credentials).json()['access_token']
        parent = {'Authorization': 'Bearer ' + token}
        child = server.post('/api/v1/children', headers=parent, json={'display_name': 'Demo'}).json()['id']
        code = server.post(f'/api/v1/children/{child}/enrollment', headers=parent,
                           json={"consent": True, "privacy_notice_version": "2026-10-20-v1"}).json()['code']
        mode = ['online']
        def transport(request):
            if mode[0] == 'offline':
                raise httpx.ConnectError('Offline')
            response = server.request(request.method, request.url.raw_path.decode(), content=request.content,
                                      headers=dict(request.headers))
            if mode[0] == 'lost_ack' and request.url.path.endswith('/events/batch'):
                raise httpx.ReadTimeout('Server committed, ACK lost')
            return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
        config = AgentConfig('http://testserver', tmp_path / 'state.json', policy_hmac_secret=settings.policy_hmac_secret)
        client = AgentClient(config, StateStore(config.state_path), httpx.MockTransport(transport))
        client.enroll(code)
        policy_url = f'/api/v1/children/{child}/policy'
        payload = server.get(policy_url, headers=parent).json()['payload']
        payload['apps'] = [{'name': 'game.exe', 'sha256': 'a' * 64, 'action': 'block'}]
        payload['domains'] = dict(allow=[], block=['example.com'], blocked_categories=['games'], safe_search=True)
        assert server.put(policy_url, headers=parent, json={'payload': payload}).status_code == 200
        client.heartbeat()  # Real server signature + policy parser + trusted anchor.
        policy = lambda: client.policy_manager.current
        assert policy().version == 2

        terminated, notices, mono = [], [], [0]
        start = client.clock_monitor.trusted_now() - timedelta(seconds=40)
        snapshot = [Process(999999, 1, 'renamed.exe', 'private.exe')]
        monitor = AppMonitor(policy, client.events.emit, notices.append, lambda: start + timedelta(seconds=mono[0]),
                             snapshot=lambda: snapshot, hasher=SimpleNamespace(digest=lambda _: 'a' * 64),
                             enforcer=SimpleNamespace(terminate=lambda process: terminated.append(process.pid) or True),
                             monotonic=lambda: mono[0])
        monitor.tick()
        mono[0] = 40
        snapshot.clear()
        monitor.tick()
        assert terminated == [999999]
        processor = DNSProcessor(policy, DomainMatcher(), FakeResolver(), client.events.emit, notices.append,
                                 client.clock_monitor.trusted_now)
        query = dns.message.make_query('secret.example.com', 'A')
        reply = dns.message.from_wire(processor.handle(query.to_wire()))
        assert reply.rcode() == dns.rcode.NXDOMAIN

        pending = client.events.pending()
        mode[0] = 'offline'
        try:
            client.events.sync(client._authorized_post)
        except httpx.ConnectError:
            pass
        assert client.events.pending() == pending
        mode[0] = 'lost_ack'
        try:
            client.events.sync(client._authorized_post)
        except httpx.ReadTimeout:
            pass
        assert client.events.pending() == pending
        mode[0] = 'online'
        assert client.events.sync(client._authorized_post) == len(pending)
        assert not client.events.pending()

        day = client.clock_monitor.trusted_now().date()
        client.usage_repository.add_usage(day, 40)
        client.heartbeat()
        view = client.authorized_get(f'/api/v1/agent/transparency?start={day}&end={day}')
        report = server.get(f'/api/v1/children/{child}/reports/summary?start={day}&end={day}', headers=parent).json()
        assert view['summary'] == report
        assert report['blocked_count'] == 2
        assert report['app_duration_sec'] == 40
        assert report['screen_time_sec'] == 40
        assert report['top_apps'][0]['subject'] == 'renamed.exe'
        assert view['audit'][0]['new_version'] == 2
        assert view['privacy']['retention_days'] == 90
        assert {item['subject'] for item in view['activity']} == {'renamed.exe', 'example.com'}
    finally:
        if client:
            client.close()
        server.close()
        session.close()
        engine.dispose()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
