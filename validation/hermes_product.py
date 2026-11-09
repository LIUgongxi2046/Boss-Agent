from dataclasses import dataclass

from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource

from agent_chat_budget import AgentChatBudget
from agent_chat_budget_routes import install_chat_budget_routes
from agent_run_api import product_application
from agent_run_broker import RunBroker, fail
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_execution_scope import NAMESPACE
from hermes_bridge import EngineEventSink, EngineProcessConfig, HermesBridge
from hermes_intents import install_owner_decision
from hermes_plan_routes import install_plan_execution
from hermes_skill_routes import install_skill_maintenance
from hermes_run_recovery import HermesRunRecovery
from hermes_process_evidence import HermesProcessEvidence
from hermes_process_manager import HermesProcessManager
from hermes_runtime_transport import HermesExecutionLifecycle
from hermes_legacy_routes import install_legacy_routes
from role_channel import RoleChannel


def require_root_file_budget_in_transaction(store, db, run_id, budget):
    if not isinstance(store, RunStore) or not db.in_transaction or not isinstance(budget, dict):
        raise ValueError("根运行文件额度需要运行事务")
    main = db.execute("PRAGMA database_list").fetchone()
    if main is None or main[1] != "main" or main[2] != str(store.path.resolve()):
        raise ValueError("根运行文件额度数据库不一致")
    root = store.require_active_lineage(db, run_id)
    file_budget = db.execute("SELECT max_files,max_bytes FROM agent_file_budgets WHERE root_run_id=?", (root,)).fetchone()
    if file_budget is None or type(budget.get("files")) is not int or type(budget.get("file_bytes")) is not int or not 0 < budget["files"] <= file_budget[0] or not 0 < budget["file_bytes"] <= file_budget[1]:
        raise ValueError("虚拟机运行文件额度与根运行不一致")
    return root


@dataclass(frozen=True)
class HermesProductServices:
    store: RunStore
    scope: RunScopeService
    broker: RunBroker
    bridge: HermesBridge
    recovery: HermesRunRecovery
    chat_budget: AgentChatBudget | None = None
    artifact_workspace: object | None = None

    def require_selected_meeting_method(self, sink, context=None):
        selection_service = self.broker.method_selection
        if selection_service is None:
            raise web.HTTPServiceUnavailable(text="运行方法选择服务尚未准备")
        selected = selection_service.require_current(sink)
        if selected["sop_id"] != "SOP04":
            raise web.HTTPConflict(text="当前运行选择的方法不适用于会议准备")
        if context is not None and context.skill_reference["method"] != {key: selected[key] for key in ("sop_id", "name", "version", "content_sha256")}:
            raise web.HTTPConflict(text="会议上下文与所选方法版本不一致")
        return selected

    def assemble_meeting_context(self, authority):
        from hermes_context_tools import HermesContextTools
        from hermes_memory_adapter import HermesMemoryAdapter
        from hermes_run_authority import HermesRunAuthority
        from hermes_skill_adapter import HermesSkillAdapter
        if not isinstance(authority, HermesRunAuthority) or authority.services is not self:
            raise ValueError("会议上下文需要当前产品运行授权")
        authority.require()
        self.require_selected_meeting_method(authority.sink)
        skills = self.recovery.channel.skills
        if skills is None:
            raise web.HTTPServiceUnavailable(text="当前方法服务尚未准备")
        memory = HermesMemoryAdapter(self.scope.store, self.scope, run_gate=authority.sink)
        skill = HermesSkillAdapter(self.scope.store, self.scope, skills.catalog, skills.drafts,
                                   run_gate=authority.sink, sop_id="SOP04")
        context = HermesContextTools.assemble(memory, skill)
        self.require_selected_meeting_method(authority.sink, context)
        authority.require()
        return context

    def register_process_start(self, request, evidence, run_id, owner, epoch, plan_digest, budget, request_key, request_digest, *, vm_access=None):
        from agent_run_dispatcher import AgentRunDispatcher
        from hermes_vm_identity import HermesVMRunAccess
        if not isinstance(evidence, HermesProcessEvidence) or evidence.store.path.resolve() != self.store.path.resolve():
            raise ValueError("进程记录与产品运行服务不属于同一数据库")
        if vm_access is not None and (not isinstance(vm_access, HermesVMRunAccess) or (vm_access.run_id, vm_access.request_key, vm_access.owner, vm_access.epoch) != (run_id, request_key, owner, epoch)):
            raise ValueError("虚拟机绑定与产品派发不匹配")
        with AgentRunDispatcher(self).launch_transaction(request, run_id, owner, epoch, plan_digest, budget) as db:
            row = db.execute("SELECT actor_id,space_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("运行身份不可核查")
            if vm_access is not None:
                from hermes_cpu_budget import HermesCPUBudget
                root = require_root_file_budget_in_transaction(self.store, db, run_id, budget)
                cpu_budget = HermesCPUBudget(self.store)
                unit = evidence.record_vm_start_in_transaction(db, vm_access.bindings, run_id, request_key, request_digest,
                    owner, epoch, row[0], row[1], vm_access.vm_id, vm_access.boot_id, vm_access.workspace)
                if root == run_id:
                    cpu_budget.configure_in_transaction(db, run_id, owner, epoch, budget["cpu_seconds"] * 1_000_000_000)
                from hermes_cpu_budget import vm_cpu_allocation_seconds
                cpu_budget.reserve_in_transaction(db, vm_access, vm_cpu_allocation_seconds(budget) * 1_000_000_000)
                return unit
            return evidence.record_start_in_transaction(db, run_id, request_key, request_digest, owner, epoch, row[0], row[1])

    def start(self, request, sink, budget, process_config):
        binding = self.recovery.authorize_start(request, sink)
        return self.bridge.start(run_id=binding["run_id"], lease_epoch=binding["lease_epoch"], budget=budget,
                                 process_config=process_config, run_sink=sink,
                                 actor_id=binding["actor_id"], space_id=binding["space_id"])

    async def execute(self, request, sink, budget, process_config, lifecycle, listener, *, plan_digest, request_key, request_digest, bootstrap):
        if not isinstance(sink, EngineEventSink) or not isinstance(process_config, EngineProcessConfig) or not isinstance(lifecycle, HermesExecutionLifecycle):
            raise ValueError("产品执行缺少运行配置或执行服务")
        if lifecycle.transport.transport.sink is not sink or process_config.run != sink.config or lifecycle.evidence.store.path.resolve() != self.store.path.resolve():
            raise ValueError("产品执行服务与运行不匹配")
        binding = self.recovery.authorize_start(request, sink)
        transport = lifecycle.transport.transport
        authority = lifecycle.transport.authority
        if authority is None or authority.services is not self or authority.request is not request or authority.sink is not sink or authority.plan_digest != plan_digest or authority.budget != budget or lifecycle.transport.provider_gateway.store.authority is not authority:
            raise ValueError("产品执行缺少当前本人运行授权")
        if transport.scope_service is not self.scope or transport.bridge is not self.bridge or (transport.actor_id, transport.space_id) != (binding["actor_id"], binding["space_id"]) or transport.context_tools is None:
            raise ValueError("产品执行的来源、身份或上下文服务不匹配")
        transport.context_tools.require_runtime_dependencies(transport.context_tools.skill)
        transport.context_tools.require_current()
        with transport.context_tools.guarded_result(gate_check=transport._require_gate):
            pass
        if transport.context_tools.skill.sop_id == "SOP04":
            self.require_selected_meeting_method(sink, transport.context_tools)
        if transport.artifact_tools is not None and (transport.artifact_tools.request is not request or transport.artifact_tools.channel is not self.recovery.channel):
            raise ValueError("成果工具与当前本人会话不匹配")
        from hermes_runtime_transport import HermesVMExecutionLifecycle
        from hermes_cpu_budget import vm_cpu_allocation_seconds
        expected_cpu = vm_cpu_allocation_seconds(budget) if isinstance(lifecycle, HermesVMExecutionLifecycle) else budget["cpu_seconds"]
        expected = {"model_requests": sink.config.request_limit, "rounds": process_config.max_rounds,
                    "tools": process_config.max_tools, "seconds": process_config.max_seconds,
                    "concurrency": process_config.max_concurrency, "context_tokens": process_config.max_context_tokens,
                    "files": process_config.max_files, "file_bytes": process_config.max_file_bytes,
                    "open_files": process_config.max_open_files, "cpu_seconds": budget["cpu_seconds"]}
        if budget != expected or process_config.max_cpu_seconds != expected_cpu or any(type(value) is not int for value in budget.values()):
            raise ValueError("进程预算与运行预算不匹配")
        if not isinstance(lifecycle, HermesVMExecutionLifecycle):
            HermesProcessManager.require_isolation()
            HermesProcessManager.require_bound_isolation()
        if isinstance(lifecycle, HermesVMExecutionLifecycle):
            access = lifecycle.host.access
            self.register_process_start(request, lifecycle.evidence, binding["run_id"], binding["lease_owner"],
                                        binding["lease_epoch"], plan_digest, budget, request_key, request_digest, vm_access=access)
            return await lifecycle.run_vm(listener, process_config, bootstrap=bootstrap)
        ticket = self.register_process_start(request, lifecycle.evidence, binding["run_id"], binding["lease_owner"],
                                             binding["lease_epoch"], plan_digest, budget, request_key, request_digest)
        return await lifecycle.run_guarded_configured(listener, ticket, process_config, bootstrap=bootstrap)


SERVICES_KEY = web.AppKey("hermes_product_services", HermesProductServices)
DISPATCHER_KEY = web.AppKey("hermes_run_dispatcher")
CLOSED_ARTIFACT_ROUTES_KEY = web.AppKey("closed_artifact_routes_installed", bool)


def install_dispatch_route(app, channel, dispatcher):
    from agent_run_api import VALIDATORS

    async def method_catalog(request):
        from boss_simulation_api import _context

        channel.require_run_api_role(request)
        if request.query or request.content_type != "application/json":
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求格式无效")
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"conversation_id", "selected_refs"}:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求字段无效")
        chat_id, refs = payload["conversation_id"], payload["selected_refs"]
        if not VALIDATORS["key"].is_valid(chat_id) or not isinstance(refs, list) or len(refs) > 100 or any(not VALIDATORS["key"].is_valid(ref) for ref in refs) or len(refs) != len(set(refs)):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "会话或来源字段无效")
        channel.require_run_subscription(request, chat_id)
        selection = dispatcher.services.broker.method_selection
        if selection is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行方法服务尚未准备")
        with selection.drafts._locked(), dispatcher.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            proof = dispatcher.services.scope.prove_in_transaction(db, chat_id, refs)
            if (proof.owner_id, proof.namespace, proof.dataset_id, proof.dataset_version) != (context["owner_id"], context["namespace"], context["dataset_id"], context["dataset_version"]):
                fail(web.HTTPForbidden, "SCOPE_FORBIDDEN", "会话或来源范围不可用")
            methods = selection.catalog_in_transaction(db)
            channel.require_run_subscription(request, chat_id)
            current = dispatcher.services.scope.prove_in_transaction(db, chat_id, refs)
            if current != proof:
                fail(web.HTTPConflict, "SCOPE_CHANGED", "会话或来源已经变化")
            channel.require_run_subscription(request, chat_id)
        return web.json_response({"conversation_id": chat_id, "selected_refs": refs, "methods": methods}, headers={"Cache-Control": "no-store"})

    async def dispatch(request, run_id):
        channel.require_run_api_role(request)
        if request.query or request.content_type != "application/json":
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求格式无效")
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"expected_revision", "request_key"} or type(payload["expected_revision"]) is not int or payload["expected_revision"] < 0 or not VALIDATORS["key"].is_valid(payload["request_key"]):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求字段无效")
        result = await dispatcher.dispatch(request, run_id, payload["expected_revision"], payload["request_key"])
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def receipt(request, run_id, request_key):
        channel.require_run_api_role(request)
        if request.query or not VALIDATORS["key"].is_valid(request_key):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求字段无效")
        return web.json_response(dispatcher.dispatch_receipt(request, run_id, request_key), headers={"Cache-Control": "no-store"})

    async def recovery_inspection(request, run_id, request_key):
        channel.require_run_api_role(request)
        if request.query or not VALIDATORS["key"].is_valid(request_key):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求字段无效")
        return web.json_response(dispatcher.inspect_dispatch_recovery(request, run_id, request_key), headers={"Cache-Control": "no-store"})

    endpoint = DynamicResource("/api/v2/runs/{run_id}/dispatch")
    endpoint.add_route("POST", dispatch)
    receipt_endpoint = DynamicResource("/api/v2/runs/{run_id}/dispatch-requests/{request_key}")
    receipt_endpoint.add_route("GET", receipt)
    inspection_endpoint = DynamicResource("/api/v2/runs/{run_id}/dispatch-requests/{request_key}/inspection")
    inspection_endpoint.add_route("GET", recovery_inspection)
    catalog_endpoint = DynamicResource("/api/v2/run-method-catalog")
    catalog_endpoint.add_route("POST", method_catalog)

    @web.middleware
    async def route(request, handler):
        match, allowed = await catalog_endpoint.resolve(request)
        if match is not None:
            return await method_catalog(request)
        if allowed:
            raise web.HTTPMethodNotAllowed(request.method, allowed)
        match, allowed = await inspection_endpoint.resolve(request)
        if match is not None:
            return await recovery_inspection(request, match["run_id"], match["request_key"])
        if allowed:
            raise web.HTTPMethodNotAllowed(request.method, allowed)
        match, allowed = await receipt_endpoint.resolve(request)
        if match is not None:
            return await receipt(request, match["run_id"], match["request_key"])
        if allowed:
            raise web.HTTPMethodNotAllowed(request.method, allowed)
        match, allowed = await endpoint.resolve(request)
        if match is not None:
            return await dispatch(request, match["run_id"])
        if allowed:
            raise web.HTTPMethodNotAllowed(request.method, allowed)
        return await handler(request)

    app.middlewares.append(route)


def install_closed_artifact_routes(app, channel):
    async def unavailable(request):
        channel.require_run_api_role(request)
        fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "成果工作区隔离尚未通过核查")

    paths = ("/api/v2/runs/{run_id}/artifacts", "/api/v2/runs/{run_id}/artifact-pending-requests", "/api/v2/runs/{run_id}/artifact-requests/{request_key}",
             "/api/v2/artifacts/{artifact_id}", "/api/v2/artifacts/{artifact_id}/file", "/api/v2/artifacts/{artifact_id}/versions")
    if CLOSED_ARTIFACT_ROUTES_KEY in app or any(path in {resource.canonical for resource in app.router.resources()} for path in paths):
        raise ValueError("成果路由已经注册")
    endpoints = []
    for path in paths:
        resource = DynamicResource(path)
        resource.add_route("GET", unavailable)
        endpoints.append(resource)

    @web.middleware
    async def dispatch(request, handler):
        for endpoint in endpoints:
            match, allowed = await endpoint.resolve(request)
            if match is not None:
                return await match.handler(request)
            if allowed:
                raise web.HTTPMethodNotAllowed(request.method, allowed)
        return await handler(request)

    app.middlewares.append(dispatch)
    app[CLOSED_ARTIFACT_ROUTES_KEY] = True


def install_isolation_status(app, channel):
    @web.middleware
    async def isolation_status(request, handler):
        if request.path != "/api/v2/hermes/isolation":
            return await handler(request)
        channel.require_run_api_role(request)
        if request.method != "GET":
            raise web.HTTPMethodNotAllowed(request.method, ["GET"])
        if request.query:
            raise web.HTTPBadRequest(text="隔离状态请求参数无效")
        return web.json_response(HermesProcessManager.inspect_isolation(), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    app.middlewares.append(isolation_status)


def hermes_product_application(channel, business_store, sessions, namespace, *, public_port, upstream_port, artifact_workspace=None, chat_budget_enabled=False, execution_factory=None, execution_deployment=None):
    from agent_artifact_workspace import ArtifactWorkspace
    mapped_workspace = artifact_workspace if isinstance(artifact_workspace, ArtifactWorkspace) else None
    run_store = RunStore(business_store.path, allow_migration=False)
    if namespace != NAMESPACE or not isinstance(channel, RoleChannel) or channel.boss_commands is None or channel.boss_commands.store.path.resolve() != business_store.path.resolve() or channel.gateway.session_manager is not sessions:
        raise ValueError("产品身份、会话和运行服务必须使用同一环境")
    scope = RunScopeService(business_store, sessions, namespace)
    from agent_run_method_selection import AgentRunMethodSelection
    from agent_run_object_scope import AgentRunObjectScope
    with run_store.connect() as db:
        selection_schema = AgentRunMethodSelection.schema_state(db)
        reselection_schema = AgentRunMethodSelection.reselection_schema_state(db)
        object_scope_schema = AgentRunObjectScope.schema_state(db)
    if selection_schema != reselection_schema:
        raise ValueError("运行方法选择迁移不完整")
    selection = None
    if selection_schema and channel.skills is not None:
        selection = AgentRunMethodSelection(run_store, scope, channel.skills.catalog, channel.skills.drafts)
    object_scope = AgentRunObjectScope(run_store, scope) if object_scope_schema else None
    broker = RunBroker(run_store, scope_service=scope, method_selection=selection, object_scope=object_scope)
    if type(chat_budget_enabled) is not bool:
        raise ValueError("聊天预算配置无效")
    chat_budget = AgentChatBudget(run_store, channel, scope) if chat_budget_enabled else None
    services = HermesProductServices(run_store, scope, broker, HermesBridge(business_store), HermesRunRecovery(channel, scope, run_store), chat_budget, mapped_workspace)
    app = product_application(channel, broker, public_port=public_port, upstream_port=upstream_port, chat_budget=chat_budget)
    install_isolation_status(app, channel)
    if chat_budget is not None:
        install_chat_budget_routes(app, chat_budget, public_port=public_port)
    install_owner_decision(app, channel, broker, public_port=public_port)
    from agent_run_resume_routes import install_run_resume_routes
    install_run_resume_routes(app, channel, broker, public_port=public_port)
    from agent_run_recovery_routes import install_run_recovery_routes
    install_run_recovery_routes(app, channel, services.recovery, public_port=public_port,
        vm_manager=execution_deployment.vm_manager if execution_deployment is not None else None,
        workspace_root=execution_deployment.workspace_root if execution_deployment is not None else None)
    from agent_source_history_routes import install_source_history_routes
    install_source_history_routes(app, channel, run_store, scope, public_port=public_port)
    from agent_artifact_source_history_routes import install_artifact_source_history_routes
    install_artifact_source_history_routes(app, channel, run_store, scope, public_port=public_port)
    install_skill_maintenance(app, channel, business_store, public_port=public_port)
    install_plan_execution(app, channel, business_store, scope, public_port=public_port)
    install_legacy_routes(app, channel, scope, broker, public_port=public_port)
    if artifact_workspace is None:
        install_closed_artifact_routes(app, channel)
    else:
        from agent_artifact_routes import install_artifact_read_routes
        install_artifact_read_routes(app, channel, scope, artifact_workspace, public_port=public_port)
    app[SERVICES_KEY] = services
    from agent_run_dispatcher import AgentRunDispatcher
    if execution_factory is not None and execution_deployment is not None:
        raise ValueError("执行工厂和部署配置不能同时提供")
    if mapped_workspace is not None and execution_factory is not None:
        raise ValueError("成果目录映射需要产品执行工厂")
    if execution_deployment is not None:
        from hermes_runtime_binding import HermesExecutionFactory
        execution_factory = HermesExecutionFactory(services, execution_deployment, artifact_workspace=mapped_workspace)
    app[DISPATCHER_KEY] = AgentRunDispatcher(services, execution_factory=execution_factory)
    broker.execution_factory = execution_factory
    install_dispatch_route(app, channel, app[DISPATCHER_KEY])
    return app
