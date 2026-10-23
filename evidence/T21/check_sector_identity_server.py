import asyncio
import json
import os
import secrets
import signal
import sys
from pathlib import Path

from aiohttp import web
from lxml.html import fromstring, tostring

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))

from boss_sector_api import BossSectorAPI
from controls import ControlStore


async def main():
    work=ROOT/".work/w2-checks/sector-ui"
    store=ControlStore(work/"sector.sqlite")
    with store.connect() as db:
        initialized=db.execute("SELECT 1 FROM spaces WHERE namespace='ui-check'").fetchone()
    if initialized is None:
        store.initialize("ui-check")
    api=BossSectorAPI(store)
    token=secrets.token_urlsafe(32)
    valid=True

    def authenticate(request):
        if not valid or not secrets.compare_digest(request.headers.get("Authorization",""),"Bearer "+token):
            raise web.HTTPUnauthorized(text="需要当前老板验证身份")

    async def index(request):
        document=fromstring((work/"dist/index.html").read_text())
        document.xpath('//meta[@name="boss-token"]')[0].set("content",token)
        return web.Response(text=tostring(document,encoding="unicode"),content_type="text/html",headers={"Cache-Control":"no-store"})

    async def read(request):
        authenticate(request)
        status,view=api.serve("BOSS",request.query_string)
        return web.json_response(view,status=status,headers={"Cache-Control":"no-store"})

    async def revoke(request):
        nonlocal valid
        authenticate(request)
        valid=False
        return web.json_response({"revoked":True})

    app=web.Application()
    app.router.add_get("/",index)
    app.router.add_get("/api/boss/ui/sector",read)
    app.router.add_post("/component/session/revoke",revoke)
    app.router.add_static("/assets",work/"dist/assets")
    runner=web.AppRunner(app,access_log=None)
    await runner.setup()
    site=web.TCPSite(runner,"127.0.0.1",0)
    await site.start()
    state={"url":"http://127.0.0.1:"+str(runner.addresses[0][1]),"pid":os.getpid(),"scope":"SECTOR_READ_AND_ACTUAL_LOCAL_IDENTITY"}
    (work/"server.json").write_text(json.dumps(state))
    print(json.dumps(state),flush=True)
    stop=asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,stop.set)
    await stop.wait()
    await runner.cleanup()


asyncio.run(main())
