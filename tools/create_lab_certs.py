"""Create a new, isolated lab CA and a server certificate; never overwrite files."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def dns_name(value: str) -> str:
    value = value.rstrip(".").encode("idna").decode("ascii").lower()
    labels = value.split(".")
    if len(value) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise argparse.ArgumentTypeError("Use a hostname without scheme, port or wildcard.")
    return value


def create_certificates(output: Path, ips: list, names: list[str], days: int) -> str:
    """Create a fresh directory and return the leaf certificate's SHA-256 pin."""
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OpenGuard Kids Lab CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=False, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    san = [x509.IPAddress(ip) for ip in dict.fromkeys(ips)]
    san.extend(x509.DNSName(name) for name in dict.fromkeys(names))
    if not san:
        raise ValueError("At least one --ip or --dns is required.")
    if not 1 <= days <= 825:
        raise ValueError("--days must be between 1 and 825.")
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OpenGuard Kids Server")]))
        .issuer_name(ca.subject).public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(x509.SubjectAlternativeName(san), False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False,
        ), True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    pin = leaf.fingerprint(hashes.SHA256()).hex()
    pem = serialization.Encoding.PEM
    files = {
        "ca.pem": ca.public_bytes(pem),
        "server.pem": leaf.public_bytes(pem),
        "ca-key.pem": ca_key.private_bytes(
            pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        "server-key.pem": server_key.private_bytes(
            pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        "server-sha256.txt": (pin + "\n").encode("ascii"),
    }
    # Refuse even an existing empty directory: never replace an installed CA/pin.
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in files.items():
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    return pin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", action="append", type=ipaddress.ip_address, default=[],
                        help="IP SAN; repeat for multiple IPv4/IPv6 addresses.")
    parser.add_argument("--dns", action="append", type=dns_name, default=[],
                        help="DNS SAN; repeat for multiple hostnames.")
    parser.add_argument("--days", type=int, default=365, help="Server validity, 1-825 days.")
    parser.add_argument("--out", type=Path, default=Path("lab-certs"),
                        help="New output directory (default: ./lab-certs).")
    args = parser.parse_args()
    if not args.ip and not args.dns:
        parser.error("Specify at least one --ip or --dns.")
    if not 1 <= args.days <= 825:
        parser.error("--days must be between 1 and 825.")
    output = args.out.expanduser().absolute()
    if output.exists():
        parser.error("Output already exists. Choose a new directory; existing certificates are never replaced.")
    try:
        pin = create_certificates(output, args.ip, args.dns, args.days)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Certificate generation failed: {exc}\n")
    print(f"Created lab certificates in: {output}")
    print(f"OGK_TLS_CA_FILE={(output / 'ca.pem').as_posix()}")
    print(f"OGK_TLS_CERT_SHA256={pin}")
    print("Set OGK_SERVER_URL=https://<a SAN address>:8000 and OGK_VERIFY_TLS=true.")
    print("Private keys are unencrypted. Restrict directory access to administrators/server.")
    print("Distribute only ca.pem and the server fingerprint to clients. Never share private keys.")
    print("No trust store, environment file or running service was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
