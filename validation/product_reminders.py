import json
from dataclasses import dataclass
from uuid import uuid4

from aiohttp import web
from nanobot.agent.tools.context import current_request_context
from nanobot.providers.base import LLMResponse, ToolCallRequest

from business import now, require
from boss_runtime_records import ATTRIBUTE
from boss_simulation_api import _context
from boss_workspace_api import BossWorkspaceAPI
from fc04_agent import Fc04Context, Fc04ReadTool, TOOLS, notifications_digest
from fc04_agent.runtime import Fc04RuntimeHook, Fc04RuntimeRecorder, Fc04SimulatedProvider
from product_bi import FEATURE_SCOPE, PREPARING_REQUEST
from product_fc01 import validate_request
from runtime_sop_read_tools import BossWorkspaceReadTool

GRANT = "product_reminder_request"


@dataclass(frozen=True)
class ReminderRequest:
    key: str
    owner_id: str
    dataset_id: str
    dataset_version: str
    projection_sha256: str
    session_id: str
    active: object


class ProductReminders:
    def __init__(self, store):
        self.store = store
        self.bot = self.runtime = None
        self.provider = Fc04SimulatedProvider(self.events)
        self.outputs = {}

    @staticmethod
    def handles(request):
        return request is not None and GRANT in request.attributes

    def _grant(self, request=None):
        request = request or current_request_context() or PREPARING_REQUEST.get()
        require(request is not None and request.sender_id == "boss-1", "提醒读取需要本人认证", web.HTTPForbidden)
        grant = request.attributes.get(GRANT)
        require(isinstance(grant, ReminderRequest) and grant.active(), "提醒读取请求已经失效", web.HTTPUnauthorized)
        return request, grant

    def context_provider(self):
        request, grant = self._grant()
        binding = request.attributes.get(ATTRIBUTE)
        return Fc04Context("BOSS", grant.owner_id, "ui-check", grant.dataset_id, grant.dataset_version,
            binding.request_id if binding else grant.key, binding.session_id if binding else grant.session_id, True, grant.projection_sha256)

    def view(self):
        code, value = BossWorkspaceAPI(self.store).serve("BOSS", "/api/boss/ui/workspace/notifications")
        require(code == 200, "当前提醒投影无法读取", web.HTTPConflict)
        return value

    async def scope_context(self, request):
        if self.handles(request):
            self._grant(request)
            policy = self.runtime.workspace_policy
            require(TOOLS <= set(self.runtime.registry.tool_names) and policy["workspace_read_mode"] == "WORKSPACE_PROJECTIONS"
                    and "notifications" in policy["workspace_projections"], "当前配置尚未启用限定提醒投影", web.HTTPConflict)
            request.attributes[FEATURE_SCOPE] = TOOLS

    def workspace_tool(self, api, role, *, allowed_projections):
        return ReminderWorkspaceTool(api, role, allowed_projections=allowed_projections, service=self)

    def recorder(self, registry, snapshot):
        return PublicReminderRecorder(self, registry, snapshot)

    async def events(self, messages, tools):
        _, grant = self._grant()
        require(len(tools) == 1 and tools[0]["function"]["parameters"]["properties"]["projection"]["enum"] == ["notifications"],
                "当前提醒工具定义超出批准投影", web.HTTPForbidden)
        start = max(index for index, message in enumerate(messages) if message["role"] == "user")
        outputs = [json.loads(message["content"]) for message in messages[start + 1:] if message["role"] == "tool"]
        if not outputs:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="bossWorkspaceRead", arguments={"projection": "notifications"})], usage=None)
        require(len(outputs) == 1 and outputs[0]["projection"] == "notifications" and notifications_digest(outputs[0]) == grant.projection_sha256,
                "提醒读取与当前批准投影不符", web.HTTPConflict)
        self.outputs[grant.key] = {"source_type": "SIMULATED", "projection": outputs[0], "owner_decision_required": True, "business_authority_granted": False}
        return LLMResponse(content="SIMULATED · 当前提醒、规则和处理状态已经读取，后续动作由本人分别决定。", usage=None)

    async def prepare(self, role, payload, active):
        require(role == "BOSS" and active(), "提醒读取需要本人认证", web.HTTPForbidden)
        validate_request("Status", payload)
        key = payload["client_request_id"]
        view = self.view()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            previous = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='reminder_public_request' AND id=?", (key,)).fetchone()
            if not previous:
                self.store.put(db, "ui-check", "reminder_public_request", key, {"client_request_id": key,
                    **{field: context[field] for field in ("owner_id", "dataset_id", "dataset_version")}, "projection_sha256": notifications_digest(view), "status": "PREPARED", "created_at": now()})
        if previous:
            return self.receipt(role, key, active)
        grant = ReminderRequest(key, context["owner_id"], context["dataset_id"], context["dataset_version"], notifications_digest(view), "fc04:" + key, active)
        result = await self.bot.run("SIMULATED：读取当前获准的经营提醒、规则及本人处理状态。", session_key=grant.session_id,
            sender_id=grant.owner_id, ephemeral=True, attributes={GRANT: grant})
        require(not result.error and key in self.outputs and active(), "当前提醒读取未完成，请核查原请求", web.HTTPConflict)
        output = self.outputs.pop(key)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.store.get(db, "ui-check", "reminder_public_request", key)
            run = self.store.get(db, "ui-check", "runtime_run", row["run_id"])
            require(run["status"] == "SUCCEEDED", "实际提醒读取运行未成功", web.HTTPConflict)
            row.update(status="SUCCEEDED", result=output)
            self.store.put(db, "ui-check", "reminder_public_request", key, row)
        return self.receipt(role, key, active)

    def receipt(self, role, key, active):
        require(role == "BOSS" and active(), "原提醒准备仅限本人读取", web.HTTPForbidden)
        validate_request("Status", {"client_request_id": key})
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            row = self.store.get(db, "ui-check", "reminder_public_request", key)
            require(all(row[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")), "原提醒请求不属于当前本人资料", web.HTTPForbidden)
            run = self.store.get(db, "ui-check", "runtime_run", row["run_id"]) if row.get("run_id") else None
        current = notifications_digest(self.view()) == row["projection_sha256"]
        return {"client_request_id": key, "run_id": row.get("run_id"), "request_state": run["status"] if run else row["status"],
            "adoption_state": "CURRENT" if current else "HISTORICAL_REQUIRES_REQUERY", "projection_sha256": row["projection_sha256"],
            "preparation": row.get("result") if current and row["status"] == "SUCCEEDED" else None, "write_performed_by_lookup": False}


class PublicReminderRecorder(Fc04RuntimeRecorder):
    def __init__(self, service, registry, snapshot):
        super().__init__(service.store, "ui-check", registry, snapshot, service.context_provider)
        self.service = service

    def hook_factory(self, context):
        binding = context.attributes.get(ATTRIBUTE)
        require(binding is not None and binding.recorder is self, "当前经营提醒运行关联无效")
        return PublicReminderHook(self, binding.run_id)

    async def context(self, request):
        token = PREPARING_REQUEST.set(request)
        try:
            block = await super().context(request)
            _, grant = self.service._grant(request)
            with self.service.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self.service.store.get(db, "ui-check", "reminder_public_request", grant.key)
                row.update(status="RUNNING", run_id=request.attributes[ATTRIBUTE].run_id)
                self.service.store.put(db, "ui-check", "reminder_public_request", grant.key, row)
            return block
        finally:
            PREPARING_REQUEST.reset(token)


class PublicReminderHook(Fc04RuntimeHook):
    async def after_execute_tool(self, context, tool_call, tool, params, result):
        await super().after_execute_tool(context, tool_call, tool, params, result)
        projection = json.loads(result)
        references = []
        for event in projection["business_alerts"]["items"]:
            references.append({"event_id": event["event_id"], "event_version": event["event_version"],
                "adoption_state": event["adoption_state"], "business_rule_version": event["business_rule"]["version"] if event["business_rule"] is not None else None,
                "rule_state": event["rule_state"], "technical_rule_version": event["technical_rule_version"],
                "owner_notice_version": event["owner_notice_version"], "review_sha256": event["review_sha256"],
                "evaluation": {field: event["evaluation"][field] for field in ("phase", "reason", "duration_seconds")},
                "sources": [{field: source[field] for field in ("source_id", "version", "status", "sha256") if field in source} for source in event["sources"]]})
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            next(item for item in row["tool_results"] if item["tool_call_id"] == tool_call.id)["business_alert_refs"] = references
            self.recorder._save(db, row)


class ReminderWorkspaceTool(BossWorkspaceReadTool):
    def __init__(self, api, role, *, allowed_projections, service):
        super().__init__(api, role, allowed_projections=allowed_projections)
        self.service = service
        self.scoped = Fc04ReadTool(service.store, service.context_provider)

    @property
    def parameters(self):
        request = current_request_context() or PREPARING_REQUEST.get()
        return self.scoped.parameters if self.service.handles(request) else super().parameters

    async def execute(self, **params):
        if self.service.handles(current_request_context()):
            return await self.scoped.execute(**params)
        return await super().execute(**params)
