import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from hermes_vm_channel import authenticate_vm_socket
from hermes_vm_credentials import install_guest_credentials, load_vm_credential_pair, load_vm_credentials, provision_vm_credentials, vm_id_from_machine_sha256


def test_vm_credentials_isolate_private_keys_and_authenticate_both_sides(tmp_path):
    tmp_path.chmod(0o700)
    vm_id = str(uuid4())
    directory = tmp_path / "credentials"
    provision_vm_credentials(directory, vm_id)
    host, guest = load_vm_credential_pair(directory, vm_id)
    assert {path.name for path in (directory / "guest").iterdir()} == {"ca.pem", "certificate.pem", "private-key.pem", "peer-certificate.pem"}
    assert (directory / "host/private-key.pem").read_bytes() != (directory / "guest/private-key.pem").read_bytes()
    left, right = socket.socketpair()

    def serve():
        with authenticate_vm_socket(left, host.server, host.peer_sha256, server_side=True) as connection:
            assert connection.recv(64) == b"vm request"
            connection.sendall(b"vm response")

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(serve)
        with authenticate_vm_socket(right, guest.client, guest.peer_sha256, server_side=False,
                                    server_hostname=guest.peer_name) as connection:
            connection.sendall(b"vm request")
            assert connection.recv(64) == b"vm response"
        future.result(timeout=10)
    with pytest.raises(FileExistsError):
        provision_vm_credentials(directory, vm_id)
    with pytest.raises(ValueError, match="名称不匹配"):
        load_vm_credentials(directory / "host", str(uuid4()), "host")
    other = tmp_path / "other-credentials"
    provision_vm_credentials(other, vm_id)
    (directory / "guest/peer-certificate.pem").write_bytes((other / "host/certificate.pem").read_bytes())
    with pytest.raises(ValueError, match="双方凭据不匹配"):
        load_vm_credential_pair(directory, vm_id)
    (directory / "guest/private-key.pem").chmod(0o644)
    with pytest.raises(ValueError, match="文件权限无效"):
        load_vm_credentials(directory / "guest", vm_id, "guest")


@pytest.mark.skipif(sys.platform != "darwin", reason="需要 Apple Virtualization.framework")
def test_framework_machine_identifier_drives_vm_credentials(tmp_path):
    tmp_path.chmod(0o700)
    root = Path(__file__).resolve().parents[2]
    executable = tmp_path / "vm-identity"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-module-cache-path", str(root / ".work/upgrade2/managed-linux-001/swift-module-cache"),
                    str(root / "scripts/managed_linux/vsock-probe.swift"), "-o", str(executable)], check=True, timeout=60)
    identity = tmp_path / "machine-identity"
    subprocess.run([str(executable), "--init-identity", str(identity)], check=True, timeout=15, capture_output=True)
    output = subprocess.run([str(executable), "--check-identity", str(identity)], check=True, timeout=15, capture_output=True, text=True).stdout.split()
    assert output[0] == "VM_IDENTITY_SHA256" and len(output) == 2
    vm_id = vm_id_from_machine_sha256(output[1])
    directory = tmp_path / "credentials"
    provision_vm_credentials(directory, vm_id)
    host, guest = load_vm_credential_pair(directory, vm_id)
    assert host.peer_name == "boss-vm-" + vm_id + ".guest"
    assert guest.peer_name == "boss-vm-" + vm_id + ".host"


@pytest.mark.skipif(sys.platform == "linux", reason="此检查针对非 Linux 宿主")
def test_guest_credential_install_rejects_non_linux_host():
    vm_id = str(uuid4())
    with pytest.raises(ValueError, match="需要 Linux 系统管理权限"):
        install_guest_credentials(Path("/run/boss-vm") / vm_id, vm_id)
