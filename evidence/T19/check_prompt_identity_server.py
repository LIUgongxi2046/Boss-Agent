import argparse
import asyncio
import json
import secrets
import signal
import sqlite3
import sys
from pathlib import Path

from aiohttp import web
from lxml import html

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_page_api import BossPageAPI
from controls import ControlStore


async def serve(arguments):
    source = arguments.database.resolve(strict=True)
    arguments.copy_to.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(arguments.copy_to) as copied:
            original.backup(copied)
    store = ControlStore(arguments.copy_to)
    build = arguments.build.resolve(strict=True)
    token = secrets.token_urlsafe(32)
    valid = True

    def authenticate(request):
        if not valid or not secrets.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            raise web.HTTPUnauthorized(text="需要有效技术维护身份")

    async def index(request):
        document = html.parse(str(build / "index.html")).getroot()
        document.find("head").append(html.Element("meta", name="maintainer-token", content=token))
        return web.Response(body=html.tostring(document, encoding="utf-8", method="html"),
                            content_type="text/html", headers={"Cache-Control": "no-store"})

    async def read(request):
        authenticate(request)
        if request.path.endswith("prompt-versions") and request.query:
            raise web.HTTPBadRequest(text="Prompt投影不接受查询字段")
        status, result = BossPageAPI(store).serve("MAINTAINER", request.path, request.query_string)
        return web.json_response(result, status=status, headers={"Cache-Control": "no-store"})

    async def revoke(request):
        nonlocal valid
        authenticate(request)
        valid = False
        return web.json_response({"session_revoked": True})

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/boss/ui/workspace/prompt-versions", read)
    app.router.add_get("/api/boss/ui/operation-status", read)
    app.router.add_post("/component/session/revoke", revoke)
    app.router.add_static("/assets", build / "assets")
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = "http://127.0.0.1:" + str(runner.addresses[0][1])
    arguments.state.write_text(json.dumps({"url": url, "scope": "PROMPT_COMPONENT_SESSION_READ_ONLY"}))
    print(url, flush=True)
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--copy-to", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    asyncio.run(serve(parser.parse_args()))
