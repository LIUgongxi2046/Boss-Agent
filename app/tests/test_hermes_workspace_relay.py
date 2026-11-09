import asyncio
import socket
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from aiohttp import web

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_process_evidence import HermesProcessEvidence
from hermes_run_authority import HermesRunAuthority
from hermes_vm_channel import HermesVMClientTLS, HermesVMServerTLS
from hermes_vm_credentials import load_vm_credential_pair, provision_vm_credentials
from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings
from hermes_workspace_relay import HermesWorkspaceRelay
from test_hermes_process_evidence import expire_lease, running_process_store
from test_hermes_run_recovery import product_services
from test_hermes_vm_channel import contexts


@pytest.mark.parametrize("ending", ["expired", "cancelled"])
def test_authenticated_workspace_relay_closes_live_connection(tmp_path, ending):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    store.configure_file_budget(run_id, "worker", epoch, 5, 1024)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                "boss-1", "ui-check", vm_id, boot_id, workspace)
    access = HermesVMRunAccess(bindings, run_id, "slot", "worker", epoch, vm_id, boot_id, workspace)
    server_context, client_context, _, client_hash = contexts(tmp_path)

    async def check():
        target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        target.bind(("127.0.0.1", 0))
        target_port = target.getsockname()[1]
        target.close()
        root = Path(__file__).resolve().parents[2]
        service = await asyncio.create_subprocess_exec(sys.executable, "-m", "http.server", str(target_port),
            "--bind", "127.0.0.1", "--protocol", "HTTP/1.1", "--directory", str(root),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            for _ in range(100):
                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = probe.connect_ex(("127.0.0.1", target_port))
                probe.close()
                if result == 0:
                    break
                await asyncio.sleep(0.05)
            else:
                raise TimeoutError("工作区通信目标未启动")
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            relay = HermesWorkspaceRelay(HermesVMServerTLS(server_context, client_hash, access), target_port)
            await relay.listen(listener)
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port, ssl=client_context,
                                                                              server_hostname="localhost"), 5)
            writer.write(b"GET /AGENTS.md HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            assert b"200 OK" in headers
            assert await asyncio.wait_for(reader.readexactly(len((root / "AGENTS.md").read_bytes())), 5) == (root / "AGENTS.md").read_bytes()
            if ending == "expired":
                expire_lease(store, run_id)
            else:
                store.cancel(run_id, store.read_run(run_id)["revision"])
            assert await asyncio.wait_for(reader.read(), 5) == b""
            with pytest.raises((ValueError, ExceptionGroup)):
                await asyncio.wait_for(relay.watcher, 5)
            writer.close()
            await writer.wait_closed()
            with pytest.raises(OSError):
                await asyncio.open_connection("127.0.0.1", port, ssl=client_context, server_hostname="localhost")
        finally:
            service.terminate()
            await service.wait()

    asyncio.run(check())


def test_workspace_relay_rechecks_product_session_authority(tmp_path):
    async def check():
        store, services = product_services(tmp_path)
        concurrency = RunConcurrencyBudget(store, allow_migration=True)
        evidence = HermesProcessEvidence(store, allow_migration=True)
        bindings = HermesVMRunBindings(store, allow_migration=True)
        run_id = store.create_run('boss-1', 'ui-check', 'workspace-authority', 'digest')
        lease = store.acquire_lease(run_id, 0, 'worker', 60)
        epoch = lease['epoch']
        store.transition(run_id, lease['revision'], 'RUNNING', 'worker', epoch)
        concurrency.configure(run_id, 'worker', epoch, 1)
        store.configure_file_budget(run_id, 'worker', epoch, 5, 1024)
        workspace = tmp_path / run_id
        workspace.mkdir()
        vm_id, boot_id = str(uuid4()), str(uuid4())
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            concurrency.reserve_in_transaction(db, run_id, 'worker', epoch, 'slot', 'digest')
            evidence.record_vm_start_in_transaction(db, bindings, run_id, 'slot', 'digest', 'worker', epoch,
                                                    'boss-1', 'ui-check', vm_id, boot_id, workspace)
        access = HermesVMRunAccess(bindings, run_id, 'slot', 'worker', epoch, vm_id, boot_id, workspace)
        server_context, _, _, client_hash = contexts(tmp_path)
        config = EngineRunConfig(run_id, epoch, '903230b1e23e0c496b28e5d2e8c4f2639cd506b6', 'http://127.0.0.1:1234', 1)
        sink = EngineEventSink(store, config, 'worker')

        async def route(request):
            authority = HermesRunAuthority(services, request, sink, 'digest', {})
            tls = HermesVMServerTLS(server_context, client_hash, access)
            with pytest.raises(ValueError, match='产品授权不匹配'):
                HermesWorkspaceRelay(tls, 1234, authority=authority)
            authority.bind_vm_access(access)
            relay = HermesWorkspaceRelay(tls, 1234, authority=authority)
            with pytest.raises(web.HTTPUnauthorized):
                relay.require_current()
            return web.Response()

        app = web.Application()
        app.router.add_get('/', route)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get('http://127.0.0.1:' + str(runner.addresses[0][1]) + '/')
                assert response.status_code == 200
        finally:
            await runner.cleanup()

    asyncio.run(check())


def test_workspace_relay_authenticates_both_transport_endpoints(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    store.configure_file_budget(run_id, 'worker', epoch, 5, 1024)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        evidence.record_vm_start_in_transaction(db, bindings, run_id, 'slot', 'digest', 'worker', epoch,
                                                'boss-1', 'ui-check', vm_id, boot_id, workspace)
    access = HermesVMRunAccess(bindings, run_id, 'slot', 'worker', epoch, vm_id, boot_id, workspace)
    server_context, client_context, server_hash, client_hash = contexts(tmp_path)
    provision_vm_credentials(tmp_path / 'vm-credentials', vm_id)
    host_credentials, guest_credentials = load_vm_credential_pair(tmp_path / 'vm-credentials', vm_id)
    payload = (Path(__file__).resolve().parents[2] / 'AGENTS.md').read_bytes()

    async def check():
        async def target(reader, writer):
            assert await reader.readexactly(4) == b'read'
            writer.write(payload)
            await writer.drain()
            await reader.read()
            writer.close()
            await writer.wait_closed()

        target_server = await asyncio.start_server(target, '127.0.0.1', 0, ssl=guest_credentials.server)
        target_port = target_server.sockets[0].getsockname()[1]
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        target_tls = HermesVMClientTLS(host_credentials.client, host_credentials.peer_name, host_credentials.peer_sha256, access)
        relay = HermesWorkspaceRelay(HermesVMServerTLS(server_context, client_hash, access), target_port, target_tls=target_tls)
        await relay.listen(listener)
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', port, ssl=client_context, server_hostname='localhost')
            writer.write(b'read')
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(len(payload)), 5) == payload
            store.cancel(run_id, store.read_run(run_id)['revision'])
            assert await asyncio.wait_for(reader.read(), 5) == b''
            with pytest.raises(ValueError):
                await relay.watcher
            writer.close()
            await writer.wait_closed()
        finally:
            target_server.close()
            await target_server.wait_closed()
            if not relay.closed:
                await relay.close()

    asyncio.run(check())


def test_workspace_relay_rejects_unrelated_root_and_vm_name(tmp_path):
    store, concurrency, evidence, run_id, epoch = running_process_store(tmp_path)
    store.configure_file_budget(run_id, 'worker', epoch, 5, 1024)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    vm_id, boot_id = str(uuid4()), str(uuid4())
    workspace = tmp_path / run_id
    workspace.mkdir()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        evidence.record_vm_start_in_transaction(db, bindings, run_id, 'slot', 'digest', 'worker', epoch,
                                                'boss-1', 'ui-check', vm_id, boot_id, workspace)
    access = HermesVMRunAccess(bindings, run_id, 'slot', 'worker', epoch, vm_id, boot_id, workspace)
    other_run = store.create_run('boss-1', 'ui-check', 'other-request', 'other-digest')
    other_lease = store.acquire_lease(other_run, 0, 'worker', 60)
    other_epoch = other_lease['epoch']
    store.transition(other_run, other_lease['revision'], 'RUNNING', 'worker', other_epoch)
    concurrency.configure(other_run, 'worker', other_epoch, 1)
    store.configure_file_budget(other_run, 'worker', other_epoch, 5, 1024)
    other_workspace = tmp_path / other_run
    other_workspace.mkdir()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        concurrency.reserve_in_transaction(db, other_run, 'worker', other_epoch, 'slot', 'digest')
        evidence.record_vm_start_in_transaction(db, bindings, other_run, 'slot', 'digest', 'worker', other_epoch,
                                                'boss-1', 'ui-check', vm_id, boot_id, other_workspace)
    other = HermesVMRunAccess(bindings, other_run, 'slot', 'worker', other_epoch, vm_id, boot_id, other_workspace)
    server_context, client_context, server_hash, client_hash = contexts(tmp_path)
    with pytest.raises(ValueError, match='名称与运行绑定不匹配'):
        HermesVMClientTLS(client_context, 'localhost', server_hash, other)
    target = HermesVMClientTLS(client_context, 'boss-vm-' + vm_id + '.guest', server_hash, other)
    with pytest.raises(ValueError, match='根运行额度不匹配'):
        HermesWorkspaceRelay(HermesVMServerTLS(server_context, client_hash, access), 1234, target_tls=target)


def test_workspace_relay_targets_root_vm_for_child_run(tmp_path):
    store = RunStore(tmp_path / 'runs.sqlite')
    concurrency = RunConcurrencyBudget(store, allow_migration=True)
    evidence = HermesProcessEvidence(store, allow_migration=True)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    root = store.create_run('boss-1', 'ui-check', 'root-request', 'digest')
    root_lease = store.acquire_lease(root, 0, 'worker', 60)
    root_epoch = root_lease['epoch']
    store.transition(root, root_lease['revision'], 'RUNNING', 'worker', root_epoch)
    concurrency.configure(root, 'worker', root_epoch, 2)
    store.configure_file_budget(root, 'worker', root_epoch, 5, 1024)
    child = store.create_child_run(root, 'worker', root_epoch, 'child-request', 'digest')
    child_lease = store.acquire_lease(child, 0, 'worker', 60)
    child_epoch = child_lease['epoch']
    store.transition(child, child_lease['revision'], 'RUNNING', 'worker', child_epoch)
    accesses = []
    for run_id, epoch in ((root, root_epoch), (child, child_epoch)):
        workspace = tmp_path / run_id
        workspace.mkdir()
        vm_id, boot_id = str(uuid4()), str(uuid4())
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            concurrency.reserve_in_transaction(db, run_id, 'worker', epoch, 'slot', 'digest')
            evidence.record_vm_start_in_transaction(db, bindings, run_id, 'slot', 'digest', 'worker', epoch,
                                                    'boss-1', 'ui-check', vm_id, boot_id, workspace)
        accesses.append(HermesVMRunAccess(bindings, run_id, 'slot', 'worker', epoch, vm_id, boot_id, workspace))
    root_access, child_access = accesses
    provision_vm_credentials(tmp_path / 'root-vm', root_access.vm_id)
    provision_vm_credentials(tmp_path / 'child-vm', child_access.vm_id)
    root_host, root_guest = load_vm_credential_pair(tmp_path / 'root-vm', root_access.vm_id)
    child_host, child_guest = load_vm_credential_pair(tmp_path / 'child-vm', child_access.vm_id)
    root_target = HermesVMClientTLS(root_host.client, root_host.peer_name, root_host.peer_sha256, root_access)
    child_target = HermesVMClientTLS(child_host.client, child_host.peer_name, child_host.peer_sha256, child_access)
    source = HermesVMServerTLS(child_host.server, child_host.peer_sha256, child_access)
    relay = HermesWorkspaceRelay(source, 1234, target_tls=root_target)
    assert relay.target_context['root_run_id'] == root
    with pytest.raises(ValueError, match='需要根运行虚拟机'):
        HermesWorkspaceRelay(HermesVMServerTLS(root_host.server, root_host.peer_sha256, root_access), 1234, target_tls=child_target)

    async def check():
        payload = (Path(__file__).resolve().parents[2] / 'AGENTS.md').read_bytes()

        async def target(reader, writer):
            assert await reader.readexactly(4) == b'read'
            writer.write(payload)
            await writer.drain()
            await reader.read()
            writer.close()
            await writer.wait_closed()

        target_server = await asyncio.start_server(target, '127.0.0.1', 0, ssl=root_guest.server)
        target_port = target_server.sockets[0].getsockname()[1]
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        relay = HermesWorkspaceRelay(source, target_port, target_tls=root_target)
        await relay.listen(listener)
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', port, ssl=child_guest.client,
                                                            server_hostname=child_guest.peer_name)
            writer.write(b'read')
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(len(payload)), 5) == payload
            store.cancel(root, store.read_run(root)['revision'])
            assert await asyncio.wait_for(reader.read(), 5) == b''
            with pytest.raises(ValueError):
                await relay.watcher
            writer.close()
            await writer.wait_closed()
        finally:
            target_server.close()
            await target_server.wait_closed()
            if not relay.closed:
                await relay.close()

    asyncio.run(check())
