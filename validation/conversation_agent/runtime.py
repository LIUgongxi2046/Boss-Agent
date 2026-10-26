import asyncio
import json
import math

from nanobot import RuntimeContextBlock
from nanobot.agent.tools.context import current_request_context

from business import checksum, encode, require
from boss_execution_scope import NAMESPACE as NS
from boss_runtime_records import ATTRIBUTE, RuntimeRecordHook
from product_bi import PREPARING_REQUEST
from conversation_agent import ConversationReadTool
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder, Fc01RuntimeHook, Fc01SimulatedProvider


class ConversationSimulatedProvider(Fc01SimulatedProvider):
    def __init__(self, event_producer, scope):
        super().__init__(event_producer)
        self.scope = scope

    async def chat(self, messages, tools=None, model=None, **kwargs):
        context = self.scope.current()
        require({item["function"]["name"] for item in tools or []} == context.allowed_tools,
                "会话模型工具与当前可信范围不符")
        binding = current_request_context().attributes[ATTRIBUTE]
        require(isinstance(binding.recorder, ConversationRuntimeRecorder) and binding.run_id in binding.recorder.deadlines,
                "当前模型步骤缺少实际运行截止时间")
        async with asyncio.timeout_at(binding.recorder.deadlines[binding.run_id]):
            await asyncio.sleep(0)
            response = await super().chat(messages, tools, model, **kwargs)
            await asyncio.sleep(0)
            require(self.scope.current() == context, "模型步骤期间会话资料或认证已变化")
        return response


class ConversationRuntimeRecorder(Fc01RuntimeRecorder):
    def __init__(self, scope, registry, runtime_snapshot, *, intent_adapter=None):
        super().__init__(scope.store, NS, registry, runtime_snapshot)
        self.scope = scope
        self.intent_adapter = intent_adapter
        self.deadlines = {}

    async def context(self, request):
        token = PREPARING_REQUEST.set(request)
        try:
            return await self._context_for_request(request)
        finally:
            PREPARING_REQUEST.reset(token)

    async def _context_for_request(self, request):
        context = self.scope.current(request, require_runtime=False)
        require(set(self.registry.tool_names) == context.allowed_tools, "公共Registry尚未采用会话当前工具范围")
        require(all(isinstance(self.registry.get(name), ConversationReadTool) for name in context.allowed_tools),
                "公共Registry尚未采用会话可信读取适配")
        block = await super().context(request)
        binding = request.attributes[ATTRIBUTE]
        reference = {"input_sha256": context.input_sha256,
            "allowed_call_refs": [{"tool_id": name, "parameters_sha256": digest} for name, digest in sorted(context.allowed_calls)],
            "references": [{"kind": kind, "id": identifier, "version": version} for kind, identifier, version in context.references]}
        if self.intent_adapter is not None:
            reference.update(self.intent_adapter.runtime_reference(request))
            self.intent_adapter.bind_runtime(request, binding)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._read(db, binding.run_id)
            row.update(feature_id="N02", conversation_context=reference)
            self._save(db, row)
        return RuntimeContextBlock(source="boss-conversation-context", content=encode({
            "runtime_configuration": json.loads(block.content), "conversation_context": reference,
            "business_authority_granted": False}))

    def hook_factory(self, context):
        binding = context.attributes.get(ATTRIBUTE)
        require(binding is not None and binding.recorder is self, "会话运行缺少当前记录器")
        return ConversationRuntimeHook(self, binding.run_id)


class ConversationRuntimeHook(Fc01RuntimeHook):
    def check_cancellation(self):
        super().check_cancellation()
        self.recorder.scope.current()

    async def before_run(self, context):
        await super().before_run(context)
        with self.recorder.store.connect() as db:
            timeout = self.recorder._read(db, self.run_id)["runtime"]["timeout"]
        require(type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0,
                "实际启用的运行超时配置无效")
        # 每轮从实际RUNNING开始固定截止，后续模型步骤共用该计时。
        self.recorder.deadlines[self.run_id] = asyncio.get_running_loop().time() + timeout

    async def on_execute_tool_error(self, context, tool_call, tool, params, error):
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            row.setdefault("tool_errors", []).append({"tool_id": tool_call.name,
                "tool_call_id": tool_call.id, "error_type": type(error).__name__, "source_type": "SIMULATED"})
            self.recorder._save(db, row)
        raise RuntimeError("会话读取工具执行失败")

    async def after_execute_tool(self, context, tool_call, tool, params, result):
        output = json.loads(result)
        safe = {key: output[key] for key in ("source_type", "source_id", "version", "review_sha256") if key in output}
        safe.update(parameters_sha256=checksum(params), result_sha256=checksum(output))
        if tool_call.name == "query_metrics":
            matches = [item for item in tool.delegate.context().query_bindings
                       if checksum(json.loads(item.parameters_json)) == checksum(params)]
            require(len(matches) == 1, "当前查询结果缺少唯一正式输入范围")
            safe.update(bi_query_context=matches[0].visible(), source_refs=[{key: source[key] for key in ("source_id", "version")} for source in output["sources"]],
                definition_versions=sorted({item["definition_version"] for item in output["values"]}), detail_refs=output["detail_refs"])
        if output.get("kind") in {"query", "task", "morning_list", "message", "message_draft"} and "data" in output:
            kind, identifier, data = output["kind"], output["id"], output["data"]
            storage = {"query": "query", "task": "task", "morning_list": "morning_list", "message_draft": "message_draft"}
            with self.recorder.store.connect() as db:
                if kind == "message":
                    rows = db.execute("SELECT id FROM objects WHERE namespace=? AND id=? AND kind IN ('message_outbox','outbox')", (self.recorder.namespace, identifier)).fetchall()
                    require(len(rows) == 1, "消息产物缺少唯一正式存储记录")
                else:
                    self.recorder.store.get(db, self.recorder.namespace, storage[kind], identifier)
            field = {"query": "query_id", "task": "task_id", "morning_list": "list_id", "message": "message_id", "message_draft": "draft_id"}[kind]
            safe[field] = identifier
            if kind in {"task", "message_draft"} and "version" in data:
                safe["task_version" if kind == "task" else "version"] = data["version"]
        await RuntimeRecordHook.after_execute_tool(self, context, tool_call, tool, params, result)
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            reference = next(item for item in row["tool_results"] if item["tool_call_id"] == tool_call.id)
            reference.update(safe)
            self.recorder._save(db, row)

    def _finish(self, context):
        try:
            super()._finish(context)
            if self.recorder.intent_adapter is not None:
                with self.recorder.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = self.recorder._read(db, self.run_id)
                    reference = row["conversation_context"]
                    if row["status"] == "SUCCEEDED" and reference["required_input_count"]:
                        row.update(status="WAITING_INPUT", stop_reason="required_input")
                        self.recorder._save(db, row)
                self.recorder.intent_adapter.finish(reference["client_request_id"])
        finally:
            self.recorder.deadlines.pop(self.run_id, None)
