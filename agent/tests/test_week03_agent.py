import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import uuid4

import dns.message
import dns.rcode
import dns.rrset
import httpx
import pytest

from openguard_agent import AgentClient, AgentConfig, AgentState, StateStore
from service.apps.classifier import classify
from service.apps.hasher import ExecutableHasher
from service.apps.monitor import AppMonitor, Process
from service.commands.handler import CommandHandler, ProcessedCommandRepository
from service.dns.matcher import DomainMatcher
from service.dns.proxy import DNSProcessor, DNSProxy, event_domain
from service.dns.resolver import Resolver
from service.enforcement import WorkstationEnforcer
from service.events import EventQueue
from service.policy import PolicyManager, PolicyRepository, PolicyRejectedError
from service.policy.verifier import expected_signature
from service.realtime.websocket_client import WebSocketWorker
from service.screen_time import UsageRepository

NOW = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)


def envelope(version=1, **payload):
    payload = dict(screen_time={}, weekly_schedule=[True] * 336, apps=[], domains=[], **{}) | payload
    return dict(id=str(uuid4()), version=version, payload=payload, signature=expected_signature(payload, version, 'test'))


def test_policy_object_signature_and_concurrent_downgrade(tmp_path):
    manager = PolicyManager(PolicyRepository(tmp_path / 'a.db'), 'test')
    item = envelope(domains=dict(allow=[], block=['example.com'], blocked_categories=['games'], safe_search=True))
    assert manager.accept(item).payload == item['payload']
    old = manager.current
    manager.accept(envelope(2))
    with pytest.raises(PolicyRejectedError):
        manager.repository.activate(old)
    item['payload']['domains']['safe_search'] = False
    with pytest.raises(PolicyRejectedError):
        manager.accept(item)
    assert manager.current.version == 2


def test_hash_rename_priority_and_invalidation(tmp_path):
    file = tmp_path / 'renamed.exe'
    file.write_bytes(b'game')
    hasher = ExecutableHasher()
    sha = hasher.digest(file)
    assert hasher.digest(file) == sha and len(hasher.cache) == 1
    assert classify('renamed.exe', sha, [dict(name='game.exe', sha256=sha, action='block'),
                                       dict(name='renamed.exe', action='allow')]) == ('block', 'sha256')
    file.write_bytes(b'updated game')
    assert hasher.digest(file) != sha
    assert hasher.digest(tmp_path / 'missing.exe') is None


def test_app_start_stop_policy_update_pid_reuse_and_no_spam(tmp_path):
    queue = EventQueue(tmp_path / 'a.db')
    process = Process(111, 1, 'renamed.exe', 'private/path')
    current = [process]
    clock = [0]
    calls, notices = [], []
    policy = SimpleNamespace(policy_id=str(uuid4()), payload={'apps': []})
    monitor = AppMonitor(lambda: policy, queue.emit, notices.append, lambda: NOW + timedelta(seconds=clock[0]),
                         snapshot=lambda: current, hasher=SimpleNamespace(digest=lambda _: 'a' * 64),
                         enforcer=SimpleNamespace(terminate=lambda p: calls.append(p.pid) or True), monotonic=lambda: clock[0])
    monitor.tick()
    clock[0] = 65
    monitor.tick()
    policy.payload['apps'] = [dict(name='game.exe', sha256='a' * 64, action='block')]
    monitor.tick()
    monitor.tick()
    assert calls == [111]
    current.clear()
    clock[0] = 70
    monitor.tick()
    events = queue.pending()
    assert [e['type'] for e in events] == ['app_start', 'app_stop', 'blocked_app', 'app_stop']
    assert sum(e['duration_sec'] for e in events) == 70
    assert 'private' not in json.dumps(events) and 'sha256' not in json.dumps(events)
    current.append(Process(111, 2, 'renamed.exe', 'private/path'))
    monitor.tick()
    assert calls == [111, 111]


def test_midnight_app_segments(tmp_path):
    queue = EventQueue(tmp_path / 'a.db')
    start = NOW.replace(hour=23, minute=59, second=58)
    clock = [0]
    monitor = AppMonitor(lambda: None, queue.emit, lambda _: None, lambda: start + timedelta(seconds=clock[0]),
                         snapshot=lambda: [Process(1, 1, 'game.exe', '')],
                         hasher=SimpleNamespace(digest=lambda _: None), enforcer=SimpleNamespace(), monotonic=lambda: clock[0])
    monitor.tick()
    clock[0] = 5
    monitor.close()
    with queue.connect() as db:
        assert db.execute('SELECT date,duration_sec FROM app_usage_daily ORDER BY date').fetchall() == [
            ('2026-10-12', 2), ('2026-10-13', 3)]


def test_durable_queue_lost_ack_partial_rejection_and_unknown_ack(tmp_path):
    path = tmp_path / 'a.db'
    queue = EventQueue(path)
    first = queue.emit('app_start', NOW, subject='game.exe')
    second = queue.emit('locked', NOW)
    original = queue.pending()
    def lost(*_):
        raise httpx.ReadTimeout('ACK lost')
    with pytest.raises(httpx.ReadTimeout):
        queue.sync(lost)
    queue = EventQueue(path)
    assert queue.pending() == original
    queue.sync(lambda *_: dict(accepted=[first, str(uuid4())], rejected=[dict(index=1, event_id=second, reason='invalid_policy')]))
    assert queue.pending() == []
    assert queue.recent()[0]['rejection'] == 'invalid_policy'
    assert queue.recent()[1]['synced']


@pytest.mark.parametrize('subject', ['https://example.com/private?q=secret', 'C:\\Users\\private.exe', 'window title'])
def test_queue_rejects_private_subjects(tmp_path, subject):
    queue = EventQueue(tmp_path / 'a.db')
    with pytest.raises(ValueError):
        queue.emit('domain_query', NOW, subject=subject)
    with pytest.raises(ValueError):
        queue.emit('app_start', NOW, subject=subject)
    with pytest.raises(ValueError):
        queue.emit('locked', NOW, subject=subject)


def test_matcher_boundaries_allow_over_block_and_category():
    matcher = DomainMatcher({'domains': {'example.com': 'games'}})
    policy = SimpleNamespace(payload={'domains': dict(allow=['school.example.com'], block=['example.com'], blocked_categories=['games'])})
    assert matcher.decide('school.example.com', policy)[0] == 'allow'
    assert matcher.decide('www.example.com.', policy)[0] == 'block'
    assert matcher.decide('notexample.com', policy)[0] == 'allow'
    policy.payload['domains']['block'] = []
    assert matcher.decide('play.example.com', policy) == ('block', 'games')
    assert event_domain('secret.www.youtube.com') == 'youtube.com'
    assert event_domain('secret.school.edu.vn') == 'school.edu.vn'


class FakeResolver:
    def __init__(self):
        self.queries = []

    def resolve(self, query):
        self.queries.append(query.question[0].name.to_text())
        response = dns.message.make_response(query)
        if query.question[0].rdtype == 1:
            response.answer.append(dns.rrset.from_text(query.question[0].name, 60, 'IN', 'A', '192.0.2.10'))
        return response


def processor(tmp_path):
    queue, resolver, notices = EventQueue(tmp_path / 'a.db'), FakeResolver(), []
    policy = SimpleNamespace(policy_id=str(uuid4()), version=1, payload={'domains': dict(block=['example.com'], safe_search=True)})
    return DNSProcessor(lambda: policy, DomainMatcher(), resolver, queue.emit, notices.append, lambda: NOW), queue, resolver, notices


def test_dns_block_safesearch_privacy_dedup_and_failure(tmp_path):
    proxy, queue, resolver, notices = processor(tmp_path)
    ask = lambda host, kind='A': dns.message.from_wire(proxy.handle(dns.message.make_query(host, kind).to_wire()))
    assert ask('private.example.com').rcode() == dns.rcode.NXDOMAIN
    assert ask('private.example.com').rcode() == dns.rcode.NXDOMAIN
    assert not resolver.queries
    assert len(queue.pending()) == len(notices) == 1
    assert queue.pending()[0]['subject'] == 'example.com'
    response = ask('www.google.com')
    assert 'forcesafesearch.google.com.' in resolver.queries
    assert response.answer[0].rdtype == 5
    assert not ask('www.google.com', 'HTTPS').answer
    ask('google.com.attacker.test')
    assert resolver.queries[-1] == 'google.com.attacker.test.'
    assert proxy.handle(b'invalid') is None
    with pytest.raises(ValueError):
        Resolver('127.0.0.1')


def test_dns_udp_tcp_loopback_high_port(tmp_path):
    import dns.query
    handler, *_ = processor(tmp_path)
    proxy = DNSProxy(handler, port=0)
    proxy.start()
    try:
        query = dns.message.make_query('example.com', 'AAAA')
        assert dns.query.udp(query, '127.0.0.1', port=proxy.port, timeout=2).rcode() == dns.rcode.NXDOMAIN
        assert dns.query.tcp(query, '127.0.0.1', port=proxy.port, timeout=2).rcode() == dns.rcode.NXDOMAIN
    finally:
        proxy.stop()


def test_concurrent_add_time_once_and_atomic_outbox(tmp_path):
    path = tmp_path / 'a.db'
    queue = EventQueue(path)
    usage = UsageRepository(path)
    handlers = [CommandHandler(ProcessedCommandRepository(path), usage, WorkstationEnforcer(lock=lambda: True),
                              today=NOW.date, event_queue=queue, event_now=lambda: NOW, policy_id=lambda: None) for _ in range(2)]
    command = dict(command_id=str(uuid4()), type='ADD_TIME', payload={'minutes': 15})
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda handler: handler.handle(command), handlers))
    assert sum(result.duplicate for result in results) == 1
    assert usage.get(NOW.date()).bonus_seconds == 900
    assert [e['type'] for e in queue.pending()] == ['override_granted']


def test_websocket_policy_notification_has_no_command_ack():
    received, acks = [], []
    handler = SimpleNamespace(handle=lambda _: pytest.fail('Policy must not reach command handler'))
    worker = None
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def recv(self, **_):
            worker._stop.set()
            return json.dumps(dict(type='POLICY_UPDATED', payload={'version': 2}))
        def send(self, value): acks.append(value)
    worker = WebSocketWorker('http://test', lambda: 'token', handler, connector=lambda *a, **kw: Socket(), on_policy=received.append)
    worker._run()
    assert received == [{'version': 2}] and acks == []


def test_push_persists_and_heartbeat_sends_quota_date(tmp_path):
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=dict(server_time=NOW.isoformat(), policy_version=1, commands=[], policy_update_available=False))
    config = AgentConfig('http://test', tmp_path / 'state.json', policy_hmac_secret='test')
    store = StateStore(config.state_path)
    store.save(AgentState(device_id='d', access_token='a', refresh_token='r'))
    client = AgentClient(config, store, httpx.MockTransport(transport))
    try:
        client.clock_monitor.synchronize(NOW)
        client.accept_policy(envelope())
        client.heartbeat()
        body = json.loads(requests[-1].content)
        assert body['policy_version'] == store.load().policy_version == 1
        assert body['quota_date'] == client.clock_monitor.trusted_now().date().isoformat()
    finally:
        client.close()


def test_queue_isolation_after_device_reenrollment(tmp_path):
    path = tmp_path / 'a.db'
    old = EventQueue(path, 'old-device')
    old.emit('locked', NOW)
    old.cache('transparency', {'private': 'old child'})
    new = EventQueue(path, 'new-device')
    assert new.pending() == new.recent() == []
    assert new.cached('transparency') is None
    assert len(old.pending()) == 1


def test_add_time_rolls_back_if_event_cannot_be_persisted(tmp_path):
    path = tmp_path / 'a.db'
    queue = EventQueue(path)
    usage = UsageRepository(path)
    handler = CommandHandler(ProcessedCommandRepository(path), usage, WorkstationEnforcer(lock=lambda: True),
                             today=NOW.date, event_queue=queue, event_now=lambda: NOW,
                             policy_id=lambda: 'invalid-uuid')
    result = handler.handle(dict(command_id='test-atomic', type='ADD_TIME', payload={'minutes': 15}))
    assert result.status == 'failed'
    assert usage.get(NOW.date()).bonus_seconds == 0 and queue.pending() == []


def test_runtime_lease_prevents_two_monitors(tmp_path):
    from service.runtime_lock import RuntimeLock
    with RuntimeLock(tmp_path / 'a.db'):
        with pytest.raises(RuntimeError):
            RuntimeLock(tmp_path / 'a.db')
    RuntimeLock(tmp_path / 'a.db').close()


def test_dns_tcp_bind_failure_releases_udp_and_reports_transport(monkeypatch):
    import errno
    from service.dns import proxy as module
    closed = []
    udp = SimpleNamespace(server_address=('127.0.0.1', 15353), server_close=lambda: closed.append(True))
    monkeypatch.setattr(module, 'UDPServer', lambda *_: udp)
    def fail(*_):
        raise OSError(errno.EADDRINUSE, 'address in use')
    monkeypatch.setattr(module, 'TCPServer', fail)
    proxy = module.DNSProxy(None, 15353)
    with pytest.raises(module.DNSBindError) as error:
        proxy.start()
    assert closed == [True] and proxy.servers == []
    assert error.value.protocol == 'TCP'
    assert '15353' in str(error.value) and 'ứng dụng khác' in str(error.value)


def test_dns_windows_access_denied_message():
    from service.dns.proxy import DNSBindError
    error = DNSBindError('UDP', 5353, OSError(10013, 'permission denied'))
    assert 'UDP' in str(error) and '5353' in str(error) and '10013' in str(error)
    assert '15353' in str(error) and 'độc quyền' in str(error)


def test_transparency_offline_cache_and_privacy():
    from transparency_ui import sections
    result = sections(dict(source='offline', data={'date': '2026-10-11', 'data': {}},
                           local=[dict(type='blocked_domain', subject='example.com', ts=NOW.isoformat(),
                                       duration_sec=0, synced=False, rejection=None)]), None)
    assert '2026-10-11' in result['Hôm nay']
    assert 'đang chờ đồng bộ' in result['Hoạt động / chặn']
    assert 'URL đầy đủ' in result['Quyền riêng tư']
    assert 'chưa có dữ liệu' in result['Hôm nay']
