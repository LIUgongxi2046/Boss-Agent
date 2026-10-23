import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from nanobot.agent.tools.context import current_request_context
from nanobot.providers.base import LLMResponse, ToolCallRequest

from business import checksum, encode, now, require
from boss_runtime_records import ATTRIBUTE
from boss_supply_quality import SupplyQualityAPI, COORDINATE_ACTION
from sop_write_tools.fc01 import Fc01Context, Fc01Tool
from sop_write_tools.fc01.contract import interface_contract
from sop_write_tools.fc01.runtime import Fc01SimulatedProvider

PREPARE = "boss.fc01.prepare"
REQUIRED = frozenset({"bossSupplyQualityRead", "bossSupplyQualityQuery", "bossEvidenceRead", "bossSupplyQualityPrepare"})
GRANT = "product_fc01_request"
SPEC_DIRECTORY = Path(__file__).resolve().parents[1] / "specs"
PUBLIC_SPEC = yaml.safe_load((SPEC_DIRECTORY / "product-fc01.openapi.yaml").read_text())
PUBLIC_REGISTRY = Registry().with_resource((SPEC_DIRECTORY / "simulated-supply-quality.schema.json").as_uri(),
    Resource.from_contents(json.loads((SPEC_DIRECTORY / "simulated-supply-quality.schema.json").read_text())))


def validate_request(kind, payload):
    schema = {**PUBLIC_SPEC, "$id":(SPEC_DIRECTORY / "product-fc01.openapi.yaml").as_uri(), "$ref":"#/components/schemas/"+kind}
    require(not list(Draft202012Validator(schema, registry=PUBLIC_REGISTRY, format_checker=FormatChecker()).iter_errors(payload)),
            "当前请求不符合公开字段规范", web.HTTPBadRequest)


@dataclass(frozen=True)
class PreparationRequest:
    key: str
    params: dict
    dataset_id: str
    dataset_version: str
    active: object
    input_bindings: frozenset


class ProductFc01:
    def __init__(self, store):
        self.store = store
        self.provider = Fc01SimulatedProvider(self.events)
        self.bot = None
        self.runtime = None
        self.outputs = {}

    def _grant(self):
        request = current_request_context()
        require(request is not None and request.sender_id == "boss-1", "当前请求需要本人认证", web.HTTPForbidden)
        grant = request.attributes.get(GRANT)
        require(isinstance(grant, PreparationRequest) and grant.active(), "本人认证已经失效", web.HTTPUnauthorized)
        return request, grant

    def context_provider(self):
        request, grant = self._grant()
        binding = request.attributes.get(ATTRIBUTE)
        require(binding is not None and binding.recorder.store is self.store, "当前请求缺少运行绑定", web.HTTPForbidden)
        allowed = frozenset(self.runtime.registry.tool_names) & REQUIRED
        return Fc01Context("BOSS", "boss-1", "ui-check", grant.dataset_id, grant.dataset_version,
                           binding.request_id, binding.session_id, allowed, grant.active(), grant.input_bindings, ())

    async def events(self, messages, tools):
        request = current_request_context()
        if request is None or GRANT not in request.attributes:
            return LLMResponse(content="SIMULATED：请在原料库存或食品品质页面选择当前依据并填写协调内容，再准备本人核查材料。", usage=None)
        request, grant = self._grant()
        outputs = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        stage = len(outputs)
        if stage == 0:
            name, params = "bossSupplyQualityRead", {"interface_id": grant.params["interface_id"]}
        elif stage == 1:
            require(outputs[0]["review_sha256"] == grant.params["review_sha256"], "当前资料已经变化", web.HTTPConflict)
            name, params = "bossSupplyQualityQuery", {"interface_id": grant.params["interface_id"], "object_ids": [grant.params["origin_record_id"]], "filters": {}}
        elif stage == 2:
            records = outputs[-1]["records"]
            origin = next((row for row in records if row["storage_id"] == grant.params["origin_record_id"] and row["entity_type"] == grant.params["origin_entity_type"]), None)
            require(origin is not None and origin["data"] is not None, "当前依据不可采用", web.HTTPConflict)
            source = origin["data"]["source_id"]
            name, params = "bossEvidenceRead", {"source": source}
        elif stage == 3:
            require(outputs[-1].get("content") is not None, "当前原文不可采用", web.HTTPConflict)
            name, params = "bossSupplyQualityPrepare", grant.params
        else:
            output = outputs[-1]
            Draft202012Validator(interface_contract(self.store, self.context_provider)["preparation_output"], format_checker=FormatChecker()).validate(output)
            require(output["coordinate_input"] == grant.params, "准备内容与本人输入不符", web.HTTPConflict)
            self.outputs[grant.key] = output
            return LLMResponse(content="SIMULATED：当前来源与协调材料已读取，请在当前页面核查内容并由本人决定。", usage=None)
        require(name in {item["function"]["name"] for item in tools}, "当前配置没有启用必要工具", web.HTTPConflict)
        return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=name, arguments=deepcopy(params))], usage=None)

    async def prepare(self, role, payload, active):
        require(role == "BOSS" and active(), "仅当前本人认证可以准备协调", web.HTTPForbidden)
        validate_request("Prepare", payload)
        require(isinstance(payload, dict) and set(payload) == {"client_request_id", "coordinate_input"}, "准备请求字段无效", web.HTTPBadRequest)
        key, params = payload["client_request_id"], deepcopy(payload["coordinate_input"])
        require(isinstance(key, str) and 1 <= len(key) <= 128, "准备请求编号无效", web.HTTPBadRequest)
        schema = Fc01Tool(self.store, self.context_provider, "bossSupplyQualityPrepare").parameters
        require(not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(params)), "协调内容字段无效", web.HTTPBadRequest)
        require(self.bot is not None and self.runtime is not None, "当前Runtime尚未就绪", web.HTTPServiceUnavailable)
        require(REQUIRED <= set(self.runtime.registry.tool_names) and self.runtime.loop.max_iterations >= 5,
                "请由维护身份启用FC01四项读取准备工具及至少五轮工具调用", web.HTTPConflict)
        view = SupplyQualityAPI(self.store).read(role, params["interface_id"])
        require(len(encode(view)) <= self.runtime.loop.max_tool_result_chars, "当前工具输出容量不足以读取完整资料", web.HTTPConflict)
        digest = checksum(params)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            initial = self.store.get(db, "ui-check", "initial", "snapshot")
            existing = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='fc01_preparation' AND id=?", (key,)).fetchone()
            if existing:
                row = json.loads(existing[0])
                require(row["input_sha256"] == digest, "相同请求编号的内容不同", web.HTTPConflict)
                require(row["status"] == "SUCCEEDED", "原准备结果尚未确定，请继续核查原请求", web.HTTPConflict)
                return row["result"]
            require(view["review_sha256"] == params["review_sha256"], "当前来源已经变化，请重新读取", web.HTTPConflict)
            self.store.put(db, "ui-check", "fc01_preparation", key, {"request_id": key, "input_sha256": digest, "status": "RUNNING", "created_at": now()})
        grant = PreparationRequest(key, params, initial["dataset_id"], initial["dataset_version"], active,
                                   frozenset({("bossSupplyQualityPrepare", digest)}))
        result = await self.bot.run("SIMULATED：读取当前采购品质来源并准备本人协调材料。", session_key="fc01:"+key,
                                    sender_id="boss-1", ephemeral=True, attributes={GRANT: grant})
        if result.error or key not in self.outputs:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.store.put(db, "ui-check", "fc01_preparation", key, {"request_id":key, "input_sha256":digest, "status":"FAILED", "created_at":now()})
            raise web.HTTPConflict(text="准备运行未成功，请核查当前运行记录")
        prepared = self.outputs.pop(key)
        require(active(), "本人认证已经失效", web.HTTPUnauthorized)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            runs = [json.loads(item[0]) for item in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run' AND json_extract(body,'$.session_id')=?", ("fc01:"+key,))]
            require(len(runs) == 1 and runs[0]["status"] == "SUCCEEDED", "当前准备运行结果无法核验", web.HTTPConflict)
            output = {**prepared, "run_id": runs[0]["run_id"], "client_request_id": key}
            self.store.put(db, "ui-check", "fc01_preparation", key, {"request_id": key, "input_sha256": digest,
                           "status": "SUCCEEDED", "result": output, "created_at": now()})
        return output

    def status(self, role, payload, active):
        require(role == "BOSS" and active(), "当前本人认证无效", web.HTTPForbidden)
        validate_request("Status", payload)
        require(isinstance(payload, dict) and set(payload) == {"client_request_id"}, "原请求查询字段无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            row = self.store.get(db, "ui-check", "fc01_preparation", payload["client_request_id"])
            runs = [json.loads(item[0]) for item in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run' AND json_extract(body,'$.session_id')=?", ("fc01:"+row["request_id"],))]
        if row["status"] == "SUCCEEDED":
            output = row["result"]
            return output
        return {"client_request_id": row["request_id"], "status": runs[0]["status"] if len(runs) == 1 else row["status"], "run_id":runs[0]["run_id"] if len(runs) == 1 else None, "source_type":"SIMULATED"}

    def coordinate(self, role, payload, active):
        require(role == "BOSS" and active(), "当前本人认证无效", web.HTTPForbidden)
        validate_request("Adopt", payload)
        require(isinstance(payload, dict) and set(payload) == {"client_request_id", "preparation_request_id", "coordinate_input"}, "本人采用字段无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            preparation = self.store.get(db, "ui-check", "fc01_preparation", payload["preparation_request_id"])
        require(preparation["status"] == "SUCCEEDED" and checksum(payload["coordinate_input"]) == preparation["input_sha256"],
                "采用内容与当前准备请求不符，请重新准备", web.HTTPConflict)
        result = SupplyQualityAPI(self.store).execute(role, COORDINATE_ACTION,
                    {**payload["coordinate_input"], "client_request_id":payload["client_request_id"]})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self.store.get(db, "ui-check", "runtime_run", preparation["result"]["run_id"])
            link = {"task_id":result["task_id"], "task_version":result["version"], "request_id":payload["client_request_id"],
                    "preparation_sha256":preparation["input_sha256"], "action":COORDINATE_ACTION}
            require(not run.get("owner_task_links") or run["owner_task_links"] == [link], "当前准备已经用于其他任务", web.HTTPConflict)
            run["owner_task_links"] = [link]
            self.store.put(db, "ui-check", "runtime_run", run["run_id"], run)
        return result
