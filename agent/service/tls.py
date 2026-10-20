"""Verify the peer certificate before HTTP headers or WebSocket handshake are sent."""
import hashlib
import hmac
import re
import ssl
from urllib.parse import urlsplit


class PinnedContext(ssl.SSLContext):
    def __new__(cls, pin, cafile=None):
        return super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)

    def __init__(self, pin, cafile=None):
        self.pin = pin
        self.minimum_version = ssl.TLSVersion.TLSv1_2
        self.load_default_certs()
        if cafile:
            self.load_verify_locations(cafile=cafile)

    def wrap_socket(self, *args, **kwargs):
        # Both httpcore's synchronous transport and websockets.sync use this path.
        kwargs["do_handshake_on_connect"] = True
        sock = super().wrap_socket(*args, **kwargs)
        digest = hashlib.sha256(sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(digest, self.pin):
            sock.close()
            raise ssl.SSLCertVerificationError("OpenGuard server certificate pin mismatch")
        return sock

    def wrap_bio(self, *args, **kwargs):
        # Never silently bypass pinning if a future transport changes to TLS-in-TLS.
        raise ssl.SSLError("Pinned transport requires a direct TLS socket")


def tls_context(url, verify=True, pin=None, cafile=None):
    scheme = urlsplit(url).scheme
    if pin:
        pin = pin.lower().replace(":", "").strip()
        if not re.fullmatch("[0-9a-f]{64}", pin):
            raise ValueError("OGK_TLS_CERT_SHA256 must be a SHA-256 certificate fingerprint")
        if scheme not in {"https", "wss"} or not verify:
            raise ValueError("Certificate pinning requires HTTPS and certificate verification")
        return PinnedContext(pin, cafile)
    if scheme in {"https", "wss"}:
        raise ValueError("HTTPS requires OGK_TLS_CERT_SHA256 (SHA-256 of the server certificate)")
    return verify
