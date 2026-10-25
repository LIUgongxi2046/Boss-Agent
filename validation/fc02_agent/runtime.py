import json

from nanobot import RuntimeContextBlock
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, encode, require
from boss_runtime_records import ATTRIBUTE
from fc02_agent import Fc02Context, Fc02Tool
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder, Fc01RuntimeHook, Fc01SimulatedProvider


class Fc02SimulatedProvider(Fc01SimulatedProvider):
    async def chat(self, messages, tools=None, model=None, **kwargs):
        require({item["function"]["name"] for item in tools or []} == {"query_metrics", "read_evidence"},
                "当前BI模拟模型工具范围不符")
        return await super().chat(messages, tools, model, **kwargs)


class Fc02RuntimeRecorder(Fc01RuntimeRecorder):
    def __init__(self, store, namespace, registry, runtime_snapshot, context_provider):
        super().__init__(store, namespace, registry, runtime_snapshot)
        self.context_provider = context_provider

    async def context(self, request):
        context = self.context_provider()
        require(isinstance(context, Fc02Context) and context.role == "BOSS" and context.active is True,
                "BI运行缺少本人可信上下文")
        require(context.owner_id == request.sender_id, "BI运行与本人身份不符")
        require(context.namespace == self.namespace, "BI运行空间与可信请求不符")
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, self.namespace)
            initial = self.store.get(db, self.namespace, "initial", "snapshot")
            require(all(initial[key] == getattr(context, key) for key in ("owner_id", "dataset_id", "dataset_version")),
                    "BI运行资料与可信请求不符")
        validator = Draft202012Validator(Fc02Tool(self.store, self.context_provider, "query_metrics").parameters,
                                         format_checker=FormatChecker())
        for item in context.query_bindings:
            require(not list(validator.iter_errors(json.loads(item.parameters_json))), "BI可信输入不符合当前正式Schema")
        block = await super().context(request)
        visible = [item.visible() for item in context.query_bindings]
        binding = request.attributes[ATTRIBUTE]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._read(db, binding.run_id)
            row.update(feature_id="FC02", bi_query_context=visible,
                       bi_readable_query_ids=sorted(context.readable_query_ids))
            self._save(db, row)
        return RuntimeContextBlock(source="boss-bi-query-context", content=encode({
            "runtime_configuration": json.loads(block.content), "bi_query_context": visible,
            "business_authority_granted": False,
        }))

    def hook_factory(self, context):
        binding = context.attributes.get(ATTRIBUTE)
        require(binding is not None and binding.recorder is self, "BI运行缺少实际关联")
        return Fc02RuntimeHook(self, binding.run_id)


class Fc02RuntimeHook(Fc01RuntimeHook):
    async def on_execute_tool_error(self, context, tool_call, tool, params, error):
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            row.setdefault("tool_errors", []).append({"tool_id": tool_call.name, "tool_call_id": tool_call.id,
                "error_type": type(error).__name__, "source_type": "SIMULATED"})
            self.recorder._save(db, row)
        raise RuntimeError("BI工具执行失败")

    async def after_execute_tool(self, context, tool_call, tool, params, result):
        await super().after_execute_tool(context, tool_call, tool, params, result)
        output = json.loads(result)
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            reference = next(item for item in row["tool_results"] if item["tool_call_id"] == tool_call.id)
            if tool_call.name == "query_metrics":
                matches = [item for item in tool.context().query_bindings
                           if checksum(json.loads(item.parameters_json)) == checksum(params)]
                require(len(matches) == 1, "BI结果没有匹配的可信查询条件")
                reference["bi_query_context"] = matches[0].visible()
            reference["definition_versions"] = sorted({item["definition_version"] for item in output.get("values", [])})
            reference["detail_refs"] = output.get("detail_refs", [item["record_id"] for item in output.get("original_records", [])])
            self.recorder._save(db, row)
