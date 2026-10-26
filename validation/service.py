import argparse
import asyncio
import hmac
import json
import os

from aiohttp import web

from business import Store, require
from controls import ControlStore


def application(path, *, execution_namespace=None):
    store = ControlStore(path)
    tokens = {"BOSS": os.environ["BOSS_PROBE_TOKEN"], "MAINTAINER": os.environ["MAINTAINER_PROBE_TOKEN"]}
    failure = os.environ.get("BOSS_PROBE_FAILURE", "NONE")
    require(failure in {"NONE", "UNAVAILABLE", "TIMEOUT"}, "模拟故障配置无效")
    require(all(len(v) >= 32 for v in tokens.values()) and len(set(tokens.values())) == 2, "身份凭据无效")

    @web.middleware
    async def authenticate(request, handler):
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        role = next((name for name, token in tokens.items() if hmac.compare_digest(token, supplied)), None)
        require(role is not None, "未认证", web.HTTPUnauthorized)
        request["role"] = role
        if execution_namespace is not None:
            from boss_execution_transition import pending_transition
            with store.connect() as db:
                store.active(db, execution_namespace)
                require(pending_transition(db, execution_namespace) is None, "执行空间正在切换")
        return await handler(request)

    def role(request, expected):
        require(request["role"] == expected, "身份权限不足", web.HTTPForbidden)

    async def health(request):
        return web.json_response({"service": "boss-selection-validation", "version": "0.1.0"})

    async def initialize(request):
        role(request, "MAINTAINER")
        require(execution_namespace is None, "当前实例需要通过数据集页面管理执行空间", web.HTTPForbidden)
        p = await request.json()
        return web.json_response(store.initialize(p["namespace"]))

    async def authorize(request):
        role(request, "BOSS")
        p = await request.json()
        return web.json_response({"authorization_id": store.authorize(p["namespace"], p["action"], p["payload"])})

    async def invoke(request):
        role(request, "BOSS")
        if request.match_info["operation"] == "query_metrics":
            if failure == "UNAVAILABLE":
                raise web.HTTPServiceUnavailable(text="获准模拟业务接口当前不可用")
            if failure == "TIMEOUT":
                await asyncio.sleep(2)
        return web.json_response(store.invoke(request.match_info["operation"], await request.json()))

    async def context(request):
        role(request, "BOSS")
        return web.json_response(store.context(request.match_info["ns"]))

    async def update(request):
        kind = request.match_info["kind"]
        require(kind in ("memory", "configuration", "schedule"), "未知配置", web.HTTPNotFound)
        role(request, "BOSS" if kind == "memory" else "MAINTAINER")
        p = await request.json()
        ns = request.match_info["ns"]
        allowed = {"memory": {"text", "confirmation_state"}, "configuration": {"max_tool_rounds", "timeout", "enabled"}, "schedule": {"enabled", "canceled"}}[kind]
        require(set(p) <= allowed | {"version"}, "未知字段", web.HTTPBadRequest)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            store.active(db, ns)
            old = store.get(db, ns, kind, "current")
            require(old["version"] == p["version"], "版本冲突")
            if kind == "configuration":
                require(1 <= p.get("max_tool_rounds", old["max_tool_rounds"]) <= 12 and 1 <= p.get("timeout", old["timeout"]) <= 120, "运行限制无效", web.HTTPBadRequest)
            current = {**old, **p, "version": str(int(old["version"]) + 1)}
            if kind == "memory":
                current["memory_version"] = current["version"]
            if kind == "schedule":
                current["schedule_version"] = current["version"]
            if kind == "memory":
                require(current["confirmation_state"] in ("CONFIRMED", "DELETED"), "记忆状态无效", web.HTTPBadRequest)
                if current["confirmation_state"] == "DELETED":
                    current["text"] = ""
            store.put(db, ns, kind, "current", current)
        return web.json_response(current)

    async def read_objects(request):
        role(request, "BOSS")
        ns, kind = request.match_info["ns"], request.match_info["kind"]
        require(kind in ("task", "outbox", "notification", "feedback", "dispatch", "event", "delivery"), "对象范围无效", web.HTTPForbidden)
        with store.connect() as db:
            store.active(db, ns)
            rows = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (ns, kind)).fetchall()
        return web.json_response([json.loads(row[0]) for row in rows])

    async def trigger(request):
        role(request, "MAINTAINER")
        p = await request.json()
        return web.json_response(store.notify(request.match_info["ns"], p["event_id"]))

    async def reset(request):
        role(request, "MAINTAINER")
        require(execution_namespace is None, "当前实例需要通过数据集页面重置执行空间", web.HTTPForbidden)
        ns = request.match_info["ns"]
        p = await request.json()
        return web.json_response(store.control(ns, "reset", p))

    async def control(request):
        action = request.match_info["action"]
        maintainer = {"feedback", "clock", "event"}
        boss = {"decide", "revoke", "withdraw", "search", "private_calendar", "reference_status", "reminder", "rules"}
        require(action in maintainer | boss, "未知控制操作", web.HTTPNotFound)
        role(request, "MAINTAINER" if action in maintainer else "BOSS")
        return web.json_response(store.control(request.match_info["ns"], action, await request.json()))

    app = web.Application(middlewares=[authenticate], client_max_size=1024*1024)
    app.add_routes([web.get("/health", health), web.post("/datasets", initialize), web.post("/authorizations", authorize), web.post("/operations/{operation}", invoke), web.get("/spaces/{ns}/context", context), web.put("/spaces/{ns}/{kind}", update), web.get("/spaces/{ns}/objects/{kind}", read_objects), web.post("/spaces/{ns}/events", trigger), web.post("/spaces/{ns}/reset", reset), web.post("/spaces/{ns}/controls/{action}", control)])
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--port", type=int, default=8871)
    args = parser.parse_args()
    web.run_app(application(args.database), host="127.0.0.1", port=args.port, access_log=None)
