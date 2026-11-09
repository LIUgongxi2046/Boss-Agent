import json
import sqlite3
from decimal import Decimal

from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource

from agent_chat_budget import AgentChatBudget
from agent_run_broker import fail


async def read_budget_payload(request):
    if request.query or request.content_type != "application/json":
        fail(web.HTTPBadRequest, "INVALID_INPUT", "聊天预算请求格式无效")
    raw = await request.read()
    source = raw.decode("utf-8", errors="replace")
    if source.encode("utf-8") != raw:
        fail(web.HTTPBadRequest, "INVALID_INPUT", "聊天预算请求格式无效")
    with sqlite3.connect(":memory:") as db:
        if db.execute("SELECT json_valid(?)", (source,)).fetchone()[0] != 1:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "聊天预算请求格式无效")
        containers = db.execute("SELECT count(*) FROM json_tree(?) WHERE type IN ('object', 'array')", (source,)).fetchone()[0]
        if containers > 2:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "聊天预算请求格式无效")
        duplicate = db.execute("SELECT 1 FROM json_tree(?) WHERE parent IS NOT NULL GROUP BY parent, key HAVING count(*) > 1 LIMIT 1", (source,)).fetchone()
        if duplicate is not None:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "聊天预算请求格式无效")
    payload = json.loads(source, parse_int=lambda value: int(value) if len(value) <= 1000 else Decimal(value))
    if not isinstance(payload, dict) or set(payload) != {"request_key", "expected_version", "budget"}:
        fail(web.HTTPBadRequest, "INVALID_INPUT", "聊天预算请求格式无效")
    return payload


def install_chat_budget_routes(app, budget_service, *, public_port):
    if not isinstance(app, web.Application) or not isinstance(budget_service, AgentChatBudget):
        raise ValueError("聊天预算路由环境无效")
    if type(public_port) is not int or not 1 <= public_port <= 65535:
        raise ValueError("产品端口无效")
    expected_host = "127.0.0.1:" + str(public_port)
    expected_origin = "http://" + expected_host

    async def read(request):
        budget_service.require_maintainer(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "聊天预算请求格式无效")
        return web.json_response(budget_service.read_configuration(request), headers={"Cache-Control": "no-store"})

    async def configure(request):
        budget_service.require_maintainer(request)
        payload = await read_budget_payload(request)
        result = budget_service.configure(request, payload["request_key"], payload["expected_version"], payload["budget"])
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    resource = DynamicResource("/api/v2/settings/chat-run-budget")
    resource.add_route("GET", read)
    resource.add_route("PUT", configure)

    @web.middleware
    async def dispatch(request, handler):
        match, allowed = await resource.resolve(request)
        if match is None:
            if allowed:
                raise web.HTTPMethodNotAllowed(request.method, allowed)
            return await handler(request)
        origin = request.headers.get("Origin")
        if request.headers.get("Host") != expected_host or origin not in (None, expected_origin) or request.method != "GET" and origin != expected_origin or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
            raise web.HTTPForbidden(text="聊天预算请求来源无效")
        return await match.handler(request)

    app.middlewares.append(dispatch)
