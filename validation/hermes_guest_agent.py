import argparse
import asyncio
import socket
import subprocess
from pathlib import Path

from hermes_guest_control import HermesGuestControl
from hermes_guest_proxy import HermesGuestRuntimeProxy
from hermes_guest_systemd import HermesGuestSystemd
from hermes_guest_identity import HermesGuestIdentityRegistry, require_persistent_guest_storage
from hermes_guest_workspace_service import HermesGuestWorkspaceService
from hermes_vm_credentials import install_guest_credentials, load_vm_credentials


async def serve(args):
    if args.install_shared_credentials:
        credentials = install_guest_credentials(args.credentials, args.vm_id)
    else:
        credentials = load_vm_credentials(args.credentials, args.vm_id, "guest")
    require_persistent_guest_storage(args.identity_directory)
    identities = HermesGuestIdentityRegistry(args.identity_directory)
    workspace_service = HermesGuestWorkspaceService(args.workspace_root, args.juicefs, args.juicefs_sha256, identities, args.supervisor_unit)
    manager = HermesGuestSystemd(python=args.python, entry=args.entry, engine=args.engine, dependencies=args.dependencies,
                                 workspace_root=args.workspace_root, identities=identities, supervisor_unit=args.supervisor_unit,
                                 workspace_service=workspace_service)
    proxy = HermesGuestRuntimeProxy(credentials.client, credentials.peer_name, credentials.peer_sha256, 1024,
                                    credentials_directory=args.credentials, vm_id=args.vm_id, dependencies=args.dependencies)
    control = HermesGuestControl(manager, proxy, credentials.server, credentials.peer_sha256)
    listener = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    listener.bind((socket.VMADDR_CID_ANY, 1025))
    listener.listen(16)
    runner = await control.listen(listener)
    try:
        subprocess.run(["/usr/bin/systemd-notify", "--ready"], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vm-id", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--install-shared-credentials", action="store_true")
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--juicefs", type=Path, required=True)
    parser.add_argument("--juicefs-sha256", required=True)
    parser.add_argument("--identity-directory", type=Path, required=True)
    parser.add_argument("--supervisor-unit", required=True)
    asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    main()
