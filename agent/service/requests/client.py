"""Extra-time request use case over an injected authorized HTTP sender."""

from __future__ import annotations

from typing import Any, Callable


class ExtraTimeClient:
    def __init__(self, post: Callable[[str, dict[str, Any]], dict[str, Any]]):
        self._post = post

    def request(self, minutes: int = 15) -> dict[str, Any]:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 5 <= minutes <= 120:
            raise ValueError("requested_minutes must be between 5 and 120")
        return self._post("/api/v1/agent/requests", {"type": "extra_time", "requested_minutes": minutes})
