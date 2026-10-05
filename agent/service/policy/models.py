"""Strict, dependency-free models for remotely supplied policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PolicyValidationError(ValueError):
    pass


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise PolicyValidationError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class ScreenTimePolicy:
    weekday_minutes: int
    weekend_minutes: int
    idle_timeout_sec: int
    grace_period_sec: int
    warning_minutes: tuple[int, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "ScreenTimePolicy":
        if not isinstance(value, dict):
            raise PolicyValidationError("payload.screen_time must be an object")
        warnings = value.get("warning_minutes", [10, 5, 1])
        if not isinstance(warnings, list) or any(
            isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 60
            for item in warnings
        ):
            raise PolicyValidationError("warning_minutes must contain integers between 1 and 60")
        return cls(
            weekday_minutes=_integer(value.get("weekday_minutes", 90), "weekday_minutes", 1, 1440),
            weekend_minutes=_integer(value.get("weekend_minutes", 120), "weekend_minutes", 1, 1440),
            idle_timeout_sec=_integer(value.get("idle_timeout_sec", 300), "idle_timeout_sec", 60, 3600),
            grace_period_sec=_integer(value.get("grace_period_sec", 60), "grace_period_sec", 0, 300),
            warning_minutes=tuple(sorted(set(warnings), reverse=True)),
        )


@dataclass(frozen=True)
class Policy:
    policy_id: str
    version: int
    payload: dict[str, Any]
    signature: str
    screen_time: ScreenTimePolicy
    weekly_schedule: tuple[bool, ...]

    @classmethod
    def from_envelope(cls, envelope: Any) -> "Policy":
        if not isinstance(envelope, dict):
            raise PolicyValidationError("policy must be an object")
        version = _integer(envelope.get("version"), "version", 1, 2_147_483_647)
        policy_id = envelope.get("id")
        signature = envelope.get("signature")
        payload = envelope.get("payload")
        if not isinstance(policy_id, str) or not policy_id:
            raise PolicyValidationError("policy.id must be a non-empty string")
        if not isinstance(signature, str) or len(signature) != 64:
            raise PolicyValidationError("policy.signature must be a 64-character hex digest")
        try:
            bytes.fromhex(signature)
        except ValueError as exc:
            raise PolicyValidationError("policy.signature must be hexadecimal") from exc
        if not isinstance(payload, dict):
            raise PolicyValidationError("policy.payload must be an object")
        schedule = payload.get("weekly_schedule", [True] * 336)
        if not isinstance(schedule, list) or len(schedule) != 336 or any(type(item) is not bool for item in schedule):
            raise PolicyValidationError("weekly_schedule must contain exactly 336 booleans")
        for name in ("apps", "domains"):
            if not isinstance(payload.get(name, []), list):
                raise PolicyValidationError(f"payload.{name} must be a list")
        return cls(
            policy_id=policy_id,
            version=version,
            payload=payload,
            signature=signature.lower(),
            screen_time=ScreenTimePolicy.from_dict(payload.get("screen_time", {})),
            weekly_schedule=tuple(schedule),
        )

    def is_allowed_at(self, moment) -> bool:
        slot = moment.weekday() * 48 + moment.hour * 2 + moment.minute // 30
        return self.weekly_schedule[slot]

    def quota_seconds_at(self, moment) -> int:
        minutes = self.screen_time.weekend_minutes if moment.weekday() >= 5 else self.screen_time.weekday_minutes
        return minutes * 60
    