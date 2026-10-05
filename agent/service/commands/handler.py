"""Idempotent processing for remote device commands."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from service.enforcement import EnforcementReason, WorkstationEnforcer
from service.screen_time.counter import UsageRepository


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    status: str
    error: str | None = None
    duplicate: bool = False


class ProcessedCommandRepository:
    def __init__(self, path: Path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS processed_commands (
                    command_id TEXT PRIMARY KEY, command_type TEXT NOT NULL,
                    status TEXT NOT NULL, error TEXT, processed_at TEXT NOT NULL
                )
            """)

    def get(self, command_id: str) -> CommandResult | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT status, error FROM processed_commands WHERE command_id=?", (command_id,)).fetchone()
        return None if row is None else CommandResult(command_id, row[0], row[1], True)

    def save(self, command_id: str, command_type: str, status: str, error: str | None) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR IGNORE INTO processed_commands VALUES (?, ?, ?, ?, ?)",
                (command_id, command_type, status, error, datetime.now().astimezone().isoformat()),
            )


class CommandHandler:
    TYPES = {"LOCK_NOW", "UNLOCK", "ADD_TIME"}

    def __init__(
        self,
        repository: ProcessedCommandRepository,
        usage: UsageRepository,
        enforcer: WorkstationEnforcer,
        today: Callable = lambda: datetime.now().astimezone().date(),
    ):
        self.repository = repository
        self.usage = usage
        self.enforcer = enforcer
        self.today = today

    def handle(self, command: dict[str, Any]) -> CommandResult:
        command_id = command.get("command_id")
        command_type = command.get("type")
        if not isinstance(command_id, str) or not command_id:
            return CommandResult("", "failed", "missing command_id")
        previous = self.repository.get(command_id)
        if previous:
            return previous
        error = None
        try:
            if command_type not in self.TYPES:
                raise ValueError("unsupported command type")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            if command_type == "LOCK_NOW":
                if not self.enforcer.enforce(EnforcementReason.REMOTE_LOCK, force=True):
                    raise RuntimeError("LockWorkStation failed")
            elif command_type == "UNLOCK":
                self.enforcer.allow_unlock()
            else:
                minutes = payload.get("minutes")
                if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 240:
                    raise ValueError("ADD_TIME minutes must be between 1 and 240")
                current = self.usage.get(self.today())
                self.usage.set_bonus(self.today(), current.bonus_seconds + minutes * 60)
            status = "completed"
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            status, error = "failed", str(exc)[:255]
        self.repository.save(command_id, str(command_type), status, error)
        return CommandResult(command_id, status, error)
