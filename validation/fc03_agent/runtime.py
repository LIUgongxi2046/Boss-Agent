import json

from nanobot import RuntimeContextBlock

from business import checksum, encode, require
from boss_runtime_records import ATTRIBUTE
from fc03_agent import Fc03TodayTool, TOOLS
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder, Fc01RuntimeHook, Fc01SimulatedProvider


class Fc03SimulatedProvider(Fc01SimulatedProvider):
    def __init__(self, event_producer, *, allowed_tools=TOOLS):
        super().__init__(event_producer)
        self.allowed_tools = frozenset(allowed_tools)

    async def chat(self, messages, tools=None, model=None, **kwargs):
        require({item["function"]["name"] for item in tools or []} == self.allowed_tools,
                "晨间模型工具超出批准读取范围")
        return await super().chat(messages, tools, model, **kwargs)


class Fc03RuntimeRecorder(Fc01RuntimeRecorder):
    def __init__(self, store, namespace, registry, runtime_snapshot, context_provider):
        super().__init__(store, namespace, registry, runtime_snapshot)
        self.context_provider = context_provider

    async def context(self, request):
        tool = self.registry.get("todayRead")
        require(isinstance(tool, Fc03TodayTool), "晨间实际读取工具尚未注册")
        context = tool.context(require_runtime=False)
        require(context.owner_id == request.sender_id and context.namespace == self.namespace,
                "晨间运行与可信本人范围不符")
        require(not tool.validate_params(json.loads(context.read_parameters_json)), "晨间可信输入不符合当前Schema")
        selected = None
        if context.selected_list_id is not None or context.selected_item_id is not None:
            from fc03_agent.formal import FormalMorningTool
            require(isinstance(tool, FormalMorningTool), "当前事项讨论需要正式晨间工具")
            selected = tool.selected_reference(context)
            require(tool.context(require_runtime=False) == context, "当前事项准备期间认证范围已经变化")
        block = await super().context(request)
        binding = request.attributes[ATTRIBUTE]
        reference = {key: getattr(context, key) for key in ("date", "timezone", "snapshot_sha256", "order_version")}
        reference["parameters_sha256"] = checksum(json.loads(context.read_parameters_json))
        reference["client_request_id"] = context.client_request_id
        if selected is not None:
            reference["selected_item_ref"] = selected
        if context.source_selection_json is not None:
            reference["source_selection"] = json.loads(context.source_selection_json)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._read(db, binding.run_id)
            row.update(feature_id="FC03", morning_context=reference)
            self._save(db, row)
        return RuntimeContextBlock(source="boss-morning-context", content=encode({
            "runtime_configuration": json.loads(block.content), "morning_context": reference,
            "business_authority_granted": False,
        }))

    def hook_factory(self, context):
        binding = context.attributes.get(ATTRIBUTE)
        require(binding is not None and binding.recorder is self, "晨间运行缺少实际关联")
        return Fc03RuntimeHook(self, binding.run_id)


class Fc03RuntimeHook(Fc01RuntimeHook):
    def check_cancellation(self):
        super().check_cancellation()
        self.recorder.context_provider()

    async def on_execute_tool_error(self, context, tool_call, tool, params, error):
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            row.setdefault("tool_errors", []).append({"tool_id": tool_call.name, "tool_call_id": tool_call.id,
                "error_type": type(error).__name__, "source_type": "SIMULATED"})
            self.recorder._save(db, row)
        raise RuntimeError("晨间读取工具执行失败")

    async def after_execute_tool(self, context, tool_call, tool, params, result):
        await super().after_execute_tool(context, tool_call, tool, params, result)
        output = json.loads(result)
        view = output.get("result", output)
        safe = {key: view[key] for key in ("date", "timezone", "snapshot_sha256", "order_version", "business_clock", "list_id", "list_version") if key in view}
        items = view.get("items", [view["item"]] if "item" in view else [])
        safe["item_refs"] = [{key: item[key] for key in ("item_id", "object_id", "version", "source_refs")} for item in items]
        if "document" in output:
            safe["document_ref"] = {key: output["document"][key] for key in ("source_id", "version")}
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            reference = next(item for item in row["tool_results"] if item["tool_call_id"] == tool_call.id)
            reference.update(safe)
            self.recorder._save(db, row)
