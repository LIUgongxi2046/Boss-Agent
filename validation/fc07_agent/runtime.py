import json

from nanobot import RuntimeContextBlock

from business import checksum, encode, require
from boss_runtime_records import ATTRIBUTE, RuntimeRecordHook
from fc07_agent import Fc07ReadTool, TOOLS
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder, Fc01RuntimeHook, Fc01SimulatedProvider


class Fc07SimulatedProvider(Fc01SimulatedProvider):
    async def chat(self, messages, tools=None, model=None, **kwargs):
        require({item["function"]["name"] for item in tools or []} == TOOLS, "交办模型工具超出批准范围")
        return await super().chat(messages, tools, model, **kwargs)


class Fc07RuntimeRecorder(Fc01RuntimeRecorder):
    def __init__(self, store, namespace, registry, runtime_snapshot, context_provider):
        super().__init__(store, namespace, registry, runtime_snapshot)
        self.context_provider = context_provider

    async def context(self, request):
        context = Fc07ReadTool(self.store, self.context_provider, "read_assignment").context(runtime=False)
        require(context.owner_id == request.sender_id and context.namespace == self.namespace, "交办运行身份不符")
        block = await super().context(request)
        safe = {key: getattr(context, key) for key in ("task_id", "task_version", "review_sha256")}
        binding = request.attributes[ATTRIBUTE]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._read(db, binding.run_id)
            row.update(feature_id="FC07", assignment_context=safe)
            self._save(db, row)
        return RuntimeContextBlock(source="boss-assignment-context", content=encode({
            "runtime_configuration": json.loads(block.content), "assignment_context": safe,
            "owner_decision_required": True, "business_authority_granted": False}))

    def hook_factory(self, context):
        binding = context.attributes.get(ATTRIBUTE)
        require(binding is not None and binding.recorder is self, "交办运行缺少实际关联")
        return Fc07RuntimeHook(self, binding.run_id)


class Fc07RuntimeHook(Fc01RuntimeHook):
    async def on_execute_tool_error(self, context, tool_call, tool, params, error):
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            row.setdefault("tool_errors", []).append({"tool_id": tool_call.name, "tool_call_id": tool_call.id,
                "error_type": type(error).__name__, "source_type": "SIMULATED"})
            self.recorder._save(db, row)
        raise RuntimeError("交办读取工具执行失败")

    async def after_execute_tool(self, context, tool_call, tool, params, result):
        await RuntimeRecordHook.after_execute_tool(self, context, tool_call, tool, params, result)
        output = json.loads(result)
        task = output.get("task", output)
        safe = {key: task[key] for key in ("task_id", "version", "status") if key in task}
        safe["result_sha256"] = checksum(output)
        if "sources" in output:
            safe["source_refs"] = [{key: source[key] for key in ("source_id", "pinned_version", "current_version", "source_status")} for source in output["sources"]]
            safe["review_sha256"] = output["review_sha256"]
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            next(item for item in row["tool_results"] if item["tool_call_id"] == tool_call.id).update(safe)
            self.recorder._save(db, row)
