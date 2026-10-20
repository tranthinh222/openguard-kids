import datetime
import hashlib
import socket
import ssl
import threading

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from websockets.sync.client import connect

from service.tls import tls_context


@pytest.fixture
def certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    crt, pem = tmp_path / "cert.pem", tmp_path / "key.pem"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    return crt, pem, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


@pytest.mark.parametrize("protocol,match", [("http", False), ("websocket", False), ("http", True)])
def test_credentials_are_sent_only_after_pin_matches(certificate, protocol, match):
    crt, pem, pin = certificate
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(5)
    port = listener.getsockname()[1]
    received = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(crt, pem)

    def serve():
        try:
            raw, _ = listener.accept()
            with context.wrap_socket(raw, server_side=True) as stream:
                stream.settimeout(5)
                received.append(stream.recv(4096))
                if received[-1]:
                    stream.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
        except (ssl.SSLError, OSError):
            pass
        finally:
            listener.close()
    worker = threading.Thread(target=serve)
    worker.start()
    verify = tls_context("https://localhost", pin=pin if match else "0" * 64, cafile=str(crt))
    try:
        if protocol == "http":
            with httpx.Client(verify=verify, trust_env=False) as client:
                if match:
                    assert client.get(f"https://localhost:{port}", headers={"Authorization": "Bearer SECRET"}).status_code == 200
                else:
                    with pytest.raises(httpx.ConnectError):
                        client.get(f"https://localhost:{port}", headers={"Authorization": "Bearer SECRET"})
        else:
            with pytest.raises(ssl.SSLCertVerificationError):
                connect(f"wss://localhost:{port}", ssl=verify, proxy=None,
                        additional_headers={"Authorization": "Bearer SECRET"})
    finally:
        worker.join(timeout=6)
    assert not worker.is_alive()
    assert (b"Bearer SECRET" in b"".join(received)) if match else not b"".join(received)


def test_valid_pin_and_required_config(certificate):
    crt, _, pin = certificate
    context = tls_context("https://localhost", pin=pin, cafile=str(crt))
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    for url, verify, value in [("https://host", True, None), ("http://host", True, pin),
                               ("https://host", False, pin), ("https://host", True, "invalid")]:
        with pytest.raises(ValueError):
            tls_context(url, verify, value)
