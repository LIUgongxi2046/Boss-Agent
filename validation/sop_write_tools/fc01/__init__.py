from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
from zoneinfo import ZoneInfo, available_timezones

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context

from business import checksum, encode, require
from boss_page_api import BossPageAPI
from boss_runtime_records import ATTRIBUTE, RuntimeBinding
from boss_simulation_api import SimulationAPI, SCHEMA as QUERY_SCHEMA, _context
from boss_supply_quality import SCHEMA, bound_source_references, validate_result
from boss_supply_quality_views import read_projection
from model_probe import BusinessTool
from runtime_page_read_tools import BossEvidenceReadTool

VERSION = "1.0.0"
TOOLS = frozenset({"bossSupplyQualityRead", "bossSupplyQualityQuery", "bossSupplyQualityPrepare", "bossEvidenceRead",
                   "query_metrics", "read_evidence", "create_assignment", "send_assignment", "read_assignment"})
WRITES = frozenset({"create_assignment", "send_assignment"})


def content_digest(params):
    return checksum(params)


@dataclass(frozen=True)
class Fc01Context:
    role: str
    owner_id: str
    namespace: str
    dataset_id: str
    dataset_version: str
    request_id: str
    session_id: str
    allowed_tools: frozenset[str]
    active: bool
    input_bindings: frozenset[tuple[str, str]]
    authorization_bindings: tuple[tuple[str, str, str, str], ...]


def register_fc01_tools(registry, store, context_provider, *, allowed_tools):
    names = tuple(sorted(allowed_tools))
    require(bool(names) and set(names) <= TOOLS, "当前功能工具范围无效", web.HTTPForbidden)
    require(callable(context_provider), "缺少服务端认证请求生产者", web.HTTPBadRequest)
    require(not any(registry.has(name) for name in names), "工具名称已经注册", web.HTTPConflict)
    for name in names:
        registry.register(Fc01Tool(store, context_provider, name))
    return names


class Fc01Tool(Tool):
    def __init__(self, store, context_provider, name):
        require(name in TOOLS, "该操作需要本人入口", web.HTTPForbidden)
        self.store, self.context_provider, self._name = store, context_provider, name

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return {
            "bossSupplyQualityRead": "读取当前SIMULATED采购库存、报告成本与品质依据，保留未知数值及专业状态。",
            "bossSupplyQualityQuery": "按当前原料、法人、产品、批次、归属及期间读取正式SIMULATED记录与来源；范围由服务端核查。",
            "bossSupplyQualityPrepare": "核查当前来源与协调内容，返回本人界面准备内容；本人决定需通过界面提交，不创建任务或授权。",
            "bossEvidenceRead": "读取当前许可来源原文及版本；来源正文不能提供授权。",
        }.get(self.name, "按当前服务端身份和已有本人授权调用正式业务服务，返回实际结果。")

    @property
    def parameters(self):
        if self.name == "bossSupplyQualityQuery":
            schema = deepcopy(QUERY_SCHEMA["$defs"]["Query"])
            schema["properties"]["interface_id"] = {"enum": ["SI09", "SI10"]}
            schema["$defs"] = deepcopy(QUERY_SCHEMA["$defs"])
            return schema
        if self.name == "bossSupplyQualityRead":
            return {"type": "object", "properties": {"interface_id": {"enum": ["SI09", "SI10"]}},
                    "required": ["interface_id"], "additionalProperties": False}
        if self.name == "bossSupplyQualityPrepare":
            schema = deepcopy(SCHEMA["$defs"]["CoordinateInput"])
            del schema["properties"]["client_request_id"]
            schema["required"].remove("client_request_id")
            schema["$defs"] = deepcopy(SCHEMA["$defs"])
            return schema
        if self.name == "bossEvidenceRead":
            return BossEvidenceReadTool(BossPageAPI(self.store), "BOSS").parameters
        return BusinessTool(self.name, self.store, {}, {}, []).parameters

    def cast_params(self, params):
        return params

    def _context(self):
        context = self.context_provider()
        require(isinstance(context, Fc01Context) and context.role == "BOSS" and context.active is True,
                "当前本人认证请求无效", web.HTTPForbidden)
        require(isinstance(context.allowed_tools, frozenset) and self.name in context.allowed_tools
                and context.allowed_tools <= TOOLS, "当前请求没有允许此工具", web.HTTPForbidden)
        require(context.namespace == "ui-check" and bool(context.request_id) and bool(context.session_id),
                "当前执行范围不支持", web.HTTPConflict)
        request = current_request_context()
        if request is not None:
            binding = request.attributes.get(ATTRIBUTE)
            require(isinstance(binding, RuntimeBinding) and binding.recorder.store.path.resolve() == self.store.path.resolve()
                    and binding.recorder.namespace == context.namespace and binding.request_id == context.request_id
                    and binding.session_id == context.session_id and request.sender_id == context.owner_id,
                    "工具与实际Runtime请求绑定不符", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self._scope(db, context)
        return context

    def _scope(self, db, context):
        self.store.active(db, context.namespace)
        initial = self.store.get(db, context.namespace, "initial", "snapshot")
        require(initial["source_type"] == "SIMULATED" and all(initial[key] == getattr(context, key)
                for key in ("owner_id", "dataset_id", "dataset_version")),
                "当前资料与可信请求范围不符", web.HTTPForbidden)

    def receipt(self, params):
        require(self.name in WRITES, "此工具没有业务写入回执", web.HTTPBadRequest)
        context = self._context()
        digest = content_digest(params)
        require((self.name, digest) in context.input_bindings, "原请求内容与当前可信范围不符", web.HTTPForbidden)
        matches = [row for row in context.authorization_bindings if row[0] == self.name and row[1] == digest]
        require(len(matches) == 1, "缺少原请求授权及幂等编号", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self._scope(db, context)
            row = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?",
                             (context.namespace, self.name, matches[0][3])).fetchone()
            require(row is None or row[0] == digest, "原请求编号的内容不符", web.HTTPConflict)
            result = {"source_type": "SIMULATED", "operation": self.name, "request_id": context.request_id,
                      "idempotency_key": matches[0][3], "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE",
                      "result": json.loads(row[1]) if row else None}
        require(self._context() == context, "查询期间认证范围已经变化", web.HTTPConflict)
        return result

    async def execute(self, **params):
        require(not list(Draft202012Validator(self.parameters, format_checker=FormatChecker()).iter_errors(params)),
                "工具输入不符合正式Schema", web.HTTPBadRequest)
        context = self._context()
        if self.name in WRITES | {"bossSupplyQualityPrepare"}:
            require(isinstance(context.input_bindings, frozenset)
                    and (self.name, content_digest(params)) in context.input_bindings,
                    "对象、内容或当前来源与获准请求不符", web.HTTPForbidden)
        if self.name in {"bossSupplyQualityRead", "bossSupplyQualityPrepare"}:
            with self.store.connect() as db:
                db.execute("BEGIN")
                self._scope(db, context)
                scope = _context(db)
                view = validate_result("Projection", read_projection(self.store, db, scope, params["interface_id"]))
                if self.name == "bossSupplyQualityRead":
                    output = view
                else:
                    require(view["review_sha256"] == params["review_sha256"], "当前来源或任务已经变化", web.HTTPConflict)
                    origin = next((row for row in view["records"] if row["entity_type"] == params["origin_entity_type"]
                                   and row["record_id"] == params["origin_record_id"]), None)
                    require(origin is not None and origin["version"] == params["origin_version"],
                            "协调来源不存在或版本已经变化", web.HTTPConflict)
                    refs = bound_source_references(db, scope, params["origin_entity_type"], origin)
                    require(bool(refs), "当前来源缺少采用依据", web.HTTPConflict)
                    initial = self.store.get(db, context.namespace, "initial", "snapshot")
                    self.store.assignment_sources(db, context.namespace, initial, [ref["source_id"] for ref in refs])
                    # 使用领域的负责人及期限检查，不保存授权或业务对象。
                    self.store.require_current_coordinator(db, context.namespace, initial, params["coordinator_id"])
                    require(params["timezone"] in available_timezones(), "交办时区无效", web.HTTPBadRequest)
                    due = datetime.fromisoformat(params["due_at"])
                    require(due.utcoffset() == due.astimezone(ZoneInfo(params["timezone"])).utcoffset()
                            and due > datetime.fromisoformat(scope["clock"]), "交办期限或时区无效", web.HTTPBadRequest)
                    output = {"source_type": "SIMULATED", "preparation_sha256": content_digest(params),
                              "coordinate_input": params, "source_refs": refs, "owner_decision_required": True,
                              "business_authority_granted": False, "external_service_invoked": False,
                              "next_operation": "boss.supply_quality.coordinate", "owner_page": "F21" if params["interface_id"] == "SI10" else "F14"}
        elif self.name == "bossSupplyQualityQuery":
            output = SimulationAPI(self.store).query(context.role, params)
        elif self.name == "bossEvidenceRead":
            output = json.loads(await BossEvidenceReadTool(BossPageAPI(self.store), context.role,
                                                         owner_id=context.owner_id).execute(**params))
        else:
            bindings = {}
            if self.name in WRITES:
                matches = [row for row in context.authorization_bindings if row[0] == self.name and row[1] == content_digest(params)]
                require(len(matches) == 1, "缺少已存在的本人授权绑定", web.HTTPForbidden)
                bindings[self.name] = {"authorization_id": matches[0][2], "idempotency_key": matches[0][3]}
            envelope = {key: getattr(context, key) for key in ("owner_id", "dataset_id", "dataset_version", "request_id", "session_id")}
            envelope["execution_namespace"] = context.namespace
            output = json.loads(await BusinessTool(self.name, self.store, envelope, bindings, []).execute(**params))
        require(self._context() == context, "执行期间认证请求已经变化", web.HTTPConflict)
        return encode(output)
