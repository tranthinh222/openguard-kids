import pytest
from service.enforcement import WorkstationEnforcer, EnforcementReason
from openguard_agent import AgentConfig


@pytest.mark.parametrize('reason', list(EnforcementReason))
def test_relock_interval_after_login_is_not_extended_by_ticks(reason):
    mono, calls, events = [0.0], [], []
    enforcer = WorkstationEnforcer(lock=lambda: calls.append(mono[0]) or True,
                                  monotonic=lambda: mono[0], on_locked=lambda: events.append('locked'))
    assert enforcer.enforce(reason)
    enforcer.session_is_locked()
    mono[0] = 100
    enforcer.observe_session(True)
    for value in (100, 101, 104.9):
        mono[0] = value
        enforcer.observe_session(True)
        assert enforcer.enforce(reason, force=True)
    assert calls == [0] and events == ['locked']
    mono[0] = 105
    enforcer.enforce(reason)
    assert calls == [0, 105] and len(events) == 2


def test_shared_clients_cannot_bypass_cooldown(tmp_path):
    mono, calls = [0.0], []
    def make():
        return WorkstationEnforcer(lock=lambda: calls.append(mono[0]) or True, monotonic=lambda: mono[0],
                                   relock_delay_sec=10, state_key=tmp_path / 'agent.db')
    first, second = make(), make()
    first.enforce(EnforcementReason.REMOTE_LOCK)
    first.session_is_locked()
    mono[0] = 50
    first.observe_session(True)
    second.enforce(EnforcementReason.REMOTE_LOCK, force=True)
    mono[0] = 60
    second.enforce(EnforcementReason.REMOTE_LOCK)
    assert calls == [0, 60]


def test_zero_delay_preserves_immediate_relock():
    calls = []
    enforcer = WorkstationEnforcer(lock=lambda: calls.append(True) or True, relock_delay_sec=0)
    enforcer.enforce(EnforcementReason.REMOTE_LOCK)
    enforcer.session_is_locked()
    enforcer.observe_session(True)
    enforcer.enforce(EnforcementReason.REMOTE_LOCK)
    assert len(calls) == 2


def test_env_default_and_custom(monkeypatch):
    monkeypatch.delenv('OGK_RELOCK_DELAY_SEC', raising=False)
    assert AgentConfig.from_env().relock_delay_sec == 5
    monkeypatch.setenv('OGK_RELOCK_DELAY_SEC', '7.5')
    assert AgentConfig.from_env().relock_delay_sec == 7.5


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'abc'])
def test_invalid_env_rejected(monkeypatch, value):
    monkeypatch.setenv('OGK_RELOCK_DELAY_SEC', value)
    with pytest.raises(ValueError):
        AgentConfig.from_env()


def test_countdown_follows_actual_deadline_and_stops_when_restriction_removed(tmp_path):
    from service.screen_time.counter import ScreenTimeCounter, UsageRepository
    mono, unlocked, restricted = [0.0], [True], [True]
    events, locks = [], []
    enforcer = WorkstationEnforcer(lock=lambda: locks.append(mono[0]) or True, monotonic=lambda: mono[0])
    counter = ScreenTimeCounter(UsageRepository(tmp_path / 'usage.db'), lambda: None,
                                lambda _: True, lambda: unlocked[0], lambda: False,
                                monotonic=lambda: mono[0], enforcer=enforcer,
                                remote_locked=lambda: restricted[0], on_event=events.append)
    counter.tick()  # First lock: no countdown.
    assert events == [] and locks == [0]
    unlocked[0] = False
    counter.tick()
    mono[0], unlocked[0] = 100, True
    counter.tick()
    counter.tick()
    assert len(events) == 1
    assert events[0] == dict(type='RELOCK_COUNTDOWN', seconds_remaining=5, started=True, reason='remote_lock')
    mono[0] = 101
    counter.tick()
    assert events[-1]['seconds_remaining'] == 4 and not events[-1]['started']
    restricted[0] = False
    counter.tick()
    assert events[-1] == dict(type='RELOCK_COUNTDOWN_ENDED', restriction_active=False)
    mono[0] = 110
    counter.tick()
    assert locks == [0]


def test_countdown_ends_on_relock_and_restarts_next_login(tmp_path):
    from service.screen_time.counter import ScreenTimeCounter, UsageRepository
    mono, unlocked, events = [0.0], [True], []
    enforcer = WorkstationEnforcer(lock=lambda: True, monotonic=lambda: mono[0])
    counter = ScreenTimeCounter(UsageRepository(tmp_path / 'usage.db'), lambda: None,
                                lambda _: True, lambda: unlocked[0], lambda: False,
                                monotonic=lambda: mono[0], enforcer=enforcer,
                                remote_locked=lambda: True, on_event=events.append)
    counter.tick()
    for start in (100, 200):
        unlocked[0] = False
        counter.tick()
        mono[0], unlocked[0] = start, True
        counter.tick()
        assert events[-1]['started'] and events[-1]['seconds_remaining'] == 5
        mono[0] = start + 5
        counter.tick()
        assert events[-1] == dict(type='RELOCK_COUNTDOWN_ENDED', restriction_active=True)


def test_countdown_ui_uses_one_tray_popup_and_updates_banner():
    import queue
    from types import SimpleNamespace
    from unittest.mock import Mock
    from agent_gui import AgentWindow
    messages = queue.Queue()
    for event in [dict(type='RELOCK_COUNTDOWN', seconds_remaining=5, started=True),
                  dict(type='RELOCK_COUNTDOWN', seconds_remaining=4, started=False),
                  dict(type='RELOCK_COUNTDOWN_ENDED', restriction_active=False)]:
        messages.put(('protection', event))
    window = SimpleNamespace(events=messages, tray=Mock(), root=Mock(), _show_banner=Mock(), _process_events=Mock())
    AgentWindow._process_events(window)
    assert window.tray.notify.call_count == 1
    assert '5 giây' in window.tray.notify.call_args.args[0]
    assert '4 giây' in window._show_banner.call_args_list[1].args[0]
    window.tray.clear_notification.assert_called_once()
