"""Verify, persist and activate last-known-good policies."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .models import Policy, PolicyValidationError
from .verifier import verify_signature

LOGGER = logging.getLogger("openguard-agent.security")


class PolicyRejectedError(RuntimeError):
    pass


class PolicyRepository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS policies (
                    version INTEGER PRIMARY KEY, policy_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, signature TEXT NOT NULL,
                    activated_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 0
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                    details TEXT NOT NULL, created_at TEXT NOT NULL
                )
            """)

    def active(self) -> Policy | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT policy_id, version, payload_json, signature FROM policies WHERE is_active=1 ORDER BY version DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return Policy.from_envelope({"id": row["policy_id"], "version": row["version"], "payload": json.loads(row["payload_json"]), "signature": row["signature"]})

    def activate(self, policy: Policy) -> None:
        now = datetime.now(timezone.utc).isoformat()
        encoded = json.dumps(policy.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as db:
            db.execute("UPDATE policies SET is_active=0")
            db.execute(
                "INSERT OR REPLACE INTO policies(version, policy_id, payload_json, signature, activated_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
                (policy.version, policy.policy_id, encoded, policy.signature, now),
            )

    def security_event(self, event_type: str, details: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO security_events(event_type, details, created_at) VALUES (?, ?, ?)",
                (event_type, details, datetime.now(timezone.utc).isoformat()),
            )


class PolicyManager:
    def __init__(self, repository: PolicyRepository, hmac_secret: str, apply: Callable[[Policy], None] | None = None):
        if not hmac_secret:
            raise ValueError("A policy HMAC secret is required")
        self.repository = repository
        self.hmac_secret = hmac_secret
        self._apply = apply or (lambda _policy: None)

    @property
    def current(self) -> Policy | None:
        return self.repository.active()

    def accept(self, envelope: dict[str, Any]) -> Policy:
        try:
            policy = Policy.from_envelope(envelope)
            if not verify_signature(policy.payload, policy.version, policy.signature, self.hmac_secret):
                raise PolicyRejectedError("policy signature verification failed")
            current = self.current
            if current is not None and policy.version < current.version:
                raise PolicyRejectedError("policy downgrade rejected")
            if current is not None and policy.version == current.version:
                if policy.signature != current.signature:
                    raise PolicyRejectedError("policy version collision rejected")
                return current
            self.repository.activate(policy)
            self._apply(policy)
            return policy
        except (PolicyValidationError, PolicyRejectedError) as exc:
            version = envelope.get("version") if isinstance(envelope, dict) else None
            detail = f"Rejected remote policy version={version}: {exc}"
            self.repository.security_event("POLICY_REJECTED", detail)
            LOGGER.error(detail)
            raise PolicyRejectedError(str(exc)) from exc
