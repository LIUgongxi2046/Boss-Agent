import json
import asyncio
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource
from jsonschema import Draft202012Validator, FormatChecker

from agent_run_broker import fail
from hermes_run_recovery import HermesRunRecovery
from role_channel import RoleChannel


PARAMS = web.RequestKey("agent_recovery_route_params", dict)
INSTALLED = web.AppKey("agent_recovery_routes_installed", bool)
SCHEMA = json.loads((Path(__file__).parent / "agent_run_recovery_schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATORS = {name: Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()) for name in ("receipt", "recheck_request", "recheck_receipt")}
RUN_ID = Draft202012Validator({"type": "string", "format": "uuid"}, format_checker=FormatChecker())


def install_run_recovery_routes(app, channel, recovery, *, public_port, vm_manager=None, workspace_root=None):
    if type(public_port) is not int or not 1 <= public_port <= 65535:
        raise ValueError("运行恢复服务端口无效")
    if not isinstance(channel, RoleChannel) or not isinstance(recovery, HermesRunRecovery) or recovery.channel is not channel:
        raise ValueError("运行恢复缺少身份或范围服务")
    if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != recovery.store.path.resolve() or channel.gateway.session_manager is not recovery.scope.sources.sessions:
        raise ValueError("运行恢复服务不属于同一环境")
    if vm_manager is not None:
        from hermes_vm_manager import HermesVMManager
        if not isinstance(vm_manager, HermesVMManager) or not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
            raise ValueError("运行恢复缺少受管虚拟机配置")
    host = "127.0.0.1:" + str(public_port)
    origin = "http://" + host

    def run_id(request):
        value = request[PARAMS]["run_id"]
        if not RUN_ID.is_valid(value) or str(UUID(value)) != value:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行编号无效")
        return value

    async def recover(request):
        channel.require_run_api_role(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行恢复请求参数无效")
        if request.content_type != "application/json":
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行恢复请求格式无效")
        if request.content_length is not None and request.content_length > 131072:
            fail(web.HTTPRequestEntityTooLarge, "INPUT_TOO_LARGE", "请求超过大小限制", actual_size=request.content_length)
        body = await request.json()
        if body != {}:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "运行恢复请求字段无效")
        identifier = run_id(request)
        channel.require_run_api_role(request)
        with recovery.store.connect() as db:
            db.execute("BEGIN")
            from boss_simulation_api import _context
            context = _context(db)
            row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=? AND actor_id=? AND space_id=?", (identifier, context["owner_id"], context["namespace"])).fetchone()
            if row is None or row[3] is None or row[4] is None:
                fail(web.HTTPNotFound, "NOT_FOUND", "运行不存在")
            channel.require_run_subscription(request, row[2])
            proof = recovery.scope.prove_in_transaction(db, row[2], json.loads(row[3]))
            if (proof.owner_id, proof.namespace) != (context["owner_id"], context["namespace"]) or json.loads(json.dumps(asdict(proof))) != json.loads(row[4]):
                fail(web.HTTPConflict, "REVISION_CONFLICT", "运行来源范围已经变化")
            from hermes_source_invalidation import require_source_cleanup_complete
            require_source_cleanup_complete(db, identifier)
            from agent_run_memory_guard import require_current_run_memory_in_transaction
            require_current_run_memory_in_transaction(db, recovery.scope.store, identifier)
            channel.require_run_subscription(request, row[2])
        if vm_manager is None:
            fail(web.HTTPServiceUnavailable, "RECOVERY_INTEGRATION_NOT_READY", "运行恢复缺少受管虚拟机")
        result = await asyncio.to_thread(recovery.recover_vm_expired, request, identifier, vm_manager, workspace_root)
        if not VALIDATORS["receipt"].is_valid(result):
            raise ValueError("运行恢复回执不可核查")
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def recheck(request):
        channel.require_run_api_role(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "终态重新核查请求参数无效")
        if request.content_type != "application/json":
            fail(web.HTTPBadRequest, "INVALID_INPUT", "终态重新核查请求格式无效")
        if request.content_length is not None and request.content_length > 131072:
            fail(web.HTTPRequestEntityTooLarge, "INPUT_TOO_LARGE", "请求超过大小限制", actual_size=request.content_length)
        body = await request.json()
        if not VALIDATORS["recheck_request"].is_valid(body):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "终态重新核查请求字段无效")
        run_id(request)
        fail(web.HTTPServiceUnavailable, "COMPLETION_RECHECK_NOT_READY", "终态重新核查尚未接入完整依赖服务")

    paths = (("/api/v2/runs/{run_id}/recover-expired", recover), ("/api/v2/runs/{run_id}/completion-recheck", recheck))
    existing = {resource.canonical for resource in app.router.resources()}
    if INSTALLED in app or any(path in existing for path, _ in paths):
        raise ValueError("运行恢复路由已经注册")
    resources = []
    for path, handler in paths:
        resource = DynamicResource(path)
        resource.add_route("POST", handler)
        resources.append(resource)

    @web.middleware
    async def dispatch(request, handler):
        for resource in resources:
            match, allowed = await resource.resolve(request)
            if match is None:
                if allowed:
                    raise web.HTTPMethodNotAllowed(request.method, allowed)
                continue
            request_origin = request.headers.get("Origin")
            if request.headers.get("Host") != host or request_origin != origin or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                fail(web.HTTPForbidden, "FORBIDDEN", "运行恢复请求来源无效")
            request[PARAMS] = dict(match)
            return await match.handler(request)
        return await handler(request)

    app.middlewares.append(dispatch)
    app[INSTALLED] = True
