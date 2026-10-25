import argparse
import asyncio
import json
import os
import secrets
import signal
import shutil
import sys
from pathlib import Path

from aiohttp import web
from lxml.html import fromstring, tostring
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))

from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from controls import ControlStore
from model_probe import BusinessTool


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--work",type=Path,default=ROOT/".work/w2-checks/skill-ui")
    args=parser.parse_args()
    work=args.work.resolve()
    if not work.is_relative_to(ROOT/".work/w2-checks"):
        raise ValueError("验证目录必须属于W2隔离目录")
    work.mkdir(parents=True,exist_ok=True)
    workspace=work/"workspace"
    if not (workspace/"skills").exists():
        shutil.copytree(ROOT/"agent/skills",workspace/"skills")
    config_path=work/"config.json"
    if not config_path.is_file():
        config=Config()
        config.agents.defaults.workspace=str(workspace)
        save_config(config,config_path)
    store=ControlStore(work/"business.sqlite")
    with store.connect() as db:
        initialized=db.execute("SELECT 1 FROM spaces WHERE namespace='ui-check'").fetchone()
    if initialized is None:
        store.initialize("ui-check")
    registry=ToolRegistry()
    assets=json.loads((ROOT/"specs/agent-assets.json").read_text())
    for item in assets["tools"]:
        registry.register(BusinessTool(item["tool_id"],store,{"request_id":"w2-sop-ui","owner_id":"boss-1","execution_namespace":"ui-check",
            "dataset_id":"selection","dataset_version":"1","session_id":"w2-sop-ui"},{},[]))
    loader=SkillsLoader(workspace,disabled_skills=set(load_config(config_path).agents.defaults.disabled_skills))
    methods=BossSkillDrafts(store,BossSkillCatalog(loader,registry),config_path)
    token=secrets.token_urlsafe(32)
    sessions={token:"MAINTAINER"}

    def role(request):
        credential=request.headers.get("Authorization","")
        if not credential.startswith("Bearer ") or credential[7:] not in sessions:
            raise web.HTTPUnauthorized(text="当前验证会话未认证")
        return sessions[credential[7:]]

    def query(request,fields):
        if set(request.query)!=set(fields) or any(len(request.query.getall(key))!=1 or not request.query[key] for key in fields):
            raise web.HTTPBadRequest(text="方法查询参数无效")
        return {key:request.query[key] for key in fields}

    @web.middleware
    async def errors(request,handler):
        try:
            return await handler(request)
        except web.HTTPException as failure:
            return web.json_response({"error":failure.text},status=failure.status)

    async def view(request):
        current=role(request)
        values=query(request,{"sop_id"})
        return web.json_response(methods.read(current,values["sop_id"]))

    async def history(request):
        values=query(request,{"sop_id","history_id"})
        return web.json_response(methods.read_history(role(request),**values))

    async def receipt(request):
        values=query(request,{"action","client_request_id"})
        return web.json_response(methods.operation_status(role(request),**values))

    async def command(request):
        current=role(request)
        payload=await request.json()
        if not isinstance(payload,dict) or set(payload)!={"action","payload"}:
            raise web.HTTPBadRequest(text="方法操作请求无效")
        return web.json_response(methods.execute(current,payload["action"],payload["payload"]))

    async def revoke(request):
        role(request)
        del sessions[request.headers["Authorization"][7:]]
        return web.json_response({"revoked":True})

    async def index(request):
        document=fromstring((work/"dist/index.html").read_text())
        document.xpath('//meta[@name="maintainer-token"]')[0].set("content",token)
        return web.Response(text=tostring(document,encoding="unicode"),content_type="text/html",headers={"Cache-Control":"no-store"})

    app=web.Application(middlewares=[errors],client_max_size=160000)
    app.router.add_get("/api/boss/ui/admin/sop-method",view)
    app.router.add_get("/api/boss/ui/admin/sop-history",history)
    app.router.add_get("/api/boss/ui/admin/sop-operation-status",receipt)
    app.router.add_post("/component/sop-command",command)
    app.router.add_post("/component/session/revoke",revoke)
    app.router.add_get("/",index)
    app.router.add_static("/assets",work/"dist/assets")
    runner=web.AppRunner(app,access_log=None)
    await runner.setup()
    site=web.TCPSite(runner,"127.0.0.1",0)
    await site.start()
    port=site._server.sockets[0].getsockname()[1]
    (work/"server.json").write_text(json.dumps({"url":"http://127.0.0.1:"+str(port),"pid":os.getpid(),"external_request_count":0}))
    print(json.dumps({"url":"http://127.0.0.1:"+str(port),"pid":os.getpid(),"external_request_count":0}),flush=True)
    stop=asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,stop.set)
    await stop.wait()
    await runner.cleanup()


asyncio.run(main())
