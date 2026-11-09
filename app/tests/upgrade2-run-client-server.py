import asyncio
import socket
import sys
import tempfile
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_product import hermes_product_application
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services
from role_channel import RoleChannel


async def main():
    directory = Path(tempfile.mkdtemp(dir=ROOT / ".work/upgrade2-u2-07"))
    business = ControlStore(directory / "business.sqlite")
    business.initialize("ui-check")
    sessions = MemorySessionManager(directory / "workspace", business_store=business, sessions_root=directory / "sessions")
    RunStore(business.path)
    bus, config = MessageBus(), WebSocketConfig()
    gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=directory, default_restrict_to_workspace=True, config_path=directory / "config.json",
        runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, directory / "access.jsonl", business)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    port = listener.getsockname()[1]
    app = hermes_product_application(channel, business, sessions, "ui-check", public_port=port, upstream_port=1)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.SockSite(runner, listener).start()
    print(runner.addresses[0][1], flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
