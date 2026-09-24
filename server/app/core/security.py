import hashlib
import hmac
import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from app.core.config import settings

password_hasher = PasswordHasher()

ENROLLMENT_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

def utc_now() -> datetime:
    """
        Naive UTC for SQLite persistence/comparison
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

def utc_now_aware() -> datetime:
    """
        Timezone-aware UTC for API/JWT timestamps.
    """
    return datetime.now(timezone.utc)

def hash_password(password: str) -> str:
    return password_hasher.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False

def create_access_token(
        subject: str,
        token_type: str,
        expires_minutes: int,
) -> str:
    now = utc_now_aware()
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }

    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])

def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)

def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def hash_device_fingerprint(value: str) -> str:
    return hash_secret(value)

def generate_enrollment_code(length: int = 8) -> str:
    return "".join(secrets.choice(ENROLLMENT_ALPHABET) for _ in range(length))

def canonical_policy_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sign_policy(payload: dict[str, Any], version: int) -> str:
    message = f"{version}.{canonical_policy_json(payload)}".encode("utf-8")

    return hmac.new(
        settings.policy_hmac_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

def verify_policy_signature(payload: dict[str, Any], version: int, signature: str) -> bool:
    expected = sign_policy(payload, version)

    return hmac.compare_digest(expected, signature)


