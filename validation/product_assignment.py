import json
from dataclasses import dataclass
from uuid import uuid4

from aiohttp import web
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.base import Tool
from nanobot.providers.base import LLMResponse, ToolCallRequest

from business import checksum, now, require
from boss_assignment_sources import AssignmentSourcesAPI
from boss_business_overview import BusinessOverviewAPI
from boss_runtime_records import ATTRIBUTE
from boss_simulation_api import _context
from fc07_agent import Fc07Context, Fc07ReadTool, TOOLS
from fc07_agent.runtime import Fc07RuntimeRecorder, Fc07SimulatedProvider
from product_bi import FEATURE_SCOPE, PREPARING_REQUEST
from product_fc01 import validate_request

GRANT = "product_assignment_request"


@dataclass(frozen=True)
class AssignmentRequest:
    key: str
    owner_id: str
    dataset_id: str
    dataset_version: str
    task_id: str
    task_version: str
    review_sha256: str
    session_id: str
    active: object


class ProductAssignment:
    def __init__(self, store):
        self.store = store
        self.bot = self.runtime = None
        self.provider = Fc07SimulatedProvider(self.events)
        self.outputs = {}

    def _overview_record(self, db, key):
        context = _context(db)
        row = self.store.get(db, "ui-check", "overview_assignment_preparation", key)
        require(all(row[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")),
                "经营准备原请求不属于当前本人资料", web.HTTPForbidden)
        return row

    async def prepare_overview(self, role, payload, active):
        require(role == "BOSS" and active(), "经营交办准备需要当前本人认证", web.HTTPForbidden)
        require(isinstance(payload, dict) and set(payload) == {"client_request_id", "input", "context_sha256"},
                "经营交办准备字段无效", web.HTTPBadRequest)
        key = payload["client_request_id"]
        validate_request("Status", {"client_request_id": key})
        bridge = BusinessOverviewAPI(self.store).preparation()
        view = bridge.verify(role, payload["input"], payload["context_sha256"])
        require(view["handoff"] is not None and view["handoff"]["operation"] == "boss.assignment.prepare",
                "当前经营准备没有正式交办审查入口", web.HTTPConflict)
        digest = checksum(payload)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            checked = bridge.project_in_transaction(role, db, payload["input"])
            require(checked["context_sha256"] == payload["context_sha256"] and checked["current_use_verified"],
                    "经营准备范围或来源已经变化", web.HTTPConflict)
            previous = db.execute("SELECT 1 FROM objects WHERE namespace='ui-check' AND kind='overview_assignment_preparation' AND id=?", (key,)).fetchone()
            if previous:
                require(self._overview_record(db, key)["input_sha256"] == digest,
                        "经营准备原编号内容不符", web.HTTPConflict)
            else:
                require(db.execute("SELECT 1 FROM objects WHERE namespace='ui-check' AND kind='assignment_public_request' AND id=?", (key,)).fetchone() is None,
                        "当前编号已经用于其他交办准备，请读取原请求", web.HTTPConflict)
                context = _context(db)
                self.store.put(db, "ui-check", "overview_assignment_preparation", key, {"client_request_id": key,
                    **{field: context[field] for field in ("owner_id", "dataset_id", "dataset_version")},
                    "input_sha256": digest, "input": payload["input"], "context_sha256": payload["context_sha256"],
                    "created_at": now()})
        if previous:
            return self.overview_receipt(role, key, active)
        def current():
            if not active():
                return False
            bridge.verify(role, payload["input"], payload["context_sha256"])
            return True
        result = await self.prepare(role, {"client_request_id": key, **view["handoff"]["parameters"]}, current)
        bridge.verify(role, payload["input"], payload["context_sha256"])
        self._verify_overview_result(view, result)
        return self.overview_receipt(role, key, active)

    @staticmethod
    def _verify_overview_result(view, receipt):
        prepared, expected = receipt["preparation"], view["assignment_context"]
        require(prepared is not None and expected is not None and receipt["request_state"] == "SUCCEEDED"
                and prepared["task"]["task_id"] == expected["task_reference"]["id"]
                and prepared["task"]["version"] == expected["task_reference"]["version"]
                and prepared["source_review"]["review_sha256"] == expected["review_sha256"],
                "经营准备实际结果与原范围、对象或来源审查不符", web.HTTPConflict)

    def overview_receipt(self, role, key, active):
        require(role == "BOSS" and active(), "经营准备原请求需要当前本人认证", web.HTTPForbidden)
        validate_request("Status", {"client_request_id": key})
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = self._overview_record(db, key)
            recorded = db.execute("SELECT 1 FROM objects WHERE namespace='ui-check' AND kind='assignment_public_request' AND id=?", (key,)).fetchone()
        result = self.receipt(role, key, active) if recorded else None
        require(active(), "经营准备读取期间本人身份已变化", web.HTTPUnauthorized)
        return {"source_type": "RUNTIME_RECORD", "client_request_id": key, "input": row["input"],
            "context_sha256": row["context_sha256"], "assignment_receipt": result,
            "outcome": "RECORDED" if recorded else "ASSIGNMENT_REQUEST_NOT_FOUND_IN_CURRENT_STORE",
            "current_use_verified": False, "write_performed_by_lookup": False,
            "business_authorization_granted": False, "business_mutation_performed": False}

    @staticmethod
    def handles(request):
        return request is not None and GRANT in request.attributes

    def _grant(self, request=None):
        request = request or current_request_context() or PREPARING_REQUEST.get()
        require(request is not None and request.sender_id == "boss-1", "交办读取需要本人认证", web.HTTPForbidden)
        grant = request.attributes.get(GRANT)
        require(isinstance(grant, AssignmentRequest) and grant.active(), "交办本人请求已经失效", web.HTTPUnauthorized)
        return request, grant

    def context_provider(self):
        request, grant = self._grant()
        binding = request.attributes.get(ATTRIBUTE)
        return Fc07Context("BOSS", grant.owner_id, "ui-check", grant.dataset_id, grant.dataset_version,
            binding.request_id if binding else grant.key, binding.session_id if binding else grant.session_id,
            True, grant.task_id, grant.task_version, grant.review_sha256)

    async def scope_context(self, request):
        if self.handles(request):
            self._grant(request)
            require(TOOLS <= set(self.runtime.registry.tool_names), "当前配置未启用交办及来源读取工具", web.HTTPConflict)
            request.attributes[FEATURE_SCOPE] = TOOLS

    def recorder(self, registry, snapshot):
        return PublicAssignmentRecorder(self, registry, snapshot)

    async def events(self, messages, tools):
        _, grant = self._grant()
        start = max(index for index, message in enumerate(messages) if message["role"] == "user")
        outputs = [json.loads(message["content"]) for message in messages[start + 1:] if message["role"] == "tool"]
        if len(outputs) < 2:
            name = "read_assignment" if not outputs else "assignmentSourcesRead"
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=name, arguments={"task_id": grant.task_id})], usage=None)
        require(outputs[0]["task_id"] == outputs[1]["task"]["task_id"] == grant.task_id
                and outputs[0]["version"] == outputs[1]["task"]["version"] == grant.task_version
                and outputs[1]["review_sha256"] == grant.review_sha256, "交办读取结果与当前对象不符", web.HTTPConflict)
        self.outputs[grant.key] = {"source_type": "SIMULATED", "task": outputs[0], "source_review": outputs[1],
            "owner_decision_required": True, "business_authority_granted": False}
        return LLMResponse(content="SIMULATED · 当前交办与来源已经读取，后续业务动作由本人分别确认。", usage=None)

    async def prepare(self, role, payload, active):
        require(role == "BOSS" and active(), "交办读取需要本人认证", web.HTTPForbidden)
        require(isinstance(payload, dict) and set(payload) == {"client_request_id", "task_id", "task_version"}, "交办读取字段无效", web.HTTPBadRequest)
        validate_request("Status", {"client_request_id": payload["client_request_id"]})
        require(all(isinstance(payload[field], str) and 0 < len(payload[field]) <= 200 for field in ("task_id", "task_version")), "交办对象或版本无效", web.HTTPBadRequest)
        key, digest = payload["client_request_id"], checksum(payload)
        view = AssignmentSourcesAPI(self.store).read(role, payload["task_id"])
        require(view["task"]["version"] == payload["task_version"], "交办版本已经变化，请重新读取当前对象", web.HTTPConflict)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            previous = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='assignment_public_request' AND id=?", (key,)).fetchone()
            if previous:
                require(json.loads(previous[0])["input_sha256"] == digest, "同编号交办读取内容不符", web.HTTPConflict)
            else:
                self.store.put(db, "ui-check", "assignment_public_request", key, {"client_request_id": key, "input_sha256": digest,
                    **{field: context[field] for field in ("owner_id", "dataset_id", "dataset_version")}, "task_id": payload["task_id"],
                    "task_version": payload["task_version"], "review_sha256": view["review_sha256"], "status": "PREPARED", "created_at": now()})
        if previous:
            return self.receipt(role, key, active)
        grant = AssignmentRequest(key, context["owner_id"], context["dataset_id"], context["dataset_version"], payload["task_id"],
            payload["task_version"], view["review_sha256"], "fc07:" + key, active)
        result = await self.bot.run("SIMULATED：读取当前选中的交办及其来源，准备本人核查。", session_key=grant.session_id,
            sender_id=grant.owner_id, ephemeral=True, attributes={GRANT: grant})
        require(not result.error and key in self.outputs and active(), "当前交办读取未完成，请核查原请求", web.HTTPConflict)
        output = self.outputs.pop(key)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.store.get(db, "ui-check", "assignment_public_request", key)
            run = self.store.get(db, "ui-check", "runtime_run", row["run_id"])
            require(run["status"] == "SUCCEEDED", "当前交办实际运行未成功", web.HTTPConflict)
            row.update(status="SUCCEEDED", result=output)
            self.store.put(db, "ui-check", "assignment_public_request", key, row)
        return self.receipt(role, key, active)

    def receipt(self, role, key, active):
        require(role == "BOSS" and active(), "交办原请求仅限本人读取", web.HTTPForbidden)
        validate_request("Status", {"client_request_id": key})
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            row = self.store.get(db, "ui-check", "assignment_public_request", key)
            require(all(row[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")), "原交办读取不属于当前资料范围", web.HTTPForbidden)
            run = self.store.get(db, "ui-check", "runtime_run", row["run_id"]) if row.get("run_id") else None
        view = AssignmentSourcesAPI(self.store).read(role, row["task_id"])
        current = view["task"]["version"] == row["task_version"] and view["review_sha256"] == row["review_sha256"]
        return {"client_request_id": key, "task_id": row["task_id"], "task_version": row["task_version"], "run_id": row.get("run_id"),
            "request_state": run["status"] if run else row["status"], "adoption_state": "CURRENT" if current else "HISTORICAL_REQUIRES_REQUERY",
            "preparation": row.get("result") if current and row["status"] == "SUCCEEDED" else None, "write_performed_by_lookup": False}


class PublicAssignmentRecorder(Fc07RuntimeRecorder):
    def __init__(self, service, registry, snapshot):
        super().__init__(service.store, "ui-check", registry, snapshot, service.context_provider)
        self.service = service

    async def context(self, request):
        token = PREPARING_REQUEST.set(request)
        try:
            block = await super().context(request)
            _, grant = self.service._grant(request)
            binding = request.attributes[ATTRIBUTE]
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self.store.get(db, "ui-check", "assignment_public_request", grant.key)
                row.update(status="RUNNING", run_id=binding.run_id)
                self.store.put(db, "ui-check", "assignment_public_request", grant.key, row)
            return block
        finally:
            PREPARING_REQUEST.reset(token)


class AssignmentReadTool(Tool):
    def __init__(self, ordinary, service):
        self.ordinary, self.service = ordinary, service
        self.scoped = Fc07ReadTool(service.store, service.context_provider, ordinary.name)

    @property
    def name(self):
        return self.ordinary.name

    @property
    def description(self):
        return self.ordinary.description

    @property
    def parameters(self):
        return self.ordinary.parameters

    def cast_params(self, params):
        return self.ordinary.cast_params(params)

    async def execute(self, **params):
        tool = self.scoped if self.service.handles(current_request_context()) else self.ordinary
        return await tool.execute(**params)
