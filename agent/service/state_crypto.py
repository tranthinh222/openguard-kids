"""AES-GCM token envelope. Windows key is protected by DPAPI and folder ACLs."""
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AAD = b"OpenGuardKids/agent-state/v1"


def _key(path: Path):
    configured = os.getenv("OGK_STATE_ENCRYPTION_KEY")
    if configured:
        key = base64.b64decode(configured, validate=True)
    else:
        key_path = path.with_name("state-key.dpapi" if os.name == "nt" else "state-key.bin")
        if not key_path.exists():
            key = AESGCM.generate_key(bit_length=256)
            if os.name == "nt":
                import win32crypt
                encoded = win32crypt.CryptProtectData(key, "OpenGuard Kids", None, None, None, 4)
            else:
                encoded = key
            # StateStore serializes callers; exclusive creation also prevents overwrite.
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as out:
                    out.write(encoded)
                    out.flush()
                    os.fsync(out.fileno())
        encoded = key_path.read_bytes()
        if os.name == "nt":
            import win32crypt
            key = win32crypt.CryptUnprotectData(encoded, None, None, None, 0)[1]
        else:
            key = encoded
    if len(key) != 32:
        raise ValueError("State encryption key must contain 32 bytes")
    return key


def encrypt(path, plaintext):
    nonce = os.urandom(12)
    return {"format": "aes-gcm-v1", "data": base64.b64encode(
        nonce + AESGCM(_key(path)).encrypt(nonce, plaintext, AAD)).decode("ascii")}


def decrypt(path, envelope):
    if envelope.get("format") != "aes-gcm-v1":
        raise ValueError("Unsupported encrypted state format")
    raw = base64.b64decode(envelope["data"], validate=True)
    return AESGCM(_key(path)).decrypt(raw[:12], raw[12:], AAD)
