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
            "available_tool_names": sorted(context.allowed_tools),
            "adopted_sops": request.attributes.get("boss_sop_reference", []),
            "capability_guidance": (
                "当前产品名称为 Boss Agent。本次工具定义与 available_tool_names 是当前会话完整的可调用工具目录。"
                "背景说明、上游使用说明和技能目录中的工具名称不表示当前产品已经接入这些能力。"
                "介绍自身能力时仅依据当前目录；未列出的网页搜索、文件编辑、进程执行、调度和图像生成均不可宣称可以调用。"
                "仅 adopted_sops 中的方法可以描述为本轮已经采用，技能文件存在不表示方法已经执行。"
                "普通知识解释、写作、翻译和连续追问可以直接回答，无需要求业务对象或来源编号。"
                "需要业务事实时调用获准工具，依据真实返回形成结论；未执行的读取、修改或验证不可描述为完成。"
                "业务回答面向老板，使用姓名、中文业务状态和易读日期，说明影响、期限和需要本人决定的事项。"
                "内部编号、字段名称、英文状态及版本信息保留在工具详情；用户明确询问技术问题时再解释这些内容。"
                "资料不足时用自然业务语言说明尚未确认的内容，不直接展示内部错误码或字段清单。"
                "复杂业务分析应自主选择下一项读取，直到足以回答问题或明确缺少的依据；无需等待用户逐项指挥。"
                "开始时用简短说明交付目标和拟核查内容；执行过程由真实工具事件展示，不编写完成清单冒充执行。"
                "发现问题时首先核查范围、日期和指标单位，再核查原文、关联事项和当前进度。"
                "工具返回的 insights 是确定性条件检查结果，可作为调查线索；其中的影响和建议尚未执行，不能当作已证明的根因。"
                "会议与资料检查使用 bossMeetingsRead 返回的 library.records 和 library.insights；任务检查使用 bossTasksRead。"
                "需要根因分析时，沿返回的 source_refs 调用 bossEvidenceRead，必要时使用其他获准工具交叉核查。"
                "bossEvidenceRead 的 source 只能使用已返回的 documents.source_id 或 source_refs.source_id；事件、任务、会议编号不能作为材料编号。"
                "每项结论区分已证实事实、待验证原因与建议行动。计算金额影响必须具备同范围、同期间、同单位的数量和单价。"
                "跨对象关联必须有明确的关联字段或原文依据；标题相似、日期接近不能证明属于同一会议或任务。"
                "期限采用工具的 business_clock 和 deadline_checks，禁止采用系统日期。期限尚未到达时不得描述为逾期。"
                "不确定关联只能提出核查问题；影响和最终建议中也不得把该关联写成确定依赖或根因。"
                "批准后版本递增本身不表示审批失效，判断须采用当前业务状态和授权记录。建议期限与已约定期限必须明确区分。"
                "交付采用老板可使用的简报：最需要关注的问题、具体依据、可能影响、可选行动、建议负责人和时间。"
                "用户要求方案比较时给出各方案条件与取舍；用户要求行动时准备可确认的内容，业务执行保持本人确认流程。"
                "完成前核对问题是否得到回答、证据是否支持结论、是否仍有需要用户补充的关键内容。"
            ),
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
                    if row["status"] == "SUCCEEDED" and reference["required_input_count"] and not row.get("external_model_invoked"):
                        row.update(status="WAITING_INPUT", stop_reason="required_input")
                        self.recorder._save(db, row)
                self.recorder.intent_adapter.finish(reference["client_request_id"])
        finally:
            self.recorder.deadlines.pop(self.run_id, None)
