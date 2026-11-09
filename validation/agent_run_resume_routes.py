import json
from pathlib import Path
from uuid import UUID

from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource
from jsonschema import Draft202012Validator, FormatChecker

from agent_run_broker import RunBroker, RunIdentity, fail
from agent_run_scope import RunScopeService
from role_channel import RoleChannel


PARAMS = web.RequestKey("agent_resume_route_params", dict)
INSTALLED = web.AppKey("agent_resume_routes_installed", bool)
SCHEMA = json.loads((Path(__file__).parent / "agent_run_resume_schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATORS = {name: Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()) for name in ("request", "receipt", "status", "request_receipt")}
RUN_ID = Draft202012Validator({"type": "string", "format": "uuid"}, format_checker=FormatChecker())


def install_run_resume_routes(app, channel, broker, *, public_port):
    if type(public_port) is not int or not 1 <= public_port <= 65535:
        raise ValueError("运行恢复服务端口无效")
    if not isinstance(channel, RoleChannel) or not isinstance(broker, RunBroker) or not isinstance(broker.scope_service, RunScopeService):
        raise ValueError("运行恢复缺少身份或来源范围服务")
    if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != broker.store.path.resolve() or channel.gateway.session_manager is not broker.scope_service.sources.sessions:
        raise ValueError("运行恢复服务不属于同一环境")
    host = "127.0.0.1:" + str(public_port)
    origin = "http://" + host

    def run_id(request):
        value = request[PARAMS]["run_id"]
        if not RUN_ID.is_valid(value) or str(UUID(value)) != value:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行编号无效")
        return value

    def identity(request, identifier):
        channel.require_run_api_role(request)
        with broker.store.connect() as db:
            db.execute("BEGIN")
            from boss_simulation_api import _context
            context = _context(db)
            row = db.execute("SELECT conversation_id,selected_refs FROM agent_runs WHERE run_id=? AND actor_id=? AND space_id=?", (identifier, context["owner_id"], context["namespace"])).fetchone()
            if row is None or row[1] is None:
                fail(web.HTTPNotFound, "NOT_FOUND", "运行不存在")
            channel.require_run_subscription(request, row[0])
            refs = json.loads(row[1])
            proof = broker.scope_service.prove_in_transaction(db, row[0], refs)
            if (proof.owner_id, proof.namespace) != (context["owner_id"], context["namespace"]):
                fail(web.HTTPForbidden, "SCOPE_CHANGED", "来源范围已经变化")
            channel.require_run_subscription(request, row[0])
            return RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}), frozenset(refs), verify=lambda: channel.require_run_subscription(request, row[0]))

    def no_query(request):
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行恢复请求参数无效")

    def response(name, value):
        VALIDATORS[name].validate(value)
        return web.json_response(value, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def status(request):
        no_query(request)
        identifier = run_id(request)
        return response("status", broker.waiting_resume_inspection(identity(request, identifier), identifier))

    async def receipt(request):
        no_query(request)
        identifier = run_id(request)
        key = request[PARAMS]["request_key"]
        if not key.strip() or len(key) > 128:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行恢复请求编号无效")
        inspection = broker.waiting_resume_inspection(identity(request, identifier), identifier, request_key=key)
        if inspection["original_receipt"] is None:
            fail(web.HTTPNotFound, "NOT_FOUND", "运行恢复原请求不存在")
        return response("request_receipt", {"run_id": identifier, "request_key": key, "outcome": "RECORDED", "receipt": inspection["original_receipt"]})

    async def resume(request):
        no_query(request)
        if request.content_type != "application/json":
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行恢复请求格式无效")
        if request.content_length is not None and request.content_length > 131072:
            fail(web.HTTPRequestEntityTooLarge, "INPUT_TOO_LARGE", "请求超过大小限制", actual_size=request.content_length)
        payload = await request.json()
        if not VALIDATORS["request"].is_valid(payload) or type(payload["expected_revision"]) is not int or type(payload["expected_goal_revision"]) is not int:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行恢复请求字段无效")
        identifier = run_id(request)
        result = broker.requeue_waiting(identity(request, identifier), identifier, payload["expected_revision"], payload["expected_goal_revision"], payload["request_key"], request=request)
        return response("receipt", result)

    definitions = (("/api/v2/runs/{run_id}/resume", "POST", resume),
                   ("/api/v2/runs/{run_id}/resume-status", "GET", status),
                   ("/api/v2/runs/{run_id}/resume-requests/{request_key}", "GET", receipt))
    existing = {resource.canonical for resource in app.router.resources()}
    if INSTALLED in app or any(path in existing for path, _, _ in definitions):
        raise ValueError("运行恢复路由已经注册")
    endpoints = []
    for path, method, handler in definitions:
        resource = DynamicResource(path)
        resource.add_route(method, handler)
        endpoints.append(resource)

    @web.middleware
    async def dispatch(request, handler):
        for endpoint in endpoints:
            match, allowed = await endpoint.resolve(request)
            if match is None:
                if allowed:
                    raise web.HTTPMethodNotAllowed(request.method, allowed)
                continue
            request_origin = request.headers.get("Origin")
            if request.headers.get("Host") != host or request_origin not in (None, origin) or request.method == "POST" and request_origin != origin or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                fail(web.HTTPForbidden, "FORBIDDEN", "运行恢复请求来源无效")
            channel.require_run_api_role(request)
            request[PARAMS] = dict(match)
            return await match.handler(request)
        return await handler(request)

    app.middlewares.append(dispatch)
    app[INSTALLED] = True
