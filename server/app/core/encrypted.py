"""Authenticated encryption for identifying text; keys stay outside the database."""
import base64
import os
import hmac
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String, JSON
import json
from sqlalchemy.types import TypeDecorator
from app.core.config import settings

PREFIX = "ogk:gcm:v1:"

def encryption_key():
    key = base64.b64decode(settings.data_encryption_key, validate=True)
    if len(key) != 32:
        raise RuntimeError("Set DATA_ENCRYPTION_KEY to a base64 encoded random 32-byte key before using the database")
    return key


def email_lookup(value):
    return hmac.new(encryption_key(), b"email-index:" + value.strip().lower().encode("utf-8"),
                    hashlib.sha256).hexdigest()

class EncryptedText(TypeDecorator):
    impl = String
    cache_ok = True

    def __init__(self, purpose, length):
        # SQLite's VARCHAR affinity has no length limit. Retaining the existing
        # declaration avoids rebuilding parent tables referenced by foreign keys.
        super().__init__(length)
        self.purpose = purpose

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        key = encryption_key()
        nonce = os.urandom(12)
        encrypted = AESGCM(key).encrypt(nonce, value.encode("utf-8"), self.purpose.encode())
        return PREFIX + base64.b64encode(nonce + encrypted).decode("ascii")

    def process_result_value(self, value, dialect):
        if value is None or not value.startswith(PREFIX):
            return value  # Transitional read for existing DBs; migration tool rewrites these.
        key = encryption_key()
        data = base64.b64decode(value[len(PREFIX):], validate=True)
        return AESGCM(key).decrypt(data[:12], data[12:], self.purpose.encode()).decode("utf-8")


class EncryptedJSON(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, purpose):
        super().__init__()
        self.purpose = purpose

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return EncryptedText(self.purpose, None).process_bind_param(json.dumps(value), dialect)

    def process_result_value(self, value, dialect):
        if value is None or isinstance(value, (dict, list)):
            return value
        return json.loads(EncryptedText(self.purpose, None).process_result_value(value, dialect))
