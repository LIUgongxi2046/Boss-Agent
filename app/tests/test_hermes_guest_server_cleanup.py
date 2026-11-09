import asyncio
import socket

import pytest
from aiohttp import web

from hermes_guest_control import HermesGuestServer


def test_guest_server_closes_listener_when_runner_cleanup_fails():
    async def run():
        app = web.Application()

        async def fail_cleanup(application):
            raise RuntimeError("技术清理检查")

        app.on_cleanup.append(fail_cleanup)
        runner = web.AppRunner(app)
        await runner.setup()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = await asyncio.get_running_loop().create_server(runner.server, sock=listener)
        resource = HermesGuestServer(runner, server)
        with pytest.raises(RuntimeError, match="技术清理检查"):
            await resource.cleanup()
        assert not server.is_serving()
        assert listener.fileno() == -1

    asyncio.run(run())
