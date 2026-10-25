from dataclasses import dataclass
from copy import deepcopy
import json

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context

from business import SPEC, OPERATIONS, checksum, encode, require
from boss_runtime_records import ATTRIBUTE, RuntimeBinding
from model_probe import BusinessTool

VERSION = "1.0.0"
TOOLS = frozenset({"query_metrics", "read_evidence"})


@dataclass(frozen=True)
class QueryBinding:
    parameters_json: str
    previous_query_id: str | None
    previous_parameters_json: str | None
    overridden_fields: frozenset[str]

    def visible(self):
        parameters = json.loads(self.parameters_json)
        excluded = {"question", "parent_query_id", "query_mode"}
        inherited = set(parameters) - self.overridden_fields if self.previous_query_id else set()
        return {"parameters": {key: value for key, value in parameters.items() if key != "question"},
                "previous_query_id": self.previous_query_id,
                "overridden_fields": sorted(self.overridden_fields - excluded),
                "inherited_fields": sorted(inherited - excluded),
                "parameters_sha256": checksum(parameters)}


def bind_query(parameters, *, previous_query_id=None, previous_parameters=None, overridden_fields=None):
    fields = frozenset(parameters) if overridden_fields is None else frozenset(overridden_fields)
    require(fields <= set(parameters), "明确覆盖字段不属于当前查询", web.HTTPBadRequest)
    require((previous_query_id is None) == (previous_parameters is None), "追问缺少原查询范围", web.HTTPBadRequest)
    if previous_parameters is None:
        require(fields == set(parameters), "新问题需要完整明确范围", web.HTTPBadRequest)
    else:
        current_scope = {key: value for key, value in parameters.items() if key != "parent_query_id"}
        previous_scope = {key: value for key, value in previous_parameters.items() if key != "parent_query_id"}
        require((set(previous_scope) ^ set(current_scope)) <= fields and all(
            current_scope[key] == previous_scope[key] for key in set(current_scope) & set(previous_scope) if key not in fields),
            "追问改变了未明确覆盖的字段", web.HTTPConflict)
        if parameters.get("query_mode") == "SCOPED":
            require(parameters.get("parent_query_id") == previous_query_id, "正式追问父查询不符", web.HTTPConflict)
    return QueryBinding(encode(parameters), previous_query_id,
                        encode(previous_parameters) if previous_parameters is not None else None, fields)


@dataclass(frozen=True)
class Fc02Context:
    role: str
    owner_id: str
    namespace: str
    dataset_id: str
    dataset_version: str
    request_id: str
    session_id: str
    active: bool
    query_bindings: tuple[QueryBinding, ...]
    readable_query_ids: frozenset[str]


def bind_scoped_followup(store, context, parent_query_id, question, overrides):
    from boss_bi_queries import BIQueryAPI
    from business import validate
    envelope = {key: getattr(context, key) for key in ("owner_id", "dataset_id", "dataset_version", "request_id", "session_id")}
    envelope["execution_namespace"] = context.namespace
    validate("bi_follow_up", {"envelope": envelope, "parent_query_id": parent_query_id,
                              "question": question, "overrides": overrides})
    parent = BIQueryAPI(store).read(context.role, parent_query_id)["result"]
    require(parent["envelope"]["session_id"] == context.session_id, "追问不属于当前会话", web.HTTPForbidden)
    previous = {key: value for key, value in parent["context_snapshot"].items() if key != "envelope"}
    current = {**previous, **overrides, "question": question, "parent_query_id": parent_query_id}
    return bind_query(current, previous_query_id=parent_query_id, previous_parameters=previous,
                      overridden_fields=set(overrides) | {"question", "parent_query_id"})


def register_fc02_tools(registry, store, context_provider):
    require(callable(context_provider), "缺少真实认证请求生产者", web.HTTPBadRequest)
    require(not any(registry.has(name) for name in TOOLS), "BI工具名称已经注册", web.HTTPConflict)
    for name in sorted(TOOLS):
        registry.register(Fc02Tool(store, context_provider, name))
    return sorted(TOOLS)


class Fc02Tool(Tool):
    def __init__(self, store, context_provider, name):
        require(name in TOOLS, "当前BI范围不允许此工具", web.HTTPForbidden)
        self.store, self.context_provider, self._name = store, context_provider, name

    @property
    def name(self):
        return self._name

    @property
    def parameters(self):
        definitions = deepcopy(SPEC["io_schema"]["$defs"])
        ref = OPERATIONS[self.name]["input_schema"].rsplit("/", 1)[1]
        for name in (ref, "legacy_query_input", "scoped_query_input"):
            definition = definitions.get(name)
            if definition is not None and "properties" in definition:
                injected = {"envelope", "authorization_id", "idempotency_key"}
                definition["properties"] = {key: value for key, value in definition["properties"].items() if key not in injected}
                definition["required"] = [key for key in definition.get("required", []) if key not in injected]
        return {"$ref": "#/$defs/" + ref, "$defs": definitions}

    @property
    def description(self):
        return BusinessTool(self.name, self.store, {}, {}, []).description

    def cast_params(self, params):
        return params

    def context(self):
        context = self.context_provider()
        require(isinstance(context, Fc02Context) and context.role == "BOSS" and context.active is True,
                "BI本人认证请求无效", web.HTTPForbidden)
        require(context.namespace == "ui-check" and context.request_id and context.session_id,
                "当前BI执行范围无效", web.HTTPForbidden)
        require(isinstance(context.query_bindings, tuple) and all(isinstance(item, QueryBinding) for item in context.query_bindings)
                and isinstance(context.readable_query_ids, frozenset), "BI可信请求结构无效", web.HTTPBadRequest)
        request = current_request_context()
        if request is not None:
            binding = request.attributes.get(ATTRIBUTE)
            require(isinstance(binding, RuntimeBinding) and binding.recorder.store.path.resolve() == self.store.path.resolve()
                    and binding.recorder.namespace == context.namespace and binding.request_id == context.request_id
                    and binding.session_id == context.session_id and request.sender_id == context.owner_id,
                    "BI工具与实际Runtime请求不符", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, context.namespace)
            initial = self.store.get(db, context.namespace, "initial", "snapshot")
            require(initial["source_type"] == "SIMULATED" and all(initial[key] == getattr(context, key)
                    for key in ("owner_id", "dataset_id", "dataset_version")), "BI本人或资料范围不符", web.HTTPForbidden)
        return context

    def _query(self, db, context, query_id):
        query = self.store.get(db, context.namespace, "query", query_id)
        envelope = query["envelope"]
        require(all(envelope[key] == getattr(context, key) for key in ("owner_id", "dataset_id", "dataset_version"))
                and envelope["execution_namespace"] == context.namespace, "原查询不属于当前范围", web.HTTPForbidden)
        return query

    def receipt(self):
        from boss_bi_queries import BIQueryAPI
        context = self.context()
        result = BIQueryAPI(self.store).receipt(context.role, context.session_id, context.request_id)
        require(self.context() == context, "BI回执读取期间认证范围已经变化", web.HTTPConflict)
        return result

    async def execute(self, **params):
        require(not list(Draft202012Validator(self.parameters, format_checker=FormatChecker()).iter_errors(params)),
                "BI输入不符合正式Schema", web.HTTPBadRequest)
        context = self.context()
        if self.name == "query_metrics":
            matches = [item for item in context.query_bindings if checksum(json.loads(item.parameters_json)) == checksum(params)]
            require(len(matches) == 1, "模型查询参数与当前明确输入不符", web.HTTPForbidden)
            item = matches[0]
            bind_query(params, previous_query_id=item.previous_query_id,
                       previous_parameters=json.loads(item.previous_parameters_json) if item.previous_parameters_json else None,
                       overridden_fields=item.overridden_fields)
            if item.previous_query_id:
                with self.store.connect() as db:
                    db.execute("BEGIN")
                    parent = self._query(db, context, item.previous_query_id)
                    if params.get("query_mode") == "SCOPED":
                        previous = {key: value for key, value in parent["context_snapshot"].items() if key not in {"envelope", "parent_query_id"}}
                        supplied = {key: value for key, value in json.loads(item.previous_parameters_json).items() if key != "parent_query_id"}
                        require(previous == supplied, "可信追问与正式持久快照不符", web.HTTPConflict)
        else:
            with self.store.connect() as db:
                db.execute("BEGIN")
                query = self._query(db, context, params["query_id"])
                same_request = query["envelope"]["request_id"] == context.request_id and query["envelope"]["session_id"] == context.session_id
                require(same_request or params["query_id"] in context.readable_query_ids,
                        "当前请求没有选择此查询依据", web.HTTPForbidden)
        envelope = {key: getattr(context, key) for key in ("owner_id", "dataset_id", "dataset_version", "request_id", "session_id")}
        envelope["execution_namespace"] = context.namespace
        result = await BusinessTool(self.name, self.store, envelope, {}, []).execute(**params)
        require(self.context() == context, "BI执行期间认证请求已经变化", web.HTTPConflict)
        return result
