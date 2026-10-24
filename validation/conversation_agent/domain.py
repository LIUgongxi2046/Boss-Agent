from copy import deepcopy
from dataclasses import dataclass
import json

from aiohttp import web
from jsonschema import Draft202012Validator

from business import checksum, encode, require
from boss_conversation import ConversationAPI, SCHEMA, validate
from boss_page_api import BossPageAPI
from boss_runtime_records import ATTRIBUTE
from nanobot.agent.tools.context import current_request_context
from runtime_page_read_tools import _BossPageReadTool
from conversation_agent.queries import ConversationQueries


def branch(projection, properties=None):
    fields = {"projection": {"const": projection}, **(properties or {})}
    return {"type": "object", "additionalProperties": False, "required": list(fields), "properties": fields}


def artifact_digest(result):
    return checksum({key: result[key] for key in ("kind", "id", "data")})


class ConversationDomainReadTool(_BossPageReadTool):
    name = "conversationRead"
    description = "读取当前可信会话的实际运行、产物、本人消息历史或原生附件元数据；不发送消息、不签发授权，附件存在不表示成为业务来源。"

    def __init__(self, api, scope, attachments):
        super().__init__(api, "BOSS")
        self.scope, self.attachments = scope, attachments
        self.conversation = ConversationAPI(api.store)

    @property
    def parameters(self):
        artifact = {key: deepcopy(value) for key, value in SCHEMA["$defs"]["ArtifactInput"]["properties"].items()
                    if key not in {"session_id", "chat_id"}}
        return {"$defs": deepcopy(SCHEMA["$defs"]), "oneOf": [branch(name) for name in ("runs", "messages", "attachments")]
                + [branch("artifact", artifact), branch("record", {"kind": {"enum": ["task", "message", "message_draft"]},
                    "id": {"$ref": "#/$defs/Id"}})]}

    async def execute(self, **params):
        require(not list(Draft202012Validator(self.parameters).iter_errors(params)), "会话读取不符合正式投影参数", web.HTTPBadRequest)
        context = self.scope.current()
        query = {"session_id": context.session_id, "chat_id": context.chat_id}
        kind = params["projection"]
        if kind == "runs":
            result = self.conversation.read("BOSS", query)
        elif kind == "messages":
            result = self.conversation.messages("BOSS")
        elif kind == "attachments":
            result = self.attachments.read("BOSS", query)
        elif kind == "record":
            identifier, record_kind = params["id"], params["kind"]
            if record_kind == "task":
                tasks = self._read("/api/boss/ui/tasks")["tasks"]
                require(any(item["task_id"] == identifier for item in tasks), "任务不属于当前本人可读范围", web.HTTPForbidden)
                with self._api.store.connect() as db:
                    initial = self._api.store.get(db, "ui-check", "initial", "snapshot")
                    data = self._api.store.get(db, "ui-check", "task", identifier)
                    self._api.store.require_current_assignment_sources(db, "ui-check", initial, data)
            else:
                history = self.conversation.messages("BOSS")
                items = history["drafts"] if record_kind == "message_draft" else history["sent_messages"]
                field = "draft_id" if record_kind == "message_draft" else "message_id"
                matches = [item for item in items if item.get(field) == identifier]
                require(len(matches) == 1 and matches[0]["adoption_state"] == "CURRENT", "消息对象或当前来源不可采用", web.HTTPForbidden)
                data = matches[0]
            binding = current_request_context().attributes[ATTRIBUTE]
            result = validate("ArtifactResult", {"source_type": "SIMULATED", **query, "run_id": binding.run_id,
                "kind": record_kind, "id": identifier, "data": data, "evidence": None,
                "business_authorization_granted": False, "business_mutation_performed": False})
        else:
            result = self.conversation.artifact("BOSS", {**query, **{key: value for key, value in params.items() if key != "projection"}})
        return encode(result)


@dataclass(frozen=True)
class ConversationPlan:
    calls: tuple[tuple[str, str], ...]
    references: tuple[tuple[str, str, str | None], ...]
    required_inputs: tuple[str, ...]
    artifact_checks: tuple[tuple[str, str], ...] = ()
    query_bindings: tuple = ()
    pending_query_scope: str | None = None


class ConversationPlanner:
    def __init__(self, store):
        self.store, self.api = store, ConversationAPI(store)
        self.pages = BossPageAPI(store)

    def plan(self, text, query, previous_references, previous_artifacts=(), last_source_id=None, *, has_media=False, pending_query_scope=None):
        lowered = text.casefold()
        calls, references, required, checks = [], list(previous_references), [], list(previous_artifacts)
        def add(name, params):
            call = (name, encode(params))
            if call not in calls:
                calls.append(call)
        if any(word in lowered for word in ("不要", "不用", "不需要", "别执行")):
            return ConversationPlan((), tuple(references), ("请明确当前需要执行的读取动作",), tuple(checks))
        query_plan = ConversationQueries(self.store, self.api).plan(text, query, pending_query_scope)
        if query_plan.binding is not None:
            add("query_metrics", json.loads(query_plan.binding.parameters_json))
            references.extend(ref for ref in query_plan.references if ref not in references)
            if query_plan.parent is not None:
                parent = query_plan.parent
                check = (encode({key: parent[key] for key in ("run_id", "kind", "id")}), artifact_digest(parent))
                if check not in checks:
                    checks.append(check)
        required.extend(query_plan.required_inputs)
        if any(word in lowered for word in ("发送", "发信", "保存草稿", "拟消息", "写消息")):
            add("conversationRead", {"projection": "messages"})
            required.append("消息写入请采用当前本人消息编辑入口中的正式草稿、收件人、内容版本及有效授权")
        with self.store.connect() as db:
            initial = self.store.get(db, "ui-check", "initial", "snapshot")
            documents = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='document' AND json_extract(body,'$.access_scope')=? AND json_extract(body,'$.source_type')='SIMULATED'", (initial["owner_id"],))]
        selected = [document for document in documents if document["source_id"].casefold() in lowered
                    or document.get("title") and document["title"].casefold() in lowered]
        if not selected and any(word in lowered for word in ("继续", "这份", "该资料", "它的来源")):
            if last_source_id and any(word in lowered for word in ("资料", "原文", "来源", "版本")):
                selected = [document for document in documents if document["source_id"] == last_source_id]
        for document in selected:
            add("bossEvidenceRead", {"source": document["source_id"]})
            reference = ("document", document["source_id"], document["version"])
            if reference not in references:
                references.append(reference)
        if any(word in lowered for word in ("资料", "原文", "来源")) and not selected and not any(word in lowered for word in ("附件", "文件")):
            required.append("请明确当前来源ID或已有正式来源名称")
        if any(word in lowered for word in ("任务", "交办", "承诺")):
            status, tasks = self.pages.serve("BOSS", "/api/boss/ui/tasks")
            require(status == 200, "当前任务范围读取失败", web.HTTPConflict)
            matches = [item for item in tasks["tasks"] if item["task_id"].casefold() in lowered]
            if len(matches) == 1:
                add("conversationRead", {"projection": "record", "kind": "task", "id": matches[0]["task_id"]})
            else:
                add("bossTasksRead", {})
            if any(word in lowered for word in ("取消任务", "确认完成", "延期", "交办给", "批准")):
                required.append("任务变更请采用当前正式任务共享入口及匹配对象版本的本人有效决定")
        if any(word in lowered for word in ("会议", "会面")):
            add("bossMeetingsRead", {})
        if any(word in lowered for word in ("消息", "草稿", "联系人", "收件人", "待回复", "发件箱", "回复")):
            history = self.api.messages("BOSS")
            for item in history["drafts"] + history["sent_messages"]:
                for source in item["attachment_refs"]:
                    reference = ("document", source["source_id"], source["version"])
                    if source["status"] == "VALID" and reference not in references:
                        references.append(reference)
            matches = [(kind, item[field]) for kind, items, field in (("message_draft", history["drafts"], "draft_id"),
                       ("message", history["sent_messages"], "message_id")) for item in items
                       if item.get(field) and item[field].casefold() in lowered]
            if len(matches) == 1:
                kind, identifier = matches[0]
                add("conversationRead", {"projection": "record", "kind": kind, "id": identifier})
            else:
                add("conversationRead", {"projection": "messages"})
        if any(word in lowered for word in ("运行", "执行过程", "进度")):
            add("conversationRead", {"projection": "runs"})
        if has_media or any(word in lowered for word in ("附件", "文件", "上传")):
            add("conversationRead", {"projection": "attachments"})
            if not text.strip():
                required.append("请补充当前附件的用途或需要核查的事项")
            if any(word in lowered for word in ("计算", "分析", "作为依据")):
                required.append("附件需要另行建立有效正式业务来源引用，保存元数据不表示已处理正文")
        if any(word in lowered for word in ("概览", "目标", "今天有哪些", "今日工作")):
            add("bossDashboardRead", {})
        for words, projection in ((("通知", "提醒"), "notifications"), (("行程", "出行"), "travel"), (("日历", "安排"), "calendar"), (("研究",), "research")):
            if any(word in lowered for word in words):
                add("bossWorkspaceRead", {"projection": projection})
        if any(word in lowered for word in ("产物", "结果详情")):
            view = self.api.read("BOSS", query)
            artifacts = [(run["run_id"], ref) for run in view["runs"] for ref in run["artifacts"]]
            matches = [(run_id, ref) for run_id, ref in artifacts if ref["id"].casefold() in lowered]
            if not matches and len(artifacts) == 1:
                matches = artifacts
            if len(matches) == 1:
                run_id, reference = matches[0]
                parameters = {"run_id": run_id, "kind": reference["kind"], "id": reference["id"]}
                actual = self.api.artifact("BOSS", {**query, **parameters})
                check = (encode(parameters), artifact_digest(actual))
                if check not in checks:
                    checks.append(check)
                add("conversationRead", {"projection": "artifact", **parameters})
            else:
                required.append("请明确当前会话中已经生成的产物编号；没有正式产物时不创建引用")
        if not calls and not required:
            required.append("请明确需要读取的当前事项、来源、消息、运行或附件；其他业务动作需要相应正式输入")
        require(len(calls) <= 10, "本次读取范围超过已验证轮次，请明确需要的对象", web.HTTPBadRequest)
        return ConversationPlan(tuple(calls), tuple(references), tuple(dict.fromkeys(required)), tuple(checks),
            (query_plan.binding,) if query_plan.binding is not None else (), query_plan.pending_scope)
