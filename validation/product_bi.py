import asyncio
import json
from copy import deepcopy
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4
from time import monotonic

import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

from business import ROOT, checksum, now, require, validate
from boss_execution_scope import NAMESPACE as NS
from boss_bi_queries import BIQueryAPI
from public_bi_scenarios import loaded_scenarios, dimension_options
from boss_runtime_records import ATTRIBUTE
from fc02_agent import Fc02Context, Fc02Tool, bind_query, bind_scoped_followup
from fc02_agent.runtime import Fc02RuntimeRecorder, Fc02SimulatedProvider
from sop_write_tools.fc01 import Fc01Tool
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder

BI_REQUEST = "product_bi_request"
FEATURE_SCOPE = "product_feature_tool_scope"
BI_TOOLS = frozenset({"query_metrics", "read_evidence"})
PREPARING_REQUEST = ContextVar("product_bi_preparing_request", default=None)
PUBLIC_SPEC = yaml.safe_load((ROOT.parent / "specs/product-bi.openapi.yaml").read_text())


def validate_public(kind, payload):
    schema = {**PUBLIC_SPEC, "$ref":"#/components/schemas/" + kind}
    require(not list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(payload)),
            "经营请求不符合公开Schema", web.HTTPBadRequest)


class FeatureToolRegistry(ToolRegistry):
    def __init__(self):
        super().__init__()
        self.conversation = None

    def _request_scope(self):
        request = current_request_context() or PREPARING_REQUEST.get()
        if request is None or FEATURE_SCOPE not in request.attributes:
            return None
        scope = request.attributes[FEATURE_SCOPE]
        require(type(scope) is frozenset and scope and scope <= set(super().tool_names),
                "当前请求工具范围无效", web.HTTPForbidden)
        return scope

    @property
    def configured_tool_names(self):
        return super().tool_names

    @property
    def tool_names(self):
        scope = self._request_scope()
        return super().tool_names if scope is None else [name for name in super().tool_names if name in scope]

    def get(self, name):
        scope = self._request_scope()
        if scope is not None and name not in scope:
            return None
        ordinary = super().get(name)
        request = current_request_context() or PREPARING_REQUEST.get()
        if scope is not None and self.conversation is not None and self.conversation.handles(request):
            return self.conversation.registry_tool(name, ordinary)
        return ordinary

    def get_definitions(self):
        scope = self._request_scope()
        request = current_request_context() or PREPARING_REQUEST.get()
        if scope is not None and self.conversation is not None and self.conversation.handles(request):
            return [self.get(name).to_schema() for name in sorted(self.tool_names)]
        definitions = super().get_definitions()
        return definitions if scope is None else [item for item in definitions if item["function"]["name"] in scope]


@dataclass(frozen=True)
class BIRequest:
    key: str
    owner_id: str
    dataset_id: str
    dataset_version: str
    session_id: str
    binding: object
    active: object


class FeatureBusinessTool(Fc01Tool):
    def __init__(self, store, fc01, bi, name):
        super().__init__(store, fc01.context_provider, name)
        self.bi_tool = Fc02Tool(store, bi.context_provider, name)

    @property
    def parameters(self):
        return self.bi_tool.parameters

    def context(self):
        return self.bi_tool.context()

    async def execute(self, **params):
        request = current_request_context()
        if request is not None and BI_REQUEST in request.attributes:
            return await self.bi_tool.execute(**params)
        return await super().execute(**params)


class ProductBI:
    def __init__(self, store):
        self.store = store
        self.api = BIQueryAPI(store)
        self.provider = Fc02SimulatedProvider(self.events)
        self.bot = None
        self.runtime = None
        self.active_runs = {}
        self.outputs = {}

    def _grant(self, request=None):
        request = request or current_request_context() or PREPARING_REQUEST.get()
        require(request is not None and request.sender_id == "boss-1", "当前经营查询需要本人认证", web.HTTPForbidden)
        grant = request.attributes.get(BI_REQUEST)
        require(isinstance(grant, BIRequest) and grant.active(), "经营查询认证已经失效", web.HTTPUnauthorized)
        return request, grant

    def context_provider(self):
        request, grant = self._grant()
        binding = request.attributes.get(ATTRIBUTE)
        request_id = binding.request_id if binding is not None else grant.key
        session_id = binding.session_id if binding is not None else request.session_key
        return Fc02Context("BOSS", grant.owner_id, NS, grant.dataset_id, grant.dataset_version,
                           request_id, session_id, grant.active(), (grant.binding,), frozenset())

    async def scope_context(self, request):
        if BI_REQUEST not in request.attributes:
            return None
        self._grant(request)
        require(BI_TOOLS <= set(self.runtime.registry.tool_names), "当前配置未启用两项BI工具", web.HTTPConflict)
        request.attributes[FEATURE_SCOPE] = BI_TOOLS
        return None

    def bind_runtime(self, request):
        _, grant = self._grant(request)
        binding = request.attributes[ATTRIBUTE]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.store.get(db, NS, "bi_public_request", grant.key)
            require(row["status"] == "PREPARED", "原经营请求已经进入Runtime", web.HTTPConflict)
            row.update(status="RUNNING", runtime_request_id=binding.request_id, run_id=binding.run_id,
                       session_id=binding.session_id)
            self.store.put(db, NS, "bi_public_request", grant.key, row)

    async def events(self, messages, tools):
        await asyncio.sleep(0)
        _, grant = self._grant()
        current = max(index for index, message in enumerate(messages) if message["role"] == "user")
        outputs = [json.loads(message["content"]) for message in messages[current + 1:] if message["role"] == "tool"]
        if not outputs:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="query_metrics",
                arguments=json.loads(grant.binding.parameters_json))], usage=None)
        query = outputs[0]
        require(query.get("source_type") == "SIMULATED" and "context_snapshot" in query,
                "当前查询缺少正式范围结果", web.HTTPConflict)
        if len(outputs) == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="read_evidence", arguments={
                "query_id":query["query_id"], "source_ids":[item["source_id"] for item in query["sources"]],
                "detail_refs":query["detail_refs"]})], usage=None)
        self.outputs[grant.key] = query
        return LLMResponse(content="SIMULATED：当前查询已返回实际数值、范围和资料缺口，请查看结果及原始依据。", usage=None)

    def _context(self, db):
        self.store.active(db, NS)
        return self.store.get(db, NS, "initial", "snapshot")

    def _request(self, role, payload, follow_up, active):
        require(role == "BOSS" and active(), "当前经营请求需要本人认证", web.HTTPForbidden)
        validate_public("FollowUpRequest" if follow_up else "QueryRequest", payload)
        keys = {"client_request_id", "question", "parent_query_id", "overrides"} if follow_up else {"client_request_id", "question", "scope"}
        require(isinstance(payload, dict) and set(payload) == keys, "经营请求字段无效", web.HTTPBadRequest)
        key = payload["client_request_id"]
        require(isinstance(key, str) and 8 <= len(key) <= 128 and key.isascii() and all(char.isalnum() or char in "-_." for char in key),
                "经营请求编号无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            initial = self._context(db)
            previous = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='bi_public_request' AND id=?", (NS, key)).fetchone()
            if previous:
                row = json.loads(previous[0])
                require(row["owner_id"] == initial["owner_id"] and row["dataset_id"] == initial["dataset_id"] and row["dataset_version"] == initial["dataset_version"], "原查询请求范围不符", web.HTTPForbidden)
                require(row["payload_sha256"] == checksum(payload), "相同请求编号的内容不同", web.HTTPConflict)
                return None
            if follow_up:
                parent = self.store.get(db, NS, "query", payload["parent_query_id"])
                require(parent["envelope"]["owner_id"] == initial["owner_id"], "父查询不属于本人", web.HTTPForbidden)
                session_id = parent["envelope"]["session_id"]
            else:
                session_id = "sdk:bi-" + str(uuid4())
            context = Fc02Context("BOSS", initial["owner_id"], NS, initial["dataset_id"], initial["dataset_version"],
                                  key, session_id, True, (), frozenset())
            envelope = {"owner_id":context.owner_id,"execution_namespace":NS,"dataset_id":context.dataset_id,
                        "dataset_version":context.dataset_version,"request_id":key,"session_id":session_id}
            if not follow_up:
                require(isinstance(payload["scope"], dict), "经营范围需要正式字段", web.HTTPBadRequest)
                params = {**deepcopy(payload["scope"]),"query_mode":"SCOPED","question":payload["question"],"envelope":envelope}
                validate("scoped_query_input", params)
                require(not ({"envelope","query_mode","question","parent_query_id"} & set(payload["scope"])), "范围含有服务端字段", web.HTTPBadRequest)
                binding = bind_query({name:value for name,value in params.items() if name != "envelope"})
            else:
                binding = bind_scoped_followup(self.store, context, payload["parent_query_id"], payload["question"], payload["overrides"])
            self.store.put(db, NS, "bi_public_request", key, {"request_id":key,"payload_sha256":checksum(payload),
                "owner_id":context.owner_id,"dataset_id":context.dataset_id,"dataset_version":context.dataset_version,
                "session_id":session_id,"status":"PREPARED","created_at":now()})
        return BIRequest(key, context.owner_id, context.dataset_id, context.dataset_version, session_id, binding, active)

    async def execute(self, role, payload, follow_up, active):
        require(role == "BOSS" and active(), "当前经营请求需要本人认证", web.HTTPForbidden)
        require(self.bot is not None and self.runtime is not None, "经营Runtime尚未就绪", web.HTTPServiceUnavailable)
        require(self.runtime.loop.max_iterations >= 3 and BI_TOOLS <= set(self.runtime.registry.tool_names),
                "请由维护身份启用两项BI工具和至少三轮调用", web.HTTPConflict)
        grant = self._request(role, payload, follow_up, active)
        if grant is None:
            return self.receipt(role, payload["client_request_id"])
        task = asyncio.create_task(self.runtime.run_bot(self.bot, "读取当前明确经营条件，执行确定性查询并核查原始依据。外部模型事件为SIMULATED。",
                    session_key=grant.session_id, sender_id=grant.owner_id, ephemeral=True, attributes={BI_REQUEST:grant}))
        self.active_runs[grant.key] = task
        try:
            result = await task
        finally:
            self.active_runs.pop(grant.key, None)
            self.outputs.pop(grant.key, None)
        require(not result.error, "经营运行未成功，请核查原请求", web.HTTPConflict)
        require(active(), "经营查询认证已经失效", web.HTTPUnauthorized)
        return self.receipt(role, grant.key)

    def serve(self, role, path, query_string):
        from urllib.parse import parse_qs
        self.api._role(role)
        query = parse_qs(query_string, keep_blank_values=True)
        require(all(value and all(value) and (len(value) == 1 or path == "/api/boss/ui/bi/dimensions" and field == "source_ids") for field,value in query.items()), "经营读取参数无效", web.HTTPBadRequest)
        if path == "/api/boss/ui/bi/scenarios":
            require(not query,"场景列表不接受额外字段",web.HTTPBadRequest)
            return loaded_scenarios(self.store,role)
        if path == "/api/boss/ui/bi/dimensions":
            require(set(query) <= {"scenario_id","source_ids"}, "维度读取字段无效", web.HTTPBadRequest)
            result = self.api.dimensions(role,query["scenario_id"][0] if "scenario_id" in query else None,query.get("source_ids"))
            return dimension_options(self.store,role,result)
        if path == "/api/boss/ui/bi/receipt":
            require(set(query) == {"client_request_id"}, "原请求读取字段无效", web.HTTPBadRequest)
            return self.receipt(role, query["client_request_id"][0])
        if path == "/api/boss/ui/bi/query":
            require(set(query) in ({"query_id"}, {"query_id", "historical"}), "查询读取字段无效", web.HTTPBadRequest)
            require(query.get("historical", ["false"])[0] in ("true", "false"), "历史读取字段无效", web.HTTPBadRequest)
            return self.api.read(role, query["query_id"][0], query.get("historical", ["false"])[0] == "true")
        if path == "/api/boss/ui/bi/history":
            require(not query, "历史列表不接受额外字段", web.HTTPBadRequest)
            with self.store.connect() as db:
                initial = self._context(db)
                rows = [json.loads(item[0]) for item in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='bi_public_request' ORDER BY json_extract(body,'$.created_at') DESC", (NS,))]
            return {"source_type":"SIMULATED", "requests":[{"client_request_id":row["request_id"], "created_at":row["created_at"], "run_id":row.get("run_id")}
                for row in rows if all(row[field] == initial[field] for field in ("owner_id","dataset_id","dataset_version"))]}
        raise web.HTTPNotFound(text="经营读取入口不存在")

    def receipt(self, role, key):
        self.api._role(role)
        validate_public("CancelRequest", {"client_request_id":key})
        with self.store.connect() as db:
            initial = self._context(db)
            row = self.store.get(db, NS, "bi_public_request", key)
            require(all(row[field] == initial[field] for field in ("owner_id","dataset_id","dataset_version")), "原请求不属于当前范围", web.HTTPForbidden)
            if "runtime_request_id" not in row:
                return {"client_request_id":key,"request_state":"RUNNING" if key in self.active_runs else "FAILED_BEFORE_RUNTIME","receipt":None,"run_id":None}
            run = self.store.get(db,NS,"runtime_run",row["run_id"])
        receipt = self.api.receipt(role, row["session_id"], row["runtime_request_id"])
        return {"client_request_id":key,"request_state":run["status"],"receipt":receipt,"run_id":row["run_id"]}

    def cancel(self, role, key, active):
        require(role == "BOSS" and active(), "经营取消请求需要本人认证", web.HTTPForbidden)
        validate_public("CancelRequest", {"client_request_id":key})
        receipt = self.receipt(role, key)
        task = self.active_runs.get(key)
        if task is not None:
            task.cancel()
        return {**receipt,"cancel_requested":task is not None}


class PublicBIRecorder(Fc02RuntimeRecorder):
    def __init__(self, service, registry, runtime_snapshot):
        super().__init__(service.store,NS,registry,runtime_snapshot,service.context_provider)
        self.service = service

    async def context(self, request):
        token = PREPARING_REQUEST.set(request)
        try:
            block = await super().context(request)
            self.service.bind_runtime(request)
            return block
        finally:
            PREPARING_REQUEST.reset(token)


class FeatureProvider(LLMProvider):
    def __init__(self, fc01, bi, morning=None, assignment=None, reminders=None):
        super().__init__(provider_name="deepseek")
        self.fc01, self.bi = fc01, bi
        self.morning = morning
        self.assignment = assignment
        self.reminders = reminders
        self.conversation = None
        self.external_provider = None
        self.closing_providers = set()

    def adopt_external(self, provider):
        previous = self.external_provider
        self.external_provider = provider
        if previous is not None and previous._client is not None:
            task = asyncio.create_task(previous._client.close())
            self.closing_providers.add(task)

    async def close_external(self):
        if self.external_provider is not None and self.external_provider._client is not None:
            await self.external_provider._client.close()
        if self.closing_providers:
            await asyncio.gather(*self.closing_providers)
            self.closing_providers.clear()

    @staticmethod
    def _call_options(kwargs, streaming=False):
        fields = {"max_tokens", "temperature", "reasoning_effort", "tool_choice", "provider_context"}
        if streaming:
            fields |= {"on_content_delta", "on_thinking_delta", "on_tool_call_delta"}
        return {key: value for key, value in kwargs.items() if key in fields}

    def _external_deadline(self):
        request = current_request_context()
        require(request is not None and ATTRIBUTE in request.attributes, "实际模型请求缺少运行归属")
        binding = request.attributes[ATTRIBUTE]
        require(binding.run_id in binding.recorder.model_deadlines, "实际模型请求缺少运行时间限制")
        return binding.recorder.model_deadlines[binding.run_id]

    def get_default_model(self):
        return self.external_provider.get_default_model() if self.external_provider is not None else "deepseek-flash"

    async def chat(self, messages, tools=None, model=None, **kwargs):
        if self.external_provider is not None:
            async with asyncio.timeout_at(self._external_deadline()):
                return await self.external_provider.chat(messages, tools, model, **self._call_options(kwargs))
        request = current_request_context()
        if self.reminders is not None and self.reminders.handles(request):
            return await self.reminders.provider.chat(messages, tools, model, **kwargs)
        if self.assignment is not None and self.assignment.handles(request):
            return await self.assignment.provider.chat(messages, tools, model, **kwargs)
        if self.conversation is not None and self.conversation.handles(request):
            return await self.conversation.provider.chat(messages, tools, model, **kwargs)
        provider = self.morning.provider if self.morning is not None and self.morning.handles(request) else self.bi.provider if request is not None and BI_REQUEST in request.attributes else self.fc01.provider
        return await provider.chat(messages, tools, model, **kwargs)

    async def chat_with_retry(self, messages, tools=None, model=None, **kwargs):
        return await self.chat(messages, tools, model, **kwargs)

    async def chat_stream_with_retry(self, messages, tools=None, model=None, **kwargs):
        if self.external_provider is not None:
            request = current_request_context()
            binding = request.attributes[ATTRIBUTE]
            options = self._call_options(kwargs, True)
            callback = options.get("on_content_delta")
            started = monotonic()
            arrivals, processing, lengths = [], [], []

            async def observe_delta(delta):
                received = monotonic()
                arrivals.append((received-started)*1000)
                lengths.append(len(delta))
                await callback(delta)
                processing.append((monotonic()-received)*1000)

            if callback is not None:
                options["on_content_delta"] = observe_delta
            async with asyncio.timeout_at(self._external_deadline()):
                try:
                    return await self.external_provider.chat_stream(messages, tools, model, **options)
                finally:
                    gaps = [right-left for left, right in zip(arrivals, arrivals[1:])]
                    profile = {"chunks": len(arrivals), "characters": sum(lengths),
                               "first_chunk_ms": round(arrivals[0], 2) if arrivals else None,
                               "max_chunk_gap_ms": round(max(gaps), 2) if gaps else None,
                               "mean_chunk_gap_ms": round(sum(gaps)/len(gaps), 2) if gaps else None,
                               "max_processing_ms": round(max(processing), 2) if processing else None,
                               "mean_processing_ms": round(sum(processing)/len(processing), 2) if processing else None}
                    with binding.recorder.store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        row = binding.recorder._read(db, binding.run_id)
                        row.setdefault("stream_observations", []).append(profile)
                        binding.recorder._save(db, row)
        result = await self.chat(messages, tools, model, **kwargs)
        if kwargs.get("on_content_delta") is not None and result.content:
            await kwargs["on_content_delta"](result.content)
        return result


class FeatureRecorder:
    def __init__(self, store, registry, snapshot, bi, morning=None, assignment=None, reminders=None):
        self.fc01 = Fc01RuntimeRecorder(store,NS,registry,snapshot)
        self.bi = PublicBIRecorder(bi,registry,snapshot)
        self.morning_service = morning
        self.morning = morning.recorder(registry,snapshot) if morning is not None else None
        self.assignment_service = assignment
        self.assignment = assignment.recorder(registry,snapshot) if assignment is not None else None
        self.reminder_service = reminders
        self.reminders = reminders.recorder(registry,snapshot) if reminders is not None else None
        self.conversation = None

    async def context(self, request):
        if self.reminder_service is not None and self.reminder_service.handles(request):
            return await self.reminders.context(request)
        if self.assignment_service is not None and self.assignment_service.handles(request):
            return await self.assignment.context(request)
        if self.conversation is not None and self.conversation.handles(request):
            token = PREPARING_REQUEST.set(request)
            try:
                return await self.conversation.recorder.context(request)
            finally:
                PREPARING_REQUEST.reset(token)
        recorder = self.morning if self.morning_service is not None and self.morning_service.handles(request) else self.bi if BI_REQUEST in request.attributes else self.fc01
        token = PREPARING_REQUEST.set(request)
        try:
            return await recorder.context(request)
        finally:
            PREPARING_REQUEST.reset(token)

    def hook_factory(self, context):
        return context.attributes[ATTRIBUTE].recorder.hook_factory(context)
