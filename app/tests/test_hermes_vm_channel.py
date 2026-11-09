import hashlib
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from hermes_vm_channel import authenticate_vm_socket


def certificate(directory, name):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                   .not_valid_after(now + timedelta(hours=1))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName(name), x509.IPAddress(ip_address("127.0.0.1"))]), False)
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                   .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / (name + ".crt"), directory / (name + ".key")
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return cert_path, key_path, hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()


def contexts(tmp_path):
    server_cert, server_key, server_hash = certificate(tmp_path, "localhost")
    client_cert, client_key, client_hash = certificate(tmp_path, "guest")
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.minimum_version = ssl.TLSVersion.TLSv1_3
    server.verify_mode = ssl.CERT_REQUIRED
    server.load_cert_chain(server_cert, server_key)
    server.load_verify_locations(client_cert)
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.minimum_version = ssl.TLSVersion.TLSv1_3
    client.load_cert_chain(client_cert, client_key)
    client.load_verify_locations(server_cert)
    return server, client, server_hash, client_hash


def test_mutual_tls_authenticates_real_socket_and_transports_bytes(tmp_path):
    server, client, server_hash, client_hash = contexts(tmp_path)
    left, right = socket.socketpair()

    def serve():
        with authenticate_vm_socket(left, server, client_hash, server_side=True) as secured:
            assert secured.version() == "TLSv1.3"
            assert secured.recv(32) == b"runtime request"
            secured.sendall(b"runtime response")

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(serve)
        with authenticate_vm_socket(right, client, server_hash, server_side=False, server_hostname="localhost") as secured:
            secured.sendall(b"runtime request")
            assert secured.recv(32) == b"runtime response"
        future.result(timeout=10)


def test_mutual_tls_rejects_changed_certificate_pin(tmp_path):
    server, client, _, client_hash = contexts(tmp_path)
    left, right = socket.socketpair()

    def serve():
        with authenticate_vm_socket(left, server, client_hash, server_side=True) as secured:
            assert secured.recv(32) == b""

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(serve)
        with pytest.raises(ValueError, match="证书不匹配"):
            authenticate_vm_socket(right, client, "0" * 64, server_side=False, server_hostname="localhost")
        future.result(timeout=10)


def test_unverified_tls_context_is_rejected(tmp_path):
    server, _, _, client_hash = contexts(tmp_path)
    server.verify_mode = ssl.CERT_NONE
    left, right = socket.socketpair()
    with left, right:
        with pytest.raises(ValueError, match="验证双方证书"):
            authenticate_vm_socket(left, server, client_hash, server_side=True)


def test_mutual_tls_rejects_client_without_certificate(tmp_path):
    server, _, _, client_hash = contexts(tmp_path)
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.minimum_version = ssl.TLSVersion.TLSv1_3
    client.load_verify_locations(tmp_path / "localhost.crt")
    left, right = socket.socketpair()

    def serve():
        with pytest.raises(ssl.SSLError):
            authenticate_vm_socket(left, server, client_hash, server_side=True)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(serve)
        with client.wrap_socket(right, server_hostname="localhost") as secured:
            with pytest.raises(ssl.SSLError):
                secured.recv(1)
        future.result(timeout=10)
