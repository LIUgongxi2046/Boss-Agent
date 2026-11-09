import hashlib
import argparse
import os
import ssl
import stat
import subprocess
import sys
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class HermesVMCredentials:
    server: ssl.SSLContext
    client: ssl.SSLContext
    peer_name: str
    peer_sha256: str


def _identity(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("虚拟机凭据身份无效")
    return "boss-vm-" + value


def vm_id_from_machine_sha256(value):
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("虚拟机机器摘要无效")
    return str(uuid5(NAMESPACE_URL, "boss-vm:" + value))


def _write_private(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def provision_vm_credentials(directory, vm_id):
    name = _identity(vm_id)
    directory = Path(directory)
    parent = directory.parent
    if not directory.is_absolute() or parent.resolve(strict=True) != parent or not parent.is_dir():
        raise ValueError("虚拟机凭据目录不可核查")
    info = parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("虚拟机凭据父目录权限无效")
    directory.mkdir(mode=0o700)
    host_dir, guest_dir = directory / "host", directory / "guest"
    host_dir.mkdir(mode=0o700)
    guest_dir.mkdir(mode=0o700)
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name + ".ca")])
    authority = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
                 .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                 .not_valid_after(now + timedelta(days=365))
                 .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                 .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                     data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                     encipher_only=False, decipher_only=False), critical=True).sign(ca_key, hashes.SHA256()))
    issued = {}
    for side in ("host", "guest"):
        key = ec.generate_private_key(ec.SECP256R1())
        hostname = name + "." + side
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_name).public_key(key.public_key())
                       .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                       .not_valid_after(now + timedelta(days=365))
                       .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                       .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
                       .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                       .sign(ca_key, hashes.SHA256()))
        issued[side] = (certificate, key)
    ca_pem = authority.public_bytes(serialization.Encoding.PEM)
    for side, target in (("host", host_dir), ("guest", guest_dir)):
        certificate, key = issued[side]
        _write_private(target / "ca.pem", ca_pem)
        _write_private(target / "certificate.pem", certificate.public_bytes(serialization.Encoding.PEM))
        _write_private(target / "private-key.pem", key.private_bytes(serialization.Encoding.PEM,
                       serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        peer = issued["guest" if side == "host" else "host"][0]
        _write_private(target / "peer-certificate.pem", peer.public_bytes(serialization.Encoding.PEM))


def load_vm_credentials(directory, vm_id, side):
    name = _identity(vm_id)
    if side not in {"host", "guest"}:
        raise ValueError("虚拟机凭据角色无效")
    directory = Path(directory)
    if not directory.is_absolute() or directory.resolve(strict=True) != directory or not directory.is_dir():
        raise ValueError("虚拟机凭据目录不可核查")
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("虚拟机凭据目录权限无效")
    paths = [directory / item for item in ("ca.pem", "certificate.pem", "private-key.pem", "peer-certificate.pem")]
    for path in paths:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("虚拟机凭据文件权限无效")
    own = x509.load_pem_x509_certificate(paths[1].read_bytes())
    peer = x509.load_pem_x509_certificate(paths[3].read_bytes())
    peer_side = "guest" if side == "host" else "host"
    for certificate, expected in ((own, name + "." + side), (peer, name + "." + peer_side)):
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        if names != [expected]:
            raise ValueError("虚拟机凭据名称不匹配")
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.minimum_version = ssl.TLSVersion.TLSv1_3
    server.verify_mode = ssl.CERT_REQUIRED
    server.load_cert_chain(paths[1], paths[2])
    server.load_verify_locations(paths[0])
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.minimum_version = ssl.TLSVersion.TLSv1_3
    client.load_cert_chain(paths[1], paths[2])
    client.load_verify_locations(paths[0])
    return HermesVMCredentials(server, client, name + "." + peer_side,
                               hashlib.sha256(peer.public_bytes(serialization.Encoding.DER)).hexdigest())


def load_vm_credential_pair(directory, vm_id):
    directory = Path(directory)
    if not directory.is_absolute() or directory.resolve(strict=True) != directory or not directory.is_dir():
        raise ValueError("虚拟机凭据根目录不可核查")
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("虚拟机凭据根目录权限无效")
    host = load_vm_credentials(directory / "host", vm_id, "host")
    guest = load_vm_credentials(directory / "guest", vm_id, "guest")
    host_cert = x509.load_pem_x509_certificate((directory / "host/certificate.pem").read_bytes())
    guest_cert = x509.load_pem_x509_certificate((directory / "guest/certificate.pem").read_bytes())
    if host.peer_sha256 != hashlib.sha256(guest_cert.public_bytes(serialization.Encoding.DER)).hexdigest() or guest.peer_sha256 != hashlib.sha256(host_cert.public_bytes(serialization.Encoding.DER)).hexdigest():
        raise ValueError("虚拟机双方凭据不匹配")
    if (directory / "host/ca.pem").read_bytes() != (directory / "guest/ca.pem").read_bytes():
        raise ValueError("虚拟机双方证书来源不匹配")
    return host, guest


def install_guest_credentials(destination, vm_id):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("客体凭据安装需要 Linux 系统管理权限")
    _identity(vm_id)
    source = Path("/run/boss-vm/credential-share")
    destination = Path(destination)
    if not destination.is_absolute() or destination.parent != Path("/run/boss-vm") or destination.name != vm_id:
        raise ValueError("客体凭据目标无效")
    parent = destination.parent
    if source.resolve(strict=True) != source or parent.resolve(strict=True) != parent:
        raise ValueError("客体凭据路径不可核查")
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("客体凭据父目录权限无效")
    output = subprocess.run(["/usr/bin/findmnt", "--json", "--mountpoint", str(source), "--output", "TARGET,SOURCE,FSTYPE,OPTIONS"],
                            check=True, capture_output=True, text=True, timeout=15)
    mounts = json.loads(output.stdout)["filesystems"]
    if len(mounts) != 1 or mounts[0]["target"] != str(source) or mounts[0]["source"] != "boss-probe" or mounts[0]["fstype"] != "virtiofs" or "ro" not in mounts[0]["options"].split(","):
        raise ValueError("客体凭据共享范围不可核查")
    output = subprocess.run(["/usr/bin/findmnt", "--json", "--target", str(parent), "--output", "TARGET,FSTYPE"],
                            check=True, capture_output=True, text=True, timeout=15)
    mounts = json.loads(output.stdout)["filesystems"]
    if len(mounts) != 1 or mounts[0]["fstype"] != "tmpfs":
        raise ValueError("客体凭据需要临时内存文件系统")
    destination.mkdir(mode=0o700)
    for name in ("ca.pem", "certificate.pem", "private-key.pem", "peer-certificate.pem"):
        descriptor = os.open(source / name, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as input_file:
            info = os.fstat(input_file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > 65536:
                raise ValueError("客体共享凭据文件无效")
            data = input_file.read(65537)
            if len(data) != info.st_size:
                raise ValueError("客体共享凭据长度已经变化")
        _write_private(destination / name, data)
    credentials = load_vm_credentials(destination, vm_id, "guest")
    subprocess.run(["/usr/bin/umount", str(source)], check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return credentials


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine-sha256", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    arguments = parser.parse_args()
    vm_id = vm_id_from_machine_sha256(arguments.machine_sha256)
    provision_vm_credentials(arguments.directory, vm_id)
    print("VM_ID", vm_id)


if __name__ == "__main__":
    main()
