import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path

from aiohttp import web
from lxml import html

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_runtime_records import runtime_records
from controls import ControlStore


async def serve(arguments):
    database = arguments.database.resolve(strict=True)
    build = arguments.build.resolve(strict=True)
    store = ControlStore(database)
    token = secrets.token_urlsafe(32)

    async def index(request):
        document = html.parse(str(build / "index.html"))
        document.getroot().find("head").append(html.Element("meta", name="maintainer-token", content=token))
        return web.Response(body=html.tostring(document, encoding="utf-8", method="html"),
                            content_type="text/html", headers={"Cache-Control": "no-store"})

    async def records(request):
        if not secrets.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            raise web.HTTPUnauthorized(text="需要有效技术维护身份")
        parameters = dict(request.query)
        if len(request.query) != len(parameters):
            raise web.HTTPBadRequest(text="查询字段不能重复")
        if set(parameters) == {"run_id"}:
            result = runtime_records(store, "MAINTAINER", run_id=parameters["run_id"])
        else:
            result = runtime_records(store, "MAINTAINER", query=parameters)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/boss/ui/runtime-records", records)
    app.router.add_static("/assets", build / "assets")
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    arguments.state.write_text(json.dumps({"url": f"http://127.0.0.1:{port}", "database": str(database),
                                           "scope": "COMPONENT_METADATA_READ_ONLY"}, indent=2))
    print(f"COMPONENT_METADATA_READ_ONLY http://127.0.0.1:{port}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    asyncio.run(serve(parser.parse_args()))
