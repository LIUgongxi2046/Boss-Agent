import asyncio
import json
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services
from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_account_auth import AccountStore, account_channel_class, provision_accounts
from role_channel import RoleChannel

WORK = ROOT / "validation/.work/t27"
ACCOUNTS = ROOT / "validation/.work/application/accounts"


@asynccontextmanager
async def account_server():
    WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not (ACCOUNTS / "accounts.sqlite").exists():
        provision_accounts(ACCOUNTS)
    roles = {role: secrets.token_urlsafe(32) for role in ("BOSS", "MAINTAINER")}
    config = WebSocketConfig(host="127.0.0.1", port=0, token_issue_secret=roles["BOSS"], token_ttl_s=30)
    bus = MessageBus()
    sessions = SessionManager(WORK / "workspace")
    gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
        static_dist_path=ROOT / "design/T27/harness/dist", workspace_path=WORK / "workspace",
        config_path=WORK / "config.json", default_restrict_to_workspace=True,
        runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
    original = WebSocketChannel(config, bus, gateway=gateway)
    channel = account_channel_class(RoleChannel)(original, roles, WORK / "audit.jsonl", account_store=AccountStore(ACCOUNTS / "accounts.sqlite"))
    async with serve(channel._connection_loop, "127.0.0.1", 0, process_request=channel._dispatch_http) as server:
        port = server.sockets[0].getsockname()[1]
        yield channel, port


async def main():
    async with account_server() as (_, port):
        (WORK / "instance.json").write_text(json.dumps({"port": port}))
        print("T27独立认证服务已启动", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
