import json
from uuid import uuid4

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.agent.tools.context import current_request_context

from business import checksum, require
from boss_runtime_records import ATTRIBUTE, RuntimeRecorder, RuntimeRecordHook


class Fc01SimulatedProvider(LLMProvider):
    source_type = "SIMULATED"

    def __init__(self, event_producer):
        super().__init__(provider_name="deepseek")
        require(callable(event_producer), "缺少明确模拟的模型事件生产者")
        self.event_producer = event_producer

    def get_default_model(self):
        return "deepseek-flash"

    async def chat(self, messages, tools=None, model=None, **kwargs):
        # 事件生产者读取实际工具消息；该适配没有网络客户端。
        request = current_request_context()
        require(request is not None, "模拟事件缺少实际Runtime请求")
        binding = request.attributes.get(ATTRIBUTE)
        require(binding is not None and isinstance(binding.recorder, Fc01RuntimeRecorder), "模拟事件缺少FC01记录器")
        recorder, event_id = binding.recorder, "sim-model-" + str(uuid4())
        with recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = recorder._read(db, binding.run_id)
            require(checksum(tools) == row["tool_config_sha256"], "模拟模型事件的工具配置已经变化")
            row.setdefault("simulated_model_events", []).append({"event_id": event_id, "state": "REQUESTED",
                "source_type": "SIMULATED", "request_sha256": checksum(messages), "usage": None, "cost_total": None})
            recorder._save(db, row)
        response = await self.event_producer(messages, tools)
        require(isinstance(response, LLMResponse) and response.usage is None,
                "模拟模型事件必须明确类型且保持未知用量")
        with recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = recorder._read(db, binding.run_id)
            event = next(item for item in row["simulated_model_events"] if item["event_id"] == event_id)
            event.update(state="RESPONSE_RECEIVED", finish_reason=response.finish_reason,
                         tool_call_ids=[call.id for call in response.tool_calls])
            recorder._save(db, row)
        return response

    async def chat_with_retry(self, messages, tools=None, model=None, **kwargs):
        return await self.chat(messages, tools, model, **kwargs)

    async def chat_stream_with_retry(self, messages, tools=None, model=None, **kwargs):
        response = await self.chat(messages, tools, model, **kwargs)
        callback = kwargs.get("on_content_delta")
        if callback is not None and response.content:
            await callback(response.content)
        return response


class Fc01RuntimeRecorder(RuntimeRecorder):
    async def context(self, request):
        block = await super().context(request)
        binding = request.attributes[ATTRIBUTE]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._read(db, binding.run_id)
            row.update(source_type="SIMULATED", external_model_invoked=False,
                       external_delivery_verified=False, feature_id="FC01")
            self._save(db, row)
        return block

    def hook_factory(self, context):
        binding = context.attributes.get(ATTRIBUTE)
        require(binding is not None and binding.recorder is self, "当前运行缺少可信关联")
        return Fc01RuntimeHook(self, binding.run_id)


class Fc01RuntimeHook(RuntimeRecordHook):
    async def on_execute_tool_error(self, context, tool_call, tool, params, error):
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            row.setdefault("tool_errors", []).append({"tool_id": tool_call.name,
                "tool_call_id": tool_call.id, "error_type": type(error).__name__, "source_type": "SIMULATED"})
            self.recorder._save(db, row)
        raise RuntimeError("FC01工具执行失败")

    async def after_execute_tool(self, context, tool_call, tool, params, result):
        await super().after_execute_tool(context, tool_call, tool, params, result)
        output = json.loads(result)
        # 只保存版本、摘要与来源标识，正文及原始参数保持在受控业务对象中。
        safe = {key: output[key] for key in ("source_type", "source_id", "version", "review_sha256", "preparation_sha256", "owner_decision_required") if key in output}
        if "source_refs" in output:
            safe["source_refs"] = output["source_refs"]
        if "sources" in output:
            safe["source_refs"] = [{key: source[key] for key in ("source_id", "version")} for source in output["sources"]]
        if tool_call.name == "read_evidence":
            safe["query_id"] = params["query_id"]
        if "coordinate_input" in output:
            safe["origin"] = {key: output["coordinate_input"][key] for key in
                              ("interface_id", "origin_entity_type", "origin_record_id", "origin_version", "review_sha256")}
        safe["result_sha256"] = checksum(output)
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            reference = next(item for item in row["tool_results"] if item["tool_call_id"] == tool_call.id)
            reference.update(safe)
            self.recorder._save(db, row)

    def _finish(self, context):
        super()._finish(context)
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            row.update(model_completion_observed=False, model_behavior_evaluation_passed=False,
                       usage=None, cost_total=None, price_version=None)
            for event in row.get("simulated_model_events", []):
                if event["state"] == "REQUESTED":
                    event["state"] = row["status"]
            self.recorder._save(db, row)
