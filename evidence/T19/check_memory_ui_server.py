import argparse
import asyncio
import json
import os
import secrets
import signal
import sys
from pathlib import Path

from aiohttp import web
from lxml import etree, html

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_admin_config import memory_technical_status
from boss_runtime_records import runtime_records
from boss_workspace_api import BossWorkspaceAPI
from controls import ControlStore


async def serve(arguments):
    database = arguments.database.resolve(strict=True)
    assert database.is_relative_to(ROOT / ".work")
    build = arguments.build.resolve(strict=True)
    store = ControlStore(database)
    token = secrets.token_urlsafe(32)

    async def index(request):
        if request.query.get("page") == "A14":
            status, projection = BossWorkspaceAPI(store).serve("MAINTAINER", "/api/boss/ui/workspace/audit")
            assert status == 200 and projection["private_values_included"] is False
            document = html.Element("html", lang="zh-CN")
            head = etree.SubElement(document, "head")
            etree.SubElement(head, "meta", charset="UTF-8")
            body = etree.SubElement(document, "body")
            etree.SubElement(body, "h1").text = "获准动作记录"
            etree.SubElement(body, "pre").text = json.dumps(projection, ensure_ascii=False)
            etree.SubElement(body, "a", href="/").text = "返回记忆技术维护"
        else:
            document = html.parse(str(build / "index.html")).getroot()
            document.find("head").append(html.Element("meta", name="maintainer-token", content=token))
        return web.Response(body=html.tostring(document, encoding="utf-8", method="html"),
                            content_type="text/html", headers={"Cache-Control": "no-store"})

    async def read(request):
        if not secrets.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            raise web.HTTPUnauthorized(text="需要有效技术维护身份")
        if request.path.endswith("/memory-status"):
            if request.query:
                raise web.HTTPBadRequest(text="记忆技术状态不接受查询字段")
            result = memory_technical_status(store, "MAINTAINER")
        else:
            parameters = dict(request.query)
            if len(request.query) != len(parameters):
                raise web.HTTPBadRequest(text="查询字段不能重复")
            result = (runtime_records(store, "MAINTAINER", run_id=parameters["run_id"])
                      if set(parameters) == {"run_id"} else runtime_records(store, "MAINTAINER", query=parameters))
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/boss/ui/admin/memory-status", read)
    app.router.add_get("/api/boss/ui/runtime-records", read)
    app.router.add_static("/assets", build / "assets")
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    arguments.state.write_text(json.dumps({"url": f"http://127.0.0.1:{port}", "pid": os.getpid(),
                                           "database": str(database), "scope": "COMPONENT_TECHNICAL_READ_ONLY"}, indent=2))
    print(f"COMPONENT_TECHNICAL_READ_ONLY http://127.0.0.1:{port}", flush=True)
    stopped = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopped.set)
    try:
        await stopped.wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    asyncio.run(serve(parser.parse_args()))
