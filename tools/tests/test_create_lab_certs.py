import argparse
import importlib.util
import ipaddress
from pathlib import Path
import ssl
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import ExtendedKeyUsageOID

spec = importlib.util.spec_from_file_location(
    "create_lab_certs", Path(__file__).resolve().parents[1] / "create_lab_certs.py")
certs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(certs)


class LabCertificatesTests(unittest.TestCase):
    def test_chain_san_pin_and_tls_handshake(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "certs"
            pin = certs.create_certificates(
                output, [ipaddress.ip_address("127.0.0.1")], ["localhost"], 30)
            ca = x509.load_pem_x509_certificate((output / "ca.pem").read_bytes())
            leaf = x509.load_pem_x509_certificate((output / "server.pem").read_bytes())
            leaf.verify_directly_issued_by(ca)
            self.assertEqual(pin, leaf.fingerprint(hashes.SHA256()).hex())
            self.assertIn(ExtendedKeyUsageOID.SERVER_AUTH,
                          leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)
            san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            self.assertEqual(san.get_values_for_type(x509.DNSName), ["localhost"])
            self.assertEqual(san.get_values_for_type(x509.IPAddress),
                             [ipaddress.ip_address("127.0.0.1")])
            server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server.minimum_version = ssl.TLSVersion.TLSv1_2
            server.load_cert_chain(output / "server.pem", output / "server-key.pem")
            client = ssl.create_default_context(cafile=str(output / "ca.pem"))
            client.minimum_version = client.maximum_version = ssl.TLSVersion.TLSv1_2
            for hostname, expected in [("localhost", True), ("127.0.0.1", True),
                                       ("wrong.example", False)]:
                si, so, ci, co = (ssl.MemoryBIO() for _ in range(4))
                s = server.wrap_bio(si, so, server_side=True)
                c = client.wrap_bio(ci, co, server_hostname=hostname)
                verified = False
                try:
                    for _ in range(20):
                        try:
                            c.do_handshake()
                            verified = True
                            break
                        except ssl.SSLWantReadError:
                            pass
                        si.write(co.read())
                        try:
                            s.do_handshake()
                        except ssl.SSLWantReadError:
                            pass
                        ci.write(so.read())
                except ssl.SSLCertVerificationError:
                    pass
                self.assertEqual(verified, expected, hostname)
                if verified:
                    self.assertEqual(c.version(), "TLSv1.2")
            before = (output / "server.pem").read_bytes()
            with self.assertRaises(FileExistsError):
                certs.create_certificates(output, [], ["localhost"], 30)
            self.assertEqual(before, (output / "server.pem").read_bytes())

    def test_reject_invalid_dns_input(self):
        for name in ["https://localhost", "localhost:8000", "*.example.com", "../test"]:
            with self.assertRaises((argparse.ArgumentTypeError, UnicodeError)):
                certs.dns_name(name)


if __name__ == "__main__":
    unittest.main()
