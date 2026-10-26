from copy import deepcopy
from dataclasses import dataclass
import json

from aiohttp import web
from jsonschema import Draft202012Validator

from business import checksum, encode, require
from boss_execution_scope import NAMESPACE as NS
from boss_conversation import ConversationAPI, SCHEMA, validate
from boss_page_api import BossPageAPI
from boss_runtime_records import ATTRIBUTE
from boss_simulation_api import _context
from boss_sector_api import CATALOGUE as SECTOR_CATALOGUE
from nanobot.agent.tools.context import current_request_context
from runtime_page_read_tools import _BossPageReadTool
from conversation_agent.queries import ConversationQueries, mentioned


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
                versions = [version for kind, key, version in context.references if kind == "task" and key == identifier]
                with self._api.store.connect() as db:
                    db.execute("BEGIN")
                    data = self.conversation.task_in_transaction(db, _context(db), identifier, versions[0] if versions else None)
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

    def plan(self, text, query, previous_references, previous_artifacts=(), last_source_id=None, *, has_media=False, pending_query_scope=None, task_entry=None):
        lowered = text.casefold()
        calls, references, required, checks = [], [], [], []
        if task_entry is not None:
            references.extend((ref["kind"], ref["id"], ref["version"]) for ref in
                [task_entry["task_reference"], *task_entry["source_references"]])
        def add(name, params):
            call = (name, encode(params))
            if call not in calls:
                calls.append(call)
        def adopt_artifact(actual, parameters):
            digest = artifact_digest(actual)
            for encoded, previous_digest in previous_artifacts:
                previous = json.loads(encoded)
                if all(previous[field] == parameters[field] for field in ("kind", "id")):
                    require(previous_digest == digest, "当前选中产物与已记录版本或摘要不符", web.HTTPConflict)
            check = (encode(parameters), digest)
            if check not in checks:
                checks.append(check)
        if any(word in lowered for word in ("不要", "不用", "不需要", "别执行")):
            return ConversationPlan((), tuple(references), ("请明确当前需要执行的读取动作",), tuple(checks))
        sector = next((page for page, design in SECTOR_CATALOGUE.items()
                       if len(str(design.get("title") or "")) >= 4 and str(design["title"]).casefold() in lowered), None)
        if sector is not None:
            parameters = {"page": sector}
            with self.store.connect() as db:
                row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?",
                                 (NS, "sector-" + sector.lower() + "-a")).fetchone()
            if row is not None:
                options = (json.loads(row[0]).get("sector_facts") or {}).get("filter_options") or {}
                filters = {}
                for name, values in options.items():
                    for value in values:
                        label = value.get("label") if isinstance(value, dict) else value
                        if label and str(label).casefold() in lowered:
                            filters[name] = str(label)
                            break
                if filters:
                    parameters["filters"] = filters
            add("bossSectorRead", parameters)
        query_plan = ConversationQueries(self.store, self.api).plan(text, query, pending_query_scope)
        if query_plan.binding is not None:
            add("query_metrics", json.loads(query_plan.binding.parameters_json))
            references.extend(ref for ref in query_plan.references if ref not in references)
            if query_plan.parent is not None:
                parent = query_plan.parent
                adopt_artifact(parent, {key: parent[key] for key in ("run_id", "kind", "id")})
        required.extend(query_plan.required_inputs)
        if any(word in lowered for word in ("发送", "发信", "保存草稿", "拟消息", "写消息")):
            add("conversationRead", {"projection": "messages"})
            required.append("消息写入请采用当前本人消息编辑入口中的正式草稿、收件人、内容版本及有效授权")
        with self.store.connect() as db:
            initial = self.store.get(db, NS, "initial", "snapshot")
            documents = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND json_extract(body,'$.access_scope')=? AND json_extract(body,'$.source_type')='SIMULATED'", (NS, initial["owner_id"]))]
        selected = [document for document in documents if mentioned(text, document["source_id"])
                    or document.get("title") and document["title"].casefold() in lowered]
        selected_source_ids = []
        if not selected and any(word in lowered for word in ("继续", "这份", "该资料", "它的来源")):
            if last_source_id and any(word in lowered for word in ("资料", "原文", "来源", "版本")):
                remembered = [ref for ref in previous_references if ref[0] == "document" and ref[1] == last_source_id]
                require(bool(remembered), "此前选择的资料缺少已记录版本，请明确来源编号", web.HTTPConflict)
                if remembered[-1] not in references:
                    references.append(remembered[-1])
                selected_source_ids.append(last_source_id)
                add("bossEvidenceRead", {"source": last_source_id})
        for document in selected:
            add("bossEvidenceRead", {"source": document["source_id"]})
            selected_source_ids.append(document["source_id"])
            reference = ("document", document["source_id"], document["version"])
            if reference not in references:
                references.append(reference)
        if any(word in lowered for word in ("资料", "原文", "来源")) and not selected_source_ids and not any(word in lowered for word in ("附件", "文件")):
            required.append("请明确当前来源ID或已有正式来源名称")
        if any(word in lowered for word in ("任务", "交办", "承诺")) or task_entry is not None and any(
                word in lowered for word in ("当前事项", "这个事项", "该事项", "本次事项", "当前对象", "这个对象")):
            if task_entry is not None:
                selected = task_entry["task_reference"]
                with self.store.connect() as db:
                    context = _context(db)
                    identifiers = [row[0] for row in db.execute("SELECT id FROM objects WHERE namespace=? AND kind='task'", (context["namespace"],))]
                require(all(identifier == selected["id"] for identifier in identifiers if mentioned(text, identifier)),
                        "当前任务输入与本会话固定选择不符", web.HTTPConflict)
                add("conversationRead", {"projection": "record", "kind": "task", "id": selected["id"]})
            else:
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
            matches = [(kind, item[field]) for kind, items, field in (("message_draft", history["drafts"], "draft_id"),
                       ("message", history["sent_messages"], "message_id")) for item in items
                       if item.get(field) and item[field].casefold() in lowered]
            if len(matches) == 1:
                kind, identifier = matches[0]
                add("conversationRead", {"projection": "record", "kind": kind, "id": identifier})
                field = "draft_id" if kind == "message_draft" else "message_id"
                items = [item for item in history["drafts"] if item.get(field) == identifier] if kind == "message_draft" else [
                    item for item in history["sent_messages"] if item.get(field) == identifier]
            else:
                add("conversationRead", {"projection": "messages"})
                items = history["drafts"] + history["sent_messages"]
            for item in items:
                for source in item["attachment_refs"]:
                    reference = ("document", source["source_id"], source["version"])
                    if source["status"] == "VALID" and reference not in references:
                        references.append(reference)
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
            artifacts = list({(ref["kind"], ref["id"]): (run["run_id"], ref)
                for run in view["runs"] for ref in run["artifacts"]}.values())
            matches = [(run_id, ref) for run_id, ref in artifacts if ref["id"].casefold() in lowered]
            if not matches and len(artifacts) == 1:
                matches = artifacts
            if len(matches) == 1:
                run_id, reference = matches[0]
                parameters = {"run_id": run_id, "kind": reference["kind"], "id": reference["id"]}
                actual = self.api.artifact("BOSS", {**query, **parameters})
                adopt_artifact(actual, parameters)
                add("conversationRead", {"projection": "artifact", **parameters})
            else:
                required.append("请明确当前会话中已经生成的产物编号；没有正式产物时不创建引用")
        if not calls and not required:
            required.append("请明确需要读取的当前事项、来源、消息、运行或附件；其他业务动作需要相应正式输入")
        require(len(calls) <= 10, "本次读取范围超过已验证轮次，请明确需要的对象", web.HTTPBadRequest)
        return ConversationPlan(tuple(calls), tuple(references), tuple(dict.fromkeys(required)), tuple(checks),
            (query_plan.binding,) if query_plan.binding is not None else (), query_plan.pending_scope)
