from datetime import date

from service.commands import CommandHandler, ProcessedCommandRepository
from service.enforcement import EnforcementReason, WorkstationEnforcer
from service.screen_time.counter import UsageRepository


def make_handler(tmp_path, lock=lambda: True):
    path = tmp_path / "agent.db"
    usage = UsageRepository(path)
    enforcer = WorkstationEnforcer(lock=lock)
    handler = CommandHandler(ProcessedCommandRepository(path), usage, enforcer, today=lambda: date(2026, 10, 5))
    return handler, usage, enforcer


def test_add_time_is_idempotent(tmp_path):
    handler, usage, _ = make_handler(tmp_path)
    command = {"command_id": "c1", "type": "ADD_TIME", "payload": {"minutes": 15}}
    assert handler.handle(command).status == "completed"
    assert handler.handle(command).duplicate is True
    assert usage.get(date(2026, 10, 5)).bonus_seconds == 900


def test_lock_now_and_unlock_use_enforcer(tmp_path):
    calls = []
    handler, _, enforcer = make_handler(tmp_path, lambda: calls.append(True) or True)
    assert handler.handle({"command_id": "c1", "type": "LOCK_NOW", "payload": {}}).status == "completed"
    assert enforcer.last_reason == EnforcementReason.REMOTE_LOCK
    assert calls == [True]
    assert handler.handle({"command_id": "c2", "type": "UNLOCK", "payload": {}}).status == "completed"
    assert enforcer.last_reason is None


def test_failed_lock_returns_failed_result(tmp_path):
    handler, _, _ = make_handler(tmp_path, lambda: False)
    result = handler.handle({"command_id": "c1", "type": "LOCK_NOW", "payload": {}})
    assert result.status == "failed"
    assert "LockWorkStation" in result.error


def test_time_added_and_rejection_notify_once(tmp_path):
    events = []
    path = tmp_path / "agent.db"
    handler = CommandHandler(
        ProcessedCommandRepository(path), UsageRepository(path), WorkstationEnforcer(lock=lambda: True),
        today=lambda: date(2026, 10, 5), on_event=events.append,
    )
    approved = {"command_id": "c1", "type": "ADD_TIME", "payload": {"minutes": 15, "request_id": "r1"}}
    rejected = {"command_id": "c2", "type": "REQUEST_REJECTED", "payload": {"request_id": "r2", "response": "Mai nhé"}}
    assert handler.handle(approved).status == "completed"
    assert handler.handle(approved).duplicate is True
    assert handler.handle(rejected).status == "completed"
    assert events == [
        {"type": "TIME_ADDED", "minutes": 15, "requested": True},
        {"type": "REQUEST_REJECTED", "response": "Mai nhé"},
    ]
