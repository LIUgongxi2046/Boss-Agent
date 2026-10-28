import asyncio
import json
from dataclasses import dataclass
from uuid import uuid4

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.tools.context import current_request_context
from nanobot.providers.base import LLMResponse, ToolCallRequest

from business import checksum, now, require
from boss_execution_scope import NAMESPACE as NS
from boss_morning import MorningAPI, SCHEMA, QUERY_ACTION
from boss_runtime_records import ATTRIBUTE
from boss_simulation_api import _context
from fc03_agent import Fc03Context
from fc03_agent.formal import FORMAL_TOOLS
from fc03_agent.runtime import Fc03RuntimeRecorder, Fc03SimulatedProvider
from fc03_agent.native import NativeMorningAdapter
from product_bi import FEATURE_SCOPE, PREPARING_REQUEST
from conversation_agent.presentation import morning_brief

MORNING_REQUEST = "product_morning_request"
REQUEST_SCHEMA = {"type": "object", "additionalProperties": False, "$defs": SCHEMA["$defs"],
    "required": ["client_request_id", "date", "timezone", "question"],
    "properties": {"client_request_id": {"type": "string", "minLength": 8, "maxLength": 128, "pattern": "^[A-Za-z0-9_.-]+$"},
        "date": SCHEMA["$defs"]["Day"]["properties"]["date"], "timezone": SCHEMA["$defs"]["Day"]["properties"]["timezone"],
        "question": {"type": "string", "minLength": 1, "maxLength": 4000}, "list_id": {"$ref": "#/$defs/Id"},
        "item_id": {"$ref": "#/$defs/Id"}}, "dependentRequired": {"item_id": ["list_id"]}}


@dataclass(frozen=True)
class MorningRequest:
    key: str
    owner_id: str
    dataset_id: str
    dataset_version: str
    session_id: str
    date: str
    timezone: str
    snapshot_sha256: str
    order_version: str
    list_id: str | None
    item_id: str | None
    active: object
    source_selection_json: str | None = None


class ProductMorning:
    def __init__(self, store):
        self.store, self.api = store, MorningAPI(store)
        self.provider = Fc03SimulatedProvider(self.events, allowed_tools=FORMAL_TOOLS)
        self.bot = self.runtime = None
        self.active_runs = {}
        self.native = NativeMorningAdapter(self)

    @staticmethod
    def handles(request):
        return request is not None and MORNING_REQUEST in request.attributes

    def _grant(self, request=None):
        request = request or current_request_context() or PREPARING_REQUEST.get()
        require(request is not None and request.sender_id == "boss-1", "晨间请求需要本人认证", web.HTTPForbidden)
        grant = request.attributes.get(MORNING_REQUEST)
        require(isinstance(grant, MorningRequest) and grant.active(), "晨间本人认证已失效", web.HTTPUnauthorized)
        return request, grant

    def context_provider(self):
        request, grant = self._grant()
        runtime = request.attributes.get(ATTRIBUTE)
        return Fc03Context("BOSS", grant.owner_id, NS, grant.dataset_id, grant.dataset_version,
            runtime.request_id if runtime is not None else grant.key, runtime.session_id if runtime is not None else grant.session_id,
            True, json.dumps({"date": grant.date, "timezone": grant.timezone}), grant.date, grant.timezone,
            grant.snapshot_sha256, grant.order_version, grant.key, frozenset({grant.list_id}) if grant.list_id else frozenset(),
            grant.list_id if grant.item_id else None, grant.item_id, grant.source_selection_json)

    async def scope_context(self, request):
        if not self.handles(request):
            return None
        self._grant(request)
        require(FORMAL_TOOLS <= set(self.runtime.registry.tool_names) and self.runtime.loop.max_iterations >= 5,
                "当前配置需要四项正式晨间读取工具和至少五轮调用", web.HTTPConflict)
        request.attributes[FEATURE_SCOPE] = FORMAL_TOOLS

    def guard_context(self, provider):
        async def guarded(request):
            ready = False
            try:
                result = await provider(request)
                ready = True
                return result
            finally:
                grant = request.attributes.get(MORNING_REQUEST)
                if not ready and grant is not None and grant.key in self.native.proofs:
                    self.native.finish(grant.key)
        return guarded

    def recorder(self, registry, snapshot):
        return PublicMorningRecorder(self, registry, snapshot)

    def bind_runtime(self, request):
        _, grant = self._grant(request)
        binding = request.attributes[ATTRIBUTE]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.store.get(db, NS, "morning_public_request", grant.key)
            require(row["status"] == "PREPARED", "原晨间请求已经进入运行", web.HTTPConflict)
            row.update(status="RUNNING", runtime_request_id=binding.request_id, run_id=binding.run_id, session_id=binding.session_id)
            self.store.put(db, NS, "morning_public_request", grant.key, row)

    async def events(self, messages, tools):
        await asyncio.sleep(0)
        _, grant = self._grant()
        current = max(index for index, message in enumerate(messages) if message["role"] == "user")
        outputs = [json.loads(message["content"]) for message in messages[current + 1:] if message["role"] == "tool"]
        def call(name, params):
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=name, arguments=params)], usage=None)
        if not outputs:
            return call("morningListRead", {"list_id": grant.list_id}) if grant.list_id else call("todayRead", {"date": grant.date, "timezone": grant.timezone})
        view = outputs[0].get("result", outputs[0])
        require(view["source_type"] == "SIMULATED" and bool(view["list_id"]), "晨间工具未产生正式清单", web.HTTPConflict)
        question = messages[current]["content"]
        mentioned = [item for item in view["items"] if item["title"] in question]
        discussed = [item for item in view["items"] if item["item_id"] == grant.item_id] if grant.item_id else mentioned or view["items"]
        if not any("adoption_state" in output for output in outputs):
            return call("morningListRead", {"list_id": view["list_id"]})
        if discussed and not any("item" in output for output in outputs):
            return call("morningDetailRead", {"list_id": view["list_id"], "item_id": discussed[0]["item_id"]})
        detail = next((output for output in outputs if "item" in output), None)
        source_ids = {ref["id"] for item in discussed for ref in item["source_refs"] if ref["kind"] == "document"} if grant.item_id or mentioned else None
        sources = [source for source in view["source_statuses"] if source["status"] == "VALID" and (source_ids is None or source["source_id"] in source_ids)]
        if sources and not any("document" in output for output in outputs):
            return call("morningSourceRead", {"list_id": view["list_id"], "source_id": sources[0]["source_id"]})
        if grant.source_selection_json is not None:
            selected_sources = json.loads(grant.source_selection_json)["source_refs"]
            documents_read = {(output["document"]["source_id"], output["document"]["version"]) for output in outputs if "document" in output}
            for source in selected_sources:
                if (source["source_id"], source["version"]) not in documents_read:
                    return call("morningSourceRead", {"list_id": view["list_id"], "source_id": source["source_id"]})
        content = "当前模拟资料：\n\n" + "\n\n".join(morning_brief({**view, "items": discussed}))
        documents = [output["document"] for output in outputs if "document" in output]
        content += "\n\n### 相关材料\n" + ("\n\n".join(document["content"] for document in documents) if documents else "当前事项尚无可读取的材料，请补充后核查。")
        content += "\n\n可以返回今日工作，勾选事项后确认具体处理操作。"
        return LLMResponse(content=content, usage=None)

    def _request(self, role, payload, active):
        require(role == "BOSS" and active(), "晨间查询需要本人认证", web.HTTPForbidden)
        require(not list(Draft202012Validator(REQUEST_SCHEMA, format_checker=FormatChecker()).iter_errors(payload)), "晨间公开请求不符合Schema", web.HTTPBadRequest)
        key = payload["client_request_id"]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            existing = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='morning_public_request' AND id=?", (NS, key)).fetchone()
            if existing:
                row = json.loads(existing[0])
                require(all(row[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")), "原晨间请求不属于当前范围", web.HTTPForbidden)
                require(row["payload_sha256"] == checksum(payload), "原晨间请求编号内容已经变化", web.HTTPConflict)
                return None
        day = {field: payload[field] for field in ("date", "timezone")}
        preview = self.api.read(role, day)
        selected = payload.get("list_id")
        domain_key = key
        if selected is not None:
            current = self.api.read_list(role, selected)
            require(all(current["result"][field] == preview[field] for field in ("date", "timezone", "snapshot_sha256")), "所选清单与当前日期范围不符", web.HTTPConflict)
            if payload.get("item_id") is not None:
                self.api.detail(role, selected, payload["item_id"])
            with self.store.connect() as db:
                stored = self.store.get(db, NS, "morning_list", selected)
                domain_key = stored["client_request_id"]
        session_id = "sdk:morning-" + str(uuid4())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = _context(db)
            require(all(current[field] == context[field] for field in ("owner_id", "namespace", "dataset_id", "dataset_version")), "晨间范围在准备期间已变化", web.HTTPConflict)
            require(db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='morning_public_request' AND id=?", (NS, key)).fetchone() is None, "原晨间请求正在准备，请查询原编号", web.HTTPConflict)
            self.store.put(db, NS, "morning_public_request", key, {"request_id": key, "payload_sha256": checksum(payload),
                "owner_id": context["owner_id"], "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"],
                **day, "session_id": session_id, "domain_client_request_id": domain_key, "selected_list_id": selected, "selected_item_id": payload.get("item_id"), "status": "PREPARED", "created_at": now()})
        return MorningRequest(key, context["owner_id"], context["dataset_id"], context["dataset_version"], session_id,
            preview["date"], preview["timezone"], preview["snapshot_sha256"], preview["order_version"], selected, payload.get("item_id"), active)

    async def execute(self, role, payload, active):
        require(self.bot is not None and self.runtime is not None, "晨间运行尚未准备", web.HTTPServiceUnavailable)
        require(FORMAL_TOOLS <= set(self.runtime.registry.tool_names) and self.runtime.loop.max_iterations >= 5,
                "请由维护身份启用四项晨间读取工具和至少五轮调用", web.HTTPConflict)
        grant = self._request(role, payload, active)
        if grant is None:
            return self.receipt(role, payload["client_request_id"])
        task = asyncio.create_task(self.runtime.run_bot(self.bot, payload["question"], session_key=grant.session_id, sender_id=grant.owner_id,
            ephemeral=True, attributes={MORNING_REQUEST: grant}))
        self.active_runs[grant.key] = task
        try:
            result = await task
        finally:
            self.active_runs.pop(grant.key, None)
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self.store.get(db, NS, "morning_public_request", grant.key)
                if "run_id" not in row:
                    row.update(status="CANCELED" if task.cancelled() else "FAILED", finished_at=now())
                    self.store.put(db, NS, "morning_public_request", grant.key, row)
        require(not result.error, "晨间运行未成功，请查询原编号", web.HTTPConflict)
        require(active(), "晨间认证已失效，请重新认证后读取原编号", web.HTTPUnauthorized)
        return self.receipt(role, grant.key)

    def receipt(self, role, key):
        self.api._role(role)
        with self.store.connect() as db:
            context = _context(db)
            row = self.store.get(db, NS, "morning_public_request", key)
            require(all(row[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")), "原晨间请求不属于当前范围", web.HTTPForbidden)
            run = self.store.get(db, NS, "runtime_run", row["run_id"]) if "run_id" in row else None
        return {"client_request_id": key, "request_state": run["status"] if run else row["status"], "run_id": row.get("run_id"),
                "receipt": self.api.receipt(role, QUERY_ACTION, row["domain_client_request_id"]), "write_performed_by_lookup": False}

    def history(self, role):
        self.api._role(role)
        with self.store.connect() as db:
            context = _context(db)
            rows = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='morning_public_request' ORDER BY json_extract(body,'$.created_at') DESC", (NS,))]
        return {"source_type": "SIMULATED", "requests": [{key: row.get(key) for key in ("request_id", "date", "timezone", "created_at", "run_id", "selected_list_id")}
            for row in rows if all(row[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version"))]}

    def cancel(self, role, key, active):
        require(role == "BOSS" and active(), "取消晨间运行需要本人认证", web.HTTPForbidden)
        receipt = self.receipt(role, key)
        task = self.active_runs.get(key)
        if task is not None:
            task.cancel()
        return {**receipt, "cancel_requested": task is not None}


class PublicMorningRecorder(Fc03RuntimeRecorder):
    def __init__(self, service, registry, snapshot):
        super().__init__(service.store, NS, registry, snapshot, service.context_provider)
        self.service = service

    async def context(self, request):
        token = PREPARING_REQUEST.set(request)
        try:
            result = await super().context(request)
            self.service.bind_runtime(request)
            return result
        finally:
            PREPARING_REQUEST.reset(token)
