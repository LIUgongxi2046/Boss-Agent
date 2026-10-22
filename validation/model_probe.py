import asyncio
import copy
import hashlib
import json
import os
import uuid
from pathlib import Path

from nanobot import Nanobot, RuntimeContextBlock
from nanobot.agent.hook import AgentHook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config, resolve_config_env_vars

from business import OPERATIONS, ROOT, SPEC, Store, encode, now
from connection import RecordedProvider, settings


class BusinessTool(Tool):
    def __init__(self, operation, store, envelope, bindings, records):
        self.operation, self.store, self.envelope = operation, store, envelope
        self.bindings, self.records = bindings, records

    @property
    def name(self):
        return self.operation

    @property
    def description(self):
        return {"query_metrics": "查询已授权经营明细并计算指标。", "read_evidence": "读取已有查询对应的原始资料和明细。", "create_assignment": "按当前老板授权创建交办。", "send_assignment": "按当前老板授权模拟发送交办。", "read_assignment": "重新查询交办的正式状态。"}[self.operation]

    @property
    def parameters(self):
        ref = OPERATIONS[self.operation]["input_schema"].rsplit("/", 1)[1]
        schema = copy.deepcopy(SPEC["io_schema"]["$defs"][ref])
        injected = {"envelope", "authorization_id", "idempotency_key"}
        schema["properties"] = {k: v for k, v in schema["properties"].items() if k not in injected}
        schema["required"] = [k for k in schema["required"] if k not in injected]
        schema["$defs"] = {"identifier": SPEC["io_schema"]["$defs"]["identifier"]}
        return schema

    async def execute(self, **kwargs):
        payload = {**kwargs, "envelope": self.envelope, **self.bindings.get(self.operation, {})}
        result = self.store.invoke(self.operation, payload)
        self.records.append({"type": "tool", "name": self.operation, "input": payload, "output": result, "at": now()})
        return encode(result)


class Audit(AgentHook):
    def __init__(self, output, records):
        super().__init__(reraise=True)
        self.output, self.records = output, records
        self.runtime_snapshot = None

    async def before_run(self, context):
        if self.runtime_snapshot is not None:
            self.records.append({"type": "runtime_admission", "configuration": self.runtime_snapshot(), "at": now()})
            self.output.write_text(json.dumps(self.records, ensure_ascii=False, indent=2))

    async def after_iteration(self, context):
        self.records.append({"type": "iteration", "iteration": context.iteration, "usage": context.usage.to_dict() if context.usage else None, "stop_reason": context.stop_reason, "error": context.error, "at": now()})
        self.output.write_text(json.dumps(self.records, ensure_ascii=False, indent=2))
        if context.error:
            raise RuntimeError(context.error)

    async def before_execute_tools(self, context):
        for call in context.tool_calls:
            tool = self.registry.get(call.name)
            if tool is None:
                raise ValueError("模型请求了未注册的工具")
            errors = tool.validate_params(call.arguments)
            if errors:
                self.records.append({"type": "tool_validation_error", "name": call.name, "errors": errors, "at": now()})
                self.output.write_text(json.dumps(self.records, ensure_ascii=False, indent=2))
                raise ValueError("工具参数不符合已发布 Schema")

    async def on_execute_tool_error(self, context, tool_call, tool, params, error):
        self.records.append({"type": "tool_error", "name": tool_call.name, "error": str(error), "at": now()})
        self.output.write_text(json.dumps(self.records, ensure_ascii=False, indent=2))
        raise RuntimeError("业务工具执行失败")


async def run_once(model, iteration):
    run_id = f"deepseek-{iteration}-{uuid.uuid4()}"
    work = ROOT / ".work" / run_id
    output = ROOT.parent / "evidence/T02" / run_id
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    input_files = [ROOT / "model_probe.py", ROOT / "business.py", ROOT / "connection.py", ROOT / "uv.lock", ROOT.parent / "specs/selection-probe.json"]
    inputs = {str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in input_files}
    (output / "inputs.json").write_text(encode({"at": now(), "files": inputs}))
    store = Store(work / "business.sqlite")
    baseline = store.initialize(run_id)
    config_path = work / "config.json"
    config_path.write_text(encode({"agents": {"defaults": {"provider": "deepseek", "model": model, "workspace": str(work / "workspace"), "maxToolIterations": 12, "maxTokens": 4096, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0, "timezone": "Asia/Shanghai"}}, "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": os.environ["DEEPSEEK_BASE_URL"], "extraBody": {"thinking": {"type": "disabled"}}}}, "gateway": {"heartbeat": {"enabled": False}}, "tools": {"restrictToWorkspace": True}}))
    config = resolve_config_env_vars(load_config(config_path), config_path=config_path)
    registry = ToolRegistry()
    provider = RecordedProvider(settings(), output / "http-requests.json")
    provider.generation = config.resolve_preset().to_generation_settings()
    loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider)
    for name in list(registry.tool_names):
        registry.unregister(name)
    envelope = {"request_id": run_id, "owner_id": "boss-1", "execution_namespace": run_id, "dataset_id": "selection", "dataset_version": "1", "session_id": run_id}
    bindings, records = {}, []
    for operation in OPERATIONS:
        registry.register(BusinessTool(operation, store, envelope, bindings, records))
    audit = Audit(output / "events.json", records)
    audit.registry = registry
    async with Nanobot(loop, config=config) as bot:
        async def context(request):
            return RuntimeContextBlock(source="boss-confirmed-memory", content=encode(store.context(run_id)))
        bot.runtime.add_context_provider(context)

        async def turn(text, session):
            records.append({"type": "instruction", "text": text, "session": session, "at": now()})
            async with asyncio.timeout(120):
                result = await bot.run(text, session_key=session, sender_id="boss-1", hooks=[audit])
            records.append({"type": "result", "content": result.content, "tools_used": result.tools_used, "usage": result.usage.to_dict() if result.usage else None, "stop_reason": result.stop_reason, "error": result.error, "metadata": result.metadata, "at": now()})
            audit.output.write_text(json.dumps(records, ensure_ascii=False, indent=2))
            if result.error or result.stop_reason != "completed":
                raise RuntimeError(f"模型运行终止：{result.error or result.stop_reason}")
            return result

        query = "查询合成 region-1 的 product-1 和 product-2 水产饲料外销经营情况，比较 2026-10-01 至 2026-10-10 与 2026-09-01 至 2026-09-10，CNY，EXTERNAL_SALES，definition_version=1。需要 sales_quantity、revenue、cost、gross_profit、gross_margin、gross_profit_per_tonne，并读取原始依据。原因资料缺少时说明未知。"
        await turn(query, run_id)
        content = {"content_version": "1", "coordinator_id": "coordinator-1", "purpose": "提交当前会议关联的毛利变化解释、措施和证据", "due_at": "2026-10-25T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["原因明细", "措施及证据"], "related_meeting_id": "meeting-1", "related_event_ids": ["event-1"], "source_refs": ["finance-note"]}
        auth_id = store.authorize(run_id, "create_assignment", content)
        bindings["create_assignment"] = {"authorization_id": auth_id, "idempotency_key": "create-1"}
        await turn("本人授权按以下内容创建交办：" + encode(content), run_id)
        tasks = [r["output"] for r in records if r["type"] == "tool" and r["name"] == "create_assignment"]
        assert tasks, "模型未执行创建交办"
        task = tasks[-1]
        send = {"task_id": task["task_id"], "task_version": "1", "recipient_id": "coordinator-1", "body": content["purpose"], "content_version": "1"}
        auth_id = store.authorize(run_id, "send_assignment", send)
        bindings["send_assignment"] = {"authorization_id": auth_id, "idempotency_key": "send-1"}
        await turn("本人授权按以下内容模拟发送交办：" + encode(send), run_id)
        await turn("重新查询交办 " + task["task_id"] + " 的正式状态与消息关联。", run_id + "-readback")
        names = {r["name"] for r in records if r["type"] == "tool"}
        assert set(OPERATIONS) <= names, "共同任务工具过程不完整"
        saved = store.invoke("read_assignment", {"envelope": envelope, "task_id": task["task_id"]})
        assert saved["status"] == "WAITING_FEEDBACK" and len(saved["message_ids"]) == 1
        transport = [record for record in provider.requests if record["type"] == "request"]
        assert transport and all(record["url"].endswith("/chat/completions") for record in transport)
        response_ids = sorted({record["response_id"] for record in provider.requests if record.get("response_id")})
        assert response_ids, "服务响应标识缺少"
        assert all(hashlib.sha256(path.read_bytes()).hexdigest() == inputs[str(path.relative_to(ROOT.parent))] for path in input_files), "模型检查期间输入文件发生变化"
        (output / "result.json").write_text(json.dumps({"status": "PASS", "scope": "SDK 共同任务；完整 A02 仍需其他断言", "provider": "deepseek", "model_id": model, "observed_api_type": "chat_completions", "transport_evidence": "http-requests.json", "baseline": baseline, "state": saved, "cost": None, "at": now()}, ensure_ascii=False, indent=2))
        print(json.dumps({"run_id": run_id, "status": "PASS", "evidence": str(output)}, ensure_ascii=False))


async def main():
    settings()
    required = ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        result = {"status": "BLOCKED", "provider": "deepseek", "request_sent": False, "missing_configuration": missing, "usage": None, "cost": None, "at": now()}
        output = ROOT.parent / "evidence/T02"
        output.mkdir(parents=True, exist_ok=True)
        content = json.dumps(result, ensure_ascii=False, indent=2)
        (output / ("model-preflight-" + str(uuid.uuid4()) + ".json")).write_text(content)
        (output / "model-preflight.json").write_text(content)
        raise SystemExit(encode(result))
    if os.environ["DEEPSEEK_MODEL"] != "deepseek-flash":
        raise ValueError("当前接入定义仅核查 deepseek-flash；其他型号需要重新核查实际协议")
    for iteration in range(2):
        await run_once(os.environ["DEEPSEEK_MODEL"], iteration)


if __name__ == "__main__":
    asyncio.run(main())
