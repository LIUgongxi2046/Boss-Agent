import asyncio
import json
import secrets
import os
import sqlite3
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
from controls import ControlStore

NATIVE_ZOOM = os.environ.get("BOSS_T27_NATIVE_ZOOM") == "1"
REVIEW = os.environ.get("BOSS_T27_REVIEW") == "1"
if NATIVE_ZOOM and REVIEW:
    raise ValueError("验证环境与查看环境必须分别启动")
REVIEW_REVISION = os.environ.get("BOSS_T27_REVIEW_REVISION", "")
if REVIEW_REVISION not in ("", "flight"):
    raise ValueError("查看窗口版本无效")
REVIEW_NAME = "t27-review-flight" if REVIEW_REVISION == "flight" else "t27-review"
WORK = ROOT / ("validation/.work/t27-native-zoom/service" if NATIVE_ZOOM else
               f"validation/.work/{REVIEW_NAME}/service" if REVIEW else
               "validation/.work/t27-preview" if os.environ.get("BOSS_T27_PREVIEW") == "1" else "validation/.work/t27")
ACCOUNTS = WORK / "accounts" if NATIVE_ZOOM or REVIEW else ROOT / "validation/.work/application/accounts"
DIST = ROOT / (".work/t27-native-zoom/dist" if NATIVE_ZOOM else f".work/{REVIEW_NAME}/dist" if REVIEW else "design/T27/harness/dist")


@asynccontextmanager
async def account_server(token_ttl_s=30):
    WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
    if REVIEW and not (ACCOUNTS / "accounts.sqlite").exists():
        primary = ROOT / "validation/.work/application/accounts/accounts.sqlite"
        AccountStore(primary)
        ACCOUNTS.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(ACCOUNTS / "accounts.sqlite", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with sqlite3.connect(primary.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(ACCOUNTS / "accounts.sqlite") as target:
            source.backup(target)
    if not (ACCOUNTS / "accounts.sqlite").exists():
        provision_accounts(ACCOUNTS)
    roles = {role: secrets.token_urlsafe(32) for role in ("BOSS", "MAINTAINER")}
    config = WebSocketConfig(host="127.0.0.1", port=0, token_issue_secret=roles["BOSS"], token_ttl_s=token_ttl_s)
    bus = MessageBus()
    sessions = SessionManager(WORK / "workspace")
    gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
        static_dist_path=DIST, workspace_path=WORK / "workspace",
        config_path=WORK / "config.json", default_restrict_to_workspace=True,
        runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
    original = WebSocketChannel(config, bus, gateway=gateway)
    store = ControlStore(WORK / "business.sqlite")
    with store.connect() as db:
        exists = db.execute("SELECT 1 FROM spaces WHERE namespace='ui-check'").fetchone()
    if exists is None:
        store.initialize("ui-check")
    channel = account_channel_class(RoleChannel)(original, roles, WORK / "audit.jsonl", store, account_store=AccountStore(ACCOUNTS / "accounts.sqlite"))
    async with serve(channel._connection_loop, "127.0.0.1", 0, process_request=channel._dispatch_http) as server:
        port = server.sockets[0].getsockname()[1]
        yield channel, port


async def main():
    async with account_server(token_ttl_s=3600 if REVIEW or os.environ.get("BOSS_T27_PREVIEW") == "1" else 30) as (_, port):
        (WORK / "instance.json").write_text(json.dumps({"port": port, "pid": os.getpid(), "work": str(WORK)}))
        print("T27独立认证服务已启动", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
