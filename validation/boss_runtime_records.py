import asyncio
import hashlib
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from aiohttp import web
from nanobot import RuntimeContextBlock
from nanobot.agent.hook import AgentHook
from nanobot.agent.tools.context import current_request_context

from business import checksum, encode, now, require
from boss_execution_scope import NAMESPACE
from boss_memory_runtime import MemoryContextInvalidated, require_current_memory_reference
from boss_prompt_config import _record_runtime_context_load, _select_runtime_prompts
from runtime_records_query import read_runtime_records

ATTRIBUTE = "boss_runtime_binding"


@dataclass(frozen=True)
class RuntimeBinding:
    recorder: object
    run_id: str
    request_id: str
    session_id: str
    context_block: RuntimeContextBlock


class RuntimeRecorder:
    def __init__(self, store, namespace, registry, runtime_snapshot):
        self.store = store
        self.namespace = namespace
        self.registry = registry
        self.runtime_snapshot = runtime_snapshot
        self.deadline_expired = None
        self.model_deadlines = {}

    def _read(self, db, run_id):
        return self.store.get(db, self.namespace, "runtime_run", run_id)

    def _save(self, db, row):
        self.store.put(db, self.namespace, "runtime_run", row["run_id"], row)

    def _binding(self):
        request = current_request_context()
        require(request is not None, "运行请求上下文缺少")
        binding = request.attributes.get(ATTRIBUTE)
        require(isinstance(binding, RuntimeBinding) and binding.recorder is self, "运行上下文尚未关联")
        return binding

    async def context(self, request):
        require(request.sender_id == "boss-1", "仅允许本人创建模型运行", web.HTTPForbidden)
        require(isinstance(request.session_key, str) and request.session_key, "运行会话标识缺少")
        existing = request.attributes.get(ATTRIBUTE)
        if existing is not None:
            require(isinstance(existing, RuntimeBinding) and existing.recorder is self, "运行上下文归属不符")
            return existing.context_block
        effective = self.runtime_snapshot()
        definitions = self.registry.get_definitions()
        memory_reference = request.attributes.get("boss_memory_reference")
        memory_fields = {"memory_id", "version", "confirmation_state", "eligible", "confirmation_authority_checked"}
        require(memory_reference is None or isinstance(memory_reference, dict) and set(memory_reference) == memory_fields,
                "记忆采用元信息格式无效")
        implementations = {}
        for name in self.registry.tool_names:
            source_path = inspect.getsourcefile(type(self.registry.get(name)))
            require(source_path is not None, "当前工具实现来源无法核查")
            implementations[name] = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, self.namespace)
            configuration = self.store.get(db, self.namespace, "configuration", "current")
            dataset = self.store.get(db, self.namespace, "initial", "snapshot")
            require(configuration["enabled"] is True, "当前模型配置已停用")
            for field in ("provider", "model_id", "api_type", "max_tool_rounds", "timeout"):
                require(configuration[field] == effective[field], "当前配置尚未被Runtime采用：" + field)
            require(set(self.registry.tool_names) <= set(configuration["tool_scope"]),
                    "当前工具超出已启用配置范围", web.HTTPForbidden)
            selected = _select_runtime_prompts(self.store, db, self.namespace)
            prompts = [{key: item[key] for key in ("kind", "prompt_id", "prompt_version", "active_version", "source_refs")}
                       | {"content_sha256": checksum(item["instruction_text"])} for item in selected]
            run_id = "run-" + str(uuid4())
            request_id = request.message_id or request.turn_id or "request-" + str(uuid4())
            row = {
                "run_id": run_id, "session_id": request.session_key, "request_id": request_id,
                "request_id_source": "MESSAGE" if request.message_id else "TURN" if request.turn_id else "SERVER_GENERATED",
                "chat_id": request.chat_id, "turn_id": request.turn_id, "namespace": self.namespace,
                "dataset_id": dataset["dataset_id"], "dataset_version": dataset["dataset_version"],
                "configuration_version": configuration["version"], "configuration_id": configuration["config_id"],
                "runtime": {key: effective[key] for key in (
                    "provider", "model_id", "api_type", "max_tool_rounds", "max_output_tokens", "timeout", "config_sha256",
                )},
                "prompt_versions": prompts, "tool_config_sha256": checksum(definitions),
                "memory_reference": dict(memory_reference) if memory_reference is not None else None,
                "tool_configuration": [{"tool_id": definition["function"]["name"], "schema_sha256": checksum(definition),
                                        "implementation_sha256": implementations[definition["function"]["name"]],
                                        "implementation": type(self.registry.get(definition["function"]["name"])).__module__
                                        + "." + type(self.registry.get(definition["function"]["name"])).__qualname__}
                                       for definition in definitions],
                "status": "QUEUED", "stop_reason": None, "started_at": now(), "finished_at": None,
                "tool_results": [], "model_requests": [], "usage": None, "cost_total": None,
                "price_version": None, "usage_coverage": "NOT_OBSERVED", "private_body_recorded": False,
                "model_completion_observed": False, "model_behavior_evaluation_passed": False,
                "model_attempts_coverage": "HTTP_REQUESTS_OBSERVED_ONLY",
            }
            if configuration.get("model_connection"):
                row["model_connection"] = dict(configuration["model_connection"])
            self._save(db, row)
            _record_runtime_context_load(self.store, db, selected, self.namespace)
        block = RuntimeContextBlock(source="boss-runtime-configuration", content=encode({
            "run_id": run_id, "configuration_version": row["configuration_version"],
            "maintained_prompts": selected,
            "technical_configuration_grants_business_authority": False,
        }))
        request.attributes[ATTRIBUTE] = RuntimeBinding(self, run_id, request_id, request.session_key, block)
        return block

    def hook_factory(self, context):
        binding = context.attributes.get(ATTRIBUTE)
        require(isinstance(binding, RuntimeBinding) and binding.recorder is self, "运行Hook缺少已核查上下文")
        return RuntimeRecordHook(self, binding.run_id)

    def observe_transport(self, event):
        binding = self._binding()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._read(db, binding.run_id)
            require(row["status"] == "RUNNING", "模型请求没有关联活动运行")
            request_id = event["model_request_id"]
            if event["type"] == "request":
                if row.get("model_connection"):
                    row["external_model_invoked"] = True
                require(event["tool_config_sha256"] == row["tool_config_sha256"], "实际请求的工具定义与启用快照不符")
                require(event["model"] == row["runtime"]["model_id"], "实际模型与启用快照不符")
                require(not any(item["model_request_id"] == request_id for item in row["model_requests"]), "模型请求标识重复")
                row["model_requests"].append({
                    "model_request_id": request_id, "request_sha256": event["request_sha256"],
                    "tool_config_sha256": event["tool_config_sha256"], "http_status": None,
                    "response_ids": [], "usage": None, "finish_reasons": [],
                })
            else:
                matches = [item for item in row["model_requests"] if item["model_request_id"] == request_id]
                require(len(matches) == 1, "模型响应没有唯一的请求记录")
                item = matches[0]
                if event["type"] == "response":
                    item["http_status"] = event["status"]
                if event.get("response_id") and event["response_id"] not in item["response_ids"]:
                    item["response_ids"].append(event["response_id"])
                if event.get("usage") is not None:
                    usage = event["usage"]
                    require(all(type(usage.get(key)) is int and usage[key] >= 0
                                for key in ("prompt_tokens", "completion_tokens", "total_tokens")), "服务用量字段无效")
                    item["usage"] = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
                    item["usage"].update({key: usage[key] for key in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
                                          if type(usage.get(key)) is int and usage[key] >= 0})
                if event.get("finish_reasons"):
                    item["finish_reasons"] = event["finish_reasons"]
            self._save(db, row)
        return {"run_id": row["run_id"], "session_id": row["session_id"], "runtime_request_id": row["request_id"],
                "configuration_version": row["configuration_version"]}


class RuntimeRecordHook(AgentHook):
    def __init__(self, recorder, run_id):
        super().__init__(reraise=True)
        self.recorder = recorder
        self.run_id = run_id

    def check_cancellation(self):
        from boss_execution_transition import pending_transition
        with self.recorder.store.connect() as db:
            db.execute("BEGIN")
            row = self.recorder._read(db, self.run_id)
            transition = pending_transition(db, self.recorder.namespace)
            require_current_memory_reference(self.recorder.store, db, self.recorder.namespace, row.get("memory_reference"))
        if transition is not None:
            raise asyncio.CancelledError("EXECUTION_SPACE_TRANSITION")
        if row.get("cancel_request"):
            raise asyncio.CancelledError("OWNER_REQUESTED_CANCELLATION")
        if self.run_id in self.recorder.model_deadlines and asyncio.get_running_loop().time() >= self.recorder.model_deadlines[self.run_id]:
            raise TimeoutError("运行已超过当前模型配置的时间限制")

    async def before_iteration(self, context):
        self.check_cancellation()

    async def after_iteration(self, context):
        self.check_cancellation()

    async def on_stream(self, context, delta):
        self.check_cancellation()

    def finalize_content(self, context, content):
        self.check_cancellation()
        return content

    async def before_execute_tool(self, context, tool_call, tool, params):
        self.check_cancellation()

    async def before_run(self, context):
        self.check_cancellation()
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            require(row["status"] == "QUEUED", "当前运行已经开始")
            row["status"] = "RUNNING"
            if row.get("model_connection"):
                self.recorder.model_deadlines[self.run_id] = asyncio.get_running_loop().time() + row["runtime"]["timeout"]
            self.recorder._save(db, row)

    async def before_execute_tools(self, context):
        self.check_cancellation()
        with self.recorder.store.connect() as db:
            row = self.recorder._read(db, self.run_id)
        require(checksum(self.recorder.registry.get_definitions()) == row["tool_config_sha256"], "进行中运行的工具定义发生变化")
        for call in context.tool_calls:
            tool = self.recorder.registry.get(call.name)
            require(tool is not None, "模型调用了未启用工具", web.HTTPForbidden)
            require(not tool.validate_params(call.arguments), "工具输入不符合当前Schema", web.HTTPBadRequest)

    async def after_execute_tool(self, context, tool_call, tool, params, result):
        output = json.loads(result)
        reference = {"tool_id": tool_call.name, "tool_call_id": tool_call.id, "iteration": context.iteration}
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            for field, kind in (("query_id", "query"), ("task_id", "task"), ("message_id", "outbox")):
                if field == "query_id" and tool_call.name != "query_metrics":
                    continue
                if field in output:
                    self.recorder.store.get(db, self.recorder.namespace, kind, output[field])
                    reference[field] = output[field]
            for field in ("version", "task_version", "status", "task_status", "authorization_id"):
                if field in output:
                    reference[field] = output[field]
            row["tool_results"].append(reference)
            self.recorder._save(db, row)

    def _finish(self, context):
        with self.recorder.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.recorder._read(db, self.run_id)
            if row["finished_at"] is not None:
                return
            reason = context.stop_reason
            if isinstance(context.exception, MemoryContextInvalidated):
                status = "CANCELED"
                reason = "OWNER_MEMORY_CONTEXT_CHANGED"
            elif isinstance(context.exception, asyncio.CancelledError):
                status = "TIMED_OUT" if self.recorder.deadline_expired is not None and self.recorder.deadline_expired() else "CANCELED"
            elif isinstance(context.exception, TimeoutError):
                status = "TIMED_OUT"
            else:
                status = "SUCCEEDED" if reason == "completed" and not context.error else "FAILED"
            row.update(status=status, stop_reason=reason, finished_at=now(),
                       model_completion_observed=reason == "completed" and not context.error)
            if status == "TIMED_OUT" and isinstance(context.exception, asyncio.CancelledError):
                row["termination_source"] = "CALLER_DEADLINE_EXPIRED"
            observed = [item["usage"] for item in row["model_requests"] if item["usage"] is not None]
            row["usage"] = {key: sum(usage[key] for usage in observed)
                            for key in ("prompt_tokens", "completion_tokens", "total_tokens")} if observed else None
            if observed:
                for key in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                    row["usage"][key] = sum(usage[key] for usage in observed) if all(key in usage for usage in observed) else None
            row["usage_coverage"] = (
                "COMPLETE_OBSERVED_REQUESTS" if row["model_requests"] and all(
                    item["usage"] is not None and item["http_status"] == 200 and item["finish_reasons"]
                    for item in row["model_requests"]
                ) else "PARTIAL_OBSERVED_REQUESTS" if row["model_requests"] else "NOT_OBSERVED"
            )
            self.recorder._save(db, row)
        self.recorder.model_deadlines.pop(self.run_id, None)

    async def after_run(self, context):
        try:
            self.check_cancellation()
        finally:
            failure = sys.exception()
            if failure is not None:
                context.exception = failure
                context.stop_reason = "error"
                context.error = type(failure).__name__
        self._finish(context)

    async def on_finally(self, context):
        self._finish(context)


def runtime_records(store, role, namespace=NAMESPACE, run_id=None, query=None):
    return read_runtime_records(store, role, namespace, run_id, query)
