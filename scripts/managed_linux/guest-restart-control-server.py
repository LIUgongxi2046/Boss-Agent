import argparse
import socket
import subprocess
import sys
from pathlib import Path

from aiohttp import web

from hermes_guest_control import HermesGuestControl
from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_proxy import HermesGuestRuntimeProxy
from hermes_guest_systemd import HermesGuestSystemd
from hermes_vm_credentials import load_vm_credential_pair


parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--vm-id", required=True)
parser.add_argument("--port", type=int, required=True)
arguments = parser.parse_args()
directory = arguments.directory.resolve(strict=True)
_, guest = load_vm_credential_pair(directory / "credentials", arguments.vm_id)
manager = HermesGuestSystemd(python=Path(sys.executable).resolve(), entry=Path("/run/boss-checks/guest-identity-probe.py"),
    engine=Path("/run/boss-checks"), dependencies=Path("/run/boss-deps/linux-target"),
    workspace_root=directory / "workspaces", identities=HermesGuestIdentityRegistry(directory / "identities"),
    supervisor_unit="boss-test-control.service")
proxy = HermesGuestRuntimeProxy(guest.client, guest.peer_name, guest.peer_sha256, 1024)
control = HermesGuestControl(manager, proxy, guest.server, guest.peer_sha256)
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", arguments.port))
listener.listen()
subprocess.run(["/usr/bin/systemd-notify", "READY=1"], check=True, timeout=5)
web.run_app(control.application(), sock=listener, ssl_context=guest.server, print=None)
