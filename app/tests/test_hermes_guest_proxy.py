import asyncio
import socket
import sys

import pytest

from hermes_guest_proxy import HermesGuestProxyServer, HermesGuestRuntimeProxy, relay_streams
from test_hermes_vm_channel import contexts


def test_relay_moves_bytes_between_real_socket_pairs():
    async def exercise():
        left, left_peer = socket.socketpair()
        right, right_peer = socket.socketpair()
        for connection in (left, left_peer, right, right_peer):
            connection.setblocking(False)
        left_reader, left_writer = await asyncio.open_connection(sock=left)
        right_reader, right_writer = await asyncio.open_connection(sock=right)
        task = asyncio.create_task(relay_streams(left_reader, left_writer, right_reader, right_writer))
        loop = asyncio.get_running_loop()
        try:
            await loop.sock_sendall(left_peer, b"runtime request")
            assert await asyncio.wait_for(loop.sock_recv(right_peer, 64), 5) == b"runtime request"
            await loop.sock_sendall(right_peer, b"runtime response")
            assert await asyncio.wait_for(loop.sock_recv(left_peer, 64), 5) == b"runtime response"
        finally:
            left_peer.close()
            right_peer.close()
            await asyncio.wait_for(task, 5)

    asyncio.run(exercise())


def test_guest_proxy_rejects_non_linux_host(tmp_path):
    if sys.platform == "linux":
        pytest.skip("此检查针对非 Linux 宿主")
    _, client_context, host_hash, _ = contexts(tmp_path)
    proxy = HermesGuestRuntimeProxy(client_context, "localhost", host_hash, 1024)
    with socket.socket() as listener:
        with pytest.raises(ValueError, match="需要 Linux Virtio Socket"):
            asyncio.run(proxy.listen(listener))


def test_proxy_server_closes_live_connections():
    async def exercise():
        writers, tasks, state = set(), set(), {"closed": False}
        accepted = asyncio.Event()
        async def handle(reader, writer):
            task = asyncio.current_task()
            tasks.add(task)
            writers.add(writer)
            accepted.set()
            try:
                await reader.read()
            finally:
                writers.discard(writer)
                tasks.discard(task)
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        managed = HermesGuestProxyServer(server, writers, tasks, state)
        reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        await asyncio.wait_for(accepted.wait(), 5)
        managed.close()
        await asyncio.wait_for(managed.wait_closed(), 5)
        assert await asyncio.wait_for(reader.read(), 5) == b""
        assert not writers and not tasks
        writer.close()
        await writer.wait_closed()
    asyncio.run(exercise())
