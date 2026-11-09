import json
from pathlib import Path
from uuid import UUID

from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource
from jsonschema import Draft202012Validator, FormatChecker

from agent_run_broker import fail
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from agent_source_history import AgentSourceHistory
from role_channel import RoleChannel


PARAMS = web.RequestKey("agent_source_history_params", dict)
INSTALLED = web.AppKey("agent_source_history_installed", bool)
UUID_VALIDATOR = Draft202012Validator({"type": "string", "format": "uuid"}, format_checker=FormatChecker())
SCHEMA = json.loads((Path(__file__).parent / "agent_source_history_schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def install_source_history_routes(app, channel, runs, scope, *, public_port):
    if type(public_port) is not int or not 1 <= public_port <= 65535:
        raise ValueError("来源历史服务端口无效")
    if not isinstance(channel, RoleChannel) or not isinstance(runs, RunStore) or not isinstance(scope, RunScopeService):
        raise ValueError("来源历史需要产品身份和会话范围")
    if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != runs.path.resolve() or channel.gateway.session_manager is not scope.sources.sessions:
        raise ValueError("来源历史服务环境不一致")
    history = AgentSourceHistory(runs, scope)
    host, origin = "127.0.0.1:" + str(public_port), "http://127.0.0.1:" + str(public_port)
    path = "/api/v2/runs/{run_id}/source-history/{event_id}"
    if INSTALLED in app or path in {resource.canonical for resource in app.router.resources()}:
        raise ValueError("来源历史路由已经注册")

    async def read(request):
        params = request[PARAMS]
        for key in ("run_id", "event_id"):
            value = params[key]
            if not UUID_VALIDATOR.is_valid(value) or str(UUID(value)) != value:
                fail(web.HTTPBadRequest, "INVALID_INPUT", "运行或结果编号无效")
        if set(request.query) != {"source_id", "version"} or any(len(request.query.getall(key)) != 1 for key in ("source_id", "version")):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "需要来源编号和版本")
        source_id, version = request.query["source_id"], request.query["version"]
        if not source_id.strip() or len(source_id) > 160 or not version.isascii() or not version.isdecimal() or len(version) > 32 or str(int(version)) != version:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "来源编号或版本无效")
        channel.require_run_api_role(request)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT conversation_id FROM agent_runs WHERE run_id=?", (params["run_id"],)).fetchone()
            if row is None:
                fail(web.HTTPNotFound, "NOT_FOUND", "运行不存在")
            channel.require_run_subscription(request, row[0])
            result = history.read_in_transaction(db, params["run_id"], params["event_id"], source_id, version)
            channel.require_run_subscription(request, row[0])
        VALIDATOR.validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    endpoint = DynamicResource(path)
    endpoint.add_route("GET", read)

    @web.middleware
    async def dispatch(request, handler):
        match, allowed = await endpoint.resolve(request)
        if match is None:
            if allowed:
                raise web.HTTPMethodNotAllowed(request.method, allowed)
            return await handler(request)
        if request.headers.get("Host") != host or request.headers.get("Origin") not in (None, origin) or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            fail(web.HTTPForbidden, "FORBIDDEN", "来源历史请求来源无效")
        channel.require_run_api_role(request)
        request[PARAMS] = dict(match)
        return await match.handler(request)

    app.middlewares.append(dispatch)
    app[INSTALLED] = True
