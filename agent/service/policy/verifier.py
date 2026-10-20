"""Policy integrity verification compatible with the server signer."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_policy_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def expected_signature(payload: dict[str, Any], version: int, secret: str) -> str:
    message = f"{version}.{canonical_policy_json(payload)}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signature(payload: dict[str, Any], version: int, signature: str, secret: str) -> bool:
    return hmac.compare_digest(expected_signature(payload, version, secret), signature.lower())
