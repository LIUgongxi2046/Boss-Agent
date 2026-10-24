import json

from nanobot import RuntimeContextBlock

from business import checksum, encode, require
from boss_runtime_records import ATTRIBUTE, RuntimeRecordHook
from fc04_agent import Fc04ReadTool, TOOLS
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder, Fc01RuntimeHook, Fc01SimulatedProvider


class Fc04SimulatedProvider(Fc01SimulatedProvider):
    async def chat(self, messages, tools=None, model=None, **kwargs):
        require({item["function"]["name"] for item in tools or []} == TOOLS, "提醒模型工具超出批准读取范围")
        return await super().chat(messages, tools, model, **kwargs)


class Fc04RuntimeRecorder(Fc01RuntimeRecorder):
    def __init__(self, store, namespace, registry, runtime_snapshot, context_provider):
        super().__init__(store, namespace, registry, runtime_snapshot)
        self.context_provider = context_provider

    async def context(self, request):
        context = Fc04ReadTool(self.store, self.context_provider).context(runtime=False)
        require(context.owner_id == request.sender_id and context.namespace == self.namespace, "提醒运行身份不符")
        block = await super().context(request)
        binding = request.attributes[ATTRIBUTE]
        safe = {"projection": "notifications", "projection_sha256": context.projection_sha256}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._read(db, binding.run_id)
            row.update(feature_id="FC04", reminder_context=safe)
            self._save(db, row)
        return RuntimeContextBlock(source="boss-reminder-context", content=encode({
            "runtime_configuration": json.loads(block.content), "reminder_context": safe,
            "business_authority_granted": False, "owner_decision_required": True}))

    def hook_factory(self, context):
        binding = context.attributes.get(ATTRIBUTE)
        require(binding is not None and binding.recorder is self, "提醒运行缺少实际关联")
        return Fc04RuntimeHook(self, binding.run_id)


class Fc04RuntimeHook(Fc01RuntimeHook):
    async def on_execute_tool_error(self, context, tool_call, tool, params, error):
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            row.setdefault("tool_errors", []).append({"tool_id": tool_call.name, "tool_call_id": tool_call.id,
                "error_type": type(error).__name__, "source_type": "SIMULATED"})
            self.recorder._save(db, row)
        raise RuntimeError("经营提醒读取失败")

    async def after_execute_tool(self, context, tool_call, tool, params, result):
        await RuntimeRecordHook.after_execute_tool(self, context, tool_call, tool, params, result)
        output = json.loads(result)
        safe = {"projection": "notifications", "result_sha256": checksum(output),
            "rule_versions": [item["version"] for item in output["rules"]],
            "event_refs": [{key: item[key] for key in ("event_id", "version", "state") if key in item} for item in output["events"]],
            "dispatch_refs": [{key: item[key] for key in ("event_id", "event_version", "rule_version", "schedule_version", "state", "reason") if key in item} for item in output["dispatches"]]}
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            next(item for item in row["tool_results"] if item["tool_call_id"] == tool_call.id).update(safe)
            self.recorder._save(db, row)
