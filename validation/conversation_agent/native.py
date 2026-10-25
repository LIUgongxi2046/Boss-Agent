from dataclasses import dataclass
import json
from uuid import uuid4

from aiohttp import web
from nanobot.agent.tools.context import current_request_context
from nanobot.command.builtin import builtin_command_starts_agent_turn
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key
from nanobot.webui.transcript import normalize_webui_turn_id

from business import checksum, encode, now, require
from boss_page_api import BossPageAPI
from boss_runtime_records import ATTRIBUTE
from boss_simulation_api import _context
from boss_source_access import require_current_business_source
from runtime_page_read_tools import BossDashboardReadTool, BossEvidenceReadTool, BossMeetingsReadTool
from runtime_sop_read_tools import BossTasksReadTool, BossWorkspaceReadTool
from conversation_agent import CONVERSATION_REQUEST, CONVERSATION_TOOLS, READ_TOOLS, ConversationContext, ConversationScope, ConversationReadTool
from conversation_agent.domain import ConversationPlanner, ConversationDomainReadTool, artifact_digest
from conversation_agent.runtime import ConversationRuntimeRecorder, ConversationSimulatedProvider
from conversation_agent.queries import ConversationQueryTool
from conversation_agent.presentation import render_conversation
from conversation_agent.business import BUSINESS_READ, BUSINESS_TOOLS, BusinessOverviewReadTool, entry_pin, plan_business
from fc02_agent import Fc02Context, Fc02Tool


@dataclass(frozen=True)
class ConversationGrant:
    key: str
    chat_id: str
    turn_id: str
    text_sha256: str
    active: object
    plan: object
    attachment_refs: tuple
    owner_id: str
    dataset_id: str
    dataset_version: str
    task_entry_json: str | None = None
    business_entry_json: str | None = None


class NativeConversationAgent:
    def __init__(self, store, registry, runtime_snapshot, attachments):
        self.store, self.registry, self.attachments = store, registry, attachments
        self.proofs = {}
        self.pending_media = {}
        self.planner = ConversationPlanner(store)
        self.task_entry = self.planner.api.task_entry(attachments.sessions)
        self.business_entry = self.planner.api.business_entry(attachments.sessions)
        self.scope = ConversationScope(store, self.context_provider, self.validate_context)
        api = BossPageAPI(store)
        self.delegates = [BossDashboardReadTool(api, "BOSS"), BossTasksReadTool(api, "BOSS"),
            BossMeetingsReadTool(api, "BOSS"), BossEvidenceReadTool(api, "BOSS"),
            BossWorkspaceReadTool(api, "BOSS", allowed_projections=["notifications", "travel", "calendar", "research"]),
            ConversationDomainReadTool(api, self.scope, attachments)]
        self.delegates.append(BusinessOverviewReadTool(store, self.scope, self.business_entry))
        self.provider = ConversationSimulatedProvider(self.events, self.scope)
        self.recorder = ConversationRuntimeRecorder(self.scope, registry, runtime_snapshot, intent_adapter=self)

    @staticmethod
    def handles(request):
        return request is not None and isinstance(request.attributes.get(CONVERSATION_REQUEST), ConversationGrant)

    @staticmethod
    def turn_key(chat_id, turn_id):
        require(is_valid_webui_chat_id(chat_id) and isinstance(turn_id, str) and normalize_webui_turn_id(turn_id) == turn_id,
                "会话或原生轮次编号无效", web.HTTPBadRequest)
        return "conversation-" + checksum({"chat_id": chat_id, "turn_id": turn_id})

    @staticmethod
    def _authorize(role, active):
        require(role == "BOSS" and callable(active) and active(), "一般会话需要当前本人认证", web.HTTPUnauthorized)

    def _identity(self, db):
        self.store.active(db, "ui-check")
        return _context(db)

    @staticmethod
    def _owner(row, identity):
        require(all(row[key] == identity[key] for key in ("owner_id", "dataset_id", "dataset_version")),
                "会话原意图不属于当前本人资料范围", web.HTTPForbidden)

    def morning_claimed(self, chat_id):
        if self.business_claimed(chat_id):
            return False
        with self.store.connect() as db:
            return db.execute("SELECT 1 FROM objects WHERE namespace='ui-check' AND kind='morning_native_binding' AND json_extract(body,'$.chat_id')=?", (chat_id,)).fetchone() is not None

    def tools(self):
        return [ConversationReadTool(delegate, self.scope) for delegate in self.delegates if delegate.name in READ_TOOLS] + [
            ConversationQueryTool(Fc02Tool(self.store, self.query_context, "query_metrics"), self.scope)]

    def business_tools(self):
        return [ConversationReadTool(delegate, self.scope) for delegate in self.delegates if delegate.name == BUSINESS_READ]

    def business_claimed(self, chat_id):
        with self.store.connect() as db:
            return db.execute("SELECT 1 FROM objects WHERE kind='conversation_business_binding' AND json_extract(body,'$.chat_id')=?", (chat_id,)).fetchone() is not None

    def business_admission(self, role, chat_id, *, attached, active):
        self._authorize(role, active)
        require(callable(attached) and attached(chat_id), "当前连接未采用该经营会话", web.HTTPForbidden)
        view = self.business_entry.read(role, {"session_id": webui_session_key(chat_id), "chat_id": chat_id})
        pin = entry_pin(view)
        require(pin is not None or not self.business_claimed(chat_id), "经营绑定不属于当前资料范围", web.HTTPForbidden)
        self._authorize(role, active)
        require(attached(chat_id), "经营入口检查期间连接已经变化", web.HTTPForbidden)
        return pin is not None

    def admit_business(self, role, chat_id, turn_id, content, *, media_sha256, attached, active, selection_current=None):
        if isinstance(content, str) and not builtin_command_starts_agent_turn(content):
            return None
        if not self.business_claimed(chat_id):
            return None
        return self.admit(role, chat_id, turn_id, content, media_sha256=media_sha256, attached=attached, active=active,
            selection_current=selection_current)

    def admit(self, role, chat_id, turn_id, content, *, media_sha256, attached, active, selection_current=None):
        if isinstance(content, str) and not builtin_command_starts_agent_turn(content):
            return None
        if self.business_claimed(chat_id):
            require(self.business_admission(role, chat_id, attached=attached, active=active), "经营会话缺少当前入口证明", web.HTTPForbidden)
            require(callable(selection_current), "经营会话缺少当前已应用选择的服务端证明", web.HTTPForbidden)
            current = self.business_entry.read("BOSS", {"session_id": webui_session_key(chat_id), "chat_id": chat_id})["entry"]
            selected = (current["preparation_id"], current["preparation_sha256"])
            require(selection_current() == selected, "当前页面选择与原始经营绑定不符", web.HTTPConflict)
            authenticated = active
            active = lambda: bool(authenticated() and selection_current() == selected)
        if self.morning_claimed(chat_id):
            return None
        self._authorize(role, active)
        require(callable(attached) and attached(chat_id), "当前连接未采用该会话", web.HTTPForbidden)
        key = self.turn_key(chat_id, turn_id)
        require(isinstance(content, str) and len(content.encode("utf-8")) <= 65536,
                "当前会话文字超过实际限制", web.HTTPBadRequest)
        require(isinstance(media_sha256, str) and len(media_sha256) == 64
                and all(value in "0123456789abcdef" for value in media_sha256), "实际媒体输入摘要无效", web.HTTPBadRequest)
        require(bool(content.strip()) or media_sha256 != checksum([]), "当前会话没有文字或附件", web.HTTPBadRequest)
        digest = checksum({"text": content, "media_sha256": media_sha256})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            identity = self._identity(db)
            found = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='conversation_intent' AND id=?", (key,)).fetchone()
            if found:
                row = json.loads(found[0])
                self._owner(row, identity)
                require(row["input_sha256"] == digest, "相同原生轮次携带不同文字或媒体", web.HTTPConflict)
                return {"enqueue": False, **self.receipt(role, key, active=active)}
            running = db.execute("SELECT 1 FROM objects WHERE namespace='ui-check' AND kind='conversation_intent' AND json_extract(body,'$.session_id')=? AND json_extract(body,'$.finished_at') IS NULL", (webui_session_key(chat_id),)).fetchone()
            require(running is None, "当前会话仍有未终止原意图，请读取原编号", web.HTTPConflict)
            row = {"client_request_id": key, "chat_id": chat_id, "session_id": webui_session_key(chat_id), "turn_id": turn_id,
                **{field: identity[field] for field in ("owner_id", "dataset_id", "dataset_version")},
                "input_sha256": digest, "text_sha256": checksum(content), "media_sha256": media_sha256,
                "status": "ADMITTED", "created_at": now(), "finished_at": None, "run_id": None}
            self.store.put(db, "ui-check", "conversation_intent", key, row)
        self.proofs[key] = (lambda: bool(active() and attached(chat_id)), digest)
        return {"enqueue": True, **self.receipt(role, key, active=active)}

    def receipt(self, role, key, *, active):
        self._authorize(role, active)
        with self.store.connect() as db:
            result = self._receipt(db, self._identity(db), key)
        self._authorize(role, active)
        return result

    def _receipt(self, db, identity, key):
        found = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='conversation_intent' AND id=?", (key,)).fetchone()
        row = json.loads(found[0]) if found else None
        if row is not None:
            self._owner(row, identity)
        run = self.store.get(db, "ui-check", "runtime_run", row["run_id"]) if row and row["run_id"] else None
        return {"source_type": "RUNTIME_RECORD", "client_request_id": key,
            "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "request_state": run["status"] if run else row["status"] if row else "UNKNOWN",
            "run_id": row["run_id"] if row else None, "chat_id": row["chat_id"] if row else None,
            "session_id": row["session_id"] if row else None, "turn_id": row["turn_id"] if row else None,
            "write_performed_by_lookup": False, "business_authority_granted": False}

    def requests(self, role, chat_id, *, attached, active):
        self._authorize(role, active)
        require(isinstance(chat_id, str) and is_valid_webui_chat_id(chat_id), "原请求读取会话编号无效", web.HTTPBadRequest)
        require(callable(attached) and attached(chat_id), "当前连接未采用该会话", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            identity = self._identity(db)
            identifiers = db.execute("SELECT id FROM objects WHERE namespace='ui-check' AND kind='conversation_intent' "
                "AND json_extract(body,'$.chat_id')=? ORDER BY json_extract(body,'$.created_at'),id", (chat_id,)).fetchall()
            results = [self._receipt(db, identity, identifier) for identifier, in identifiers]
            for result in results:
                require(result["outcome"] == "RECORDED" and result["chat_id"] == chat_id
                    and result["session_id"] == webui_session_key(chat_id)
                    and result["client_request_id"] == self.turn_key(chat_id, result["turn_id"]),
                    "原请求记录不属于当前规范会话及轮次", web.HTTPForbidden)
        self._authorize(role, active)
        require(attached(chat_id), "原请求读取期间连接已停止采用该会话", web.HTTPForbidden)
        with self.store.connect() as db:
            current = self._identity(db)
        require(all(current[field] == identity[field] for field in ("namespace", "owner_id", "dataset_id", "dataset_version")),
                "原请求读取期间本人资料范围已经变化", web.HTTPForbidden)
        return results

    @staticmethod
    def _media_refs(view):
        return tuple(sorted({(item["attachment_id"], item["content_sha256"], item["processing_state"])
                             for item in view["attachments"]}))

    def task_entry_pin(self, query):
        current = self.task_entry.read("BOSS", query)
        if current["binding_state"] == "UNBOUND":
            require(current["current_use_verified"] is False and current["entry"] is None,
                    "未绑定会话的任务入口状态无效", web.HTTPConflict)
            return None
        entry = current["entry"]
        require(current["binding_state"] == "BOUND" and current["current_use_verified"] is True
                and entry["binding_state"] == "BOUND" and entry["current_use_verified"] is True,
                "任务入口缺少当前有效绑定", web.HTTPConflict)
        # 使用不可变字符串保存原始选择，后续读取持续核查相同摘要。
        return encode({field: entry[field] for field in ("preparation_id", "client_request_id", "preparation_sha256",
            "task_reference", "source_references", "return_reference")})

    def record_media(self, role, key, accepted_media, accepted_paths, *, active):
        self._authorize(role, active)
        require(key in self.proofs, "实际上传缺少当前会话接收证明", web.HTTPForbidden)
        self._authorize(role, self.proofs[key][0])
        with self.store.connect() as db:
            row = self.store.get(db, "ui-check", "conversation_intent", key)
            self._owner(row, self._identity(db))
            require(row["status"] == "ADMITTED", "当前原意图已经开始运行", web.HTTPConflict)
            require(checksum(accepted_media) == row["media_sha256"], "成功上传内容与本轮原生媒体摘要不符", web.HTTPConflict)
        result = self.attachments.record_upload(role, {"session_id": row["session_id"], "chat_id": row["chat_id"]},
                                                accepted_media, accepted_paths)
        snapshot = self.attachments.sessions.read_session_snapshot(row["session_id"])
        metadata = snapshot.metadata["boss_attachment_metadata"]
        self.pending_media[key] = tuple((identifier, metadata[identifier]["content_sha256"], "STORED") for identifier in result["attachment_ids"])
        return result

    async def native_context(self, request):
        if request.channel != "websocket" or not builtin_command_starts_agent_turn(request.original_user_text or "") or self.morning_claimed(request.chat_id):
            return None
        require(request.sender_id == "boss-1" and request.session_key == webui_session_key(request.chat_id),
                "一般原生请求身份或会话不符", web.HTTPForbidden)
        key = self.turn_key(request.chat_id, request.metadata.get("webui_turn_id"))
        proof = self.proofs.get(key)
        require(proof is not None, "一般会话缺少本轮已认证接收证明", web.HTTPForbidden)
        ready = False
        try:
            self._authorize("BOSS", proof[0])
            with self.store.connect() as db:
                identity = self._identity(db)
                row = self.store.get(db, "ui-check", "conversation_intent", key)
                self._owner(row, identity)
                require(row["status"] == "ADMITTED" and row["text_sha256"] == checksum(request.original_user_text)
                        and row["input_sha256"] == proof[1], "会话输入或原编号已变化", web.HTTPConflict)
                previous = [json.loads(item[0]) for item in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='conversation_intent' AND json_extract(body,'$.session_id')=? AND id<>? ORDER BY json_extract(body,'$.created_at')", (request.session_key, key))]
            artifacts, last_source_id, last_source_ref, pending_query_scope = [], None, None, None
            for old in previous:
                self._owner(old, identity)
                if "last_source_ref" in old:
                    last_source_ref = tuple(old["last_source_ref"]) if old["last_source_ref"] is not None else None
                elif old["run_id"] is not None:
                    with self.store.connect() as db:
                        recorded = self.store.get(db, "ui-check", "runtime_run", old["run_id"])
                    selected = [step for step in recorded["tool_results"] if step["tool_id"] == "bossEvidenceRead"
                        and step.get("source_id") == old.get("last_source_id")]
                    if selected:
                        last_source_ref = ("document", selected[-1]["source_id"], selected[-1]["version"])
                for check in old.get("artifact_checks", []):
                    if tuple(check) not in artifacts:
                        artifacts.append(tuple(check))
                if old.get("last_source_id"):
                    last_source_id = old["last_source_id"]
                    if last_source_ref is not None and last_source_ref[1] != last_source_id:
                        last_source_ref = None
                pending_query_scope = old.get("pending_query_scope")
            query = {"session_id": request.session_key, "chat_id": request.chat_id}
            business_view = self.business_entry.read("BOSS", query)
            business_entry_json = entry_pin(business_view)
            for old in previous:
                if "business_entry" in old:
                    require((encode(old["business_entry"]) if old["business_entry"] is not None else None) == business_entry_json,
                            "本会话经营入口与原始固定选择不符", web.HTTPConflict)
            task_entry_json = self.task_entry_pin(query)
            require(business_entry_json is None or task_entry_json is None, "会话存在其他入口绑定", web.HTTPConflict)
            for old in previous:
                if "task_entry" in old:
                    require((encode(old["task_entry"]) if old["task_entry"] is not None else None) == task_entry_json,
                            "本会话任务入口与原固定选择不符", web.HTTPConflict)
            task_entry = json.loads(task_entry_json) if task_entry_json is not None else None
            media = self._media_refs(self.attachments.read("BOSS", query))
            require(all(state == "STORED" for _, _, state in media), "当前附件已变化或无法读取，请核查原附件", web.HTTPConflict)
            require(row["media_sha256"] == checksum([]) or key in self.pending_media,
                    "本轮媒体尚无原生成功上传的正式元信息", web.HTTPConflict)
            media = tuple(sorted(set(media) | set(self.pending_media.get(key, ()))))
            if business_entry_json is not None:
                plan = plan_business(self.store, self.planner.api, request.original_user_text, query, business_view, pending_query_scope)
                for parameters, digest in plan.artifact_checks:
                    selected = json.loads(parameters)
                    for old_parameters, old_digest in artifacts:
                        old = json.loads(old_parameters)
                        if all(old[field] == selected[field] for field in ("kind", "id")):
                            require(old_digest == digest, "经营追问产物与原始摘要不符", web.HTTPConflict)
            else:
                plan = self.planner.plan(request.original_user_text, query, (last_source_ref,) if last_source_ref else (), tuple(artifacts), last_source_id,
                    has_media=bool(self.pending_media.get(key)), pending_query_scope=pending_query_scope, task_entry=task_entry)
            self.validate_artifacts(plan, query)
            grant = ConversationGrant(key, request.chat_id, row["turn_id"], row["text_sha256"], proof[0], plan, media,
                row["owner_id"], row["dataset_id"], row["dataset_version"], task_entry_json, business_entry_json)
            require(CONVERSATION_REQUEST not in request.attributes, "请求已经包含会话采用上下文", web.HTTPForbidden)
            request.attributes[CONVERSATION_REQUEST] = grant
            self.scope.current(request, require_runtime=False)
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self.store.get(db, "ui-check", "conversation_intent", key)
                current_sources = [json.loads(parameters)["source"] for name, parameters in plan.calls if name == "bossEvidenceRead"]
                if current_sources:
                    last_source_ref = next(ref for ref in reversed(plan.references) if ref[0] == "document" and ref[1] == current_sources[-1])
                row.update(references=plan.references, attachment_refs=media, artifact_checks=plan.artifact_checks,
                           pending_query_scope=plan.pending_query_scope, task_entry=task_entry,
                           business_entry=json.loads(business_entry_json) if business_entry_json is not None else None,
                           last_source_id=current_sources[-1] if current_sources else last_source_id,
                           last_source_ref=last_source_ref,
                           plan_sha256=checksum({"calls": plan.calls, "required_inputs": plan.required_inputs}))
                self.store.put(db, "ui-check", "conversation_intent", key, row)
            ready = True
        finally:
            if not ready:
                self.finish(key)
        return None

    def context_provider(self, request):
        grant = request.attributes.get(CONVERSATION_REQUEST)
        require(isinstance(grant, ConversationGrant), "一般会话缺少可信本次输入", web.HTTPForbidden)
        require(grant.chat_id == request.chat_id and grant.turn_id == request.metadata.get("webui_turn_id")
                and grant.key == self.turn_key(request.chat_id, grant.turn_id), "会话采用上下文不属于本轮输入", web.HTTPForbidden)
        require(self.task_entry_pin({"session_id": request.session_key, "chat_id": request.chat_id}) == grant.task_entry_json,
                "任务入口与本轮固定准备摘要不符", web.HTTPConflict)
        require(entry_pin(self.business_entry.read("BOSS", {"session_id": request.session_key, "chat_id": request.chat_id})) == grant.business_entry_json,
                "经营入口与本轮原始选择不符", web.HTTPConflict)
        binding = request.attributes.get(ATTRIBUTE)
        return ConversationContext("BOSS", grant.owner_id, "ui-check", grant.dataset_id, grant.dataset_version,
            binding.request_id if binding else request.message_id or request.turn_id, request.session_key,
            request.chat_id, request.turn_id, bool(grant.key in self.proofs and grant.active()), grant.text_sha256,
            BUSINESS_TOOLS if grant.business_entry_json is not None else CONVERSATION_TOOLS,
            frozenset((name, checksum(json.loads(params))) for name, params in grant.plan.calls), grant.plan.references)

    def validate_context(self, context):
        with self.store.connect() as db:
            for kind, identifier, version in context.references:
                if kind == "task":
                    self.planner.api.task_in_transaction(db, _context(db), identifier, version)
                else:
                    require(kind == "document", "会话历史包含未验证来源种类", web.HTTPForbidden)
                    document = require_current_business_source(self.store, db, "ui-check", context.owner_id, identifier)
                    require(document["version"] == version, "会话历史来源版本已经变化", web.HTTPConflict)
        request = current_request_context()
        if request is not None and self.handles(request) and ATTRIBUTE in request.attributes:
            grant = request.attributes[CONVERSATION_REQUEST]
            media = self.attachments.read("BOSS", {"session_id": context.session_id, "chat_id": context.chat_id})
            require(self._media_refs(media) == grant.attachment_refs, "本轮实际媒体元信息已变化", web.HTTPConflict)
            require(all(item["processing_state"] == "STORED" for item in media["attachments"]), "当前附件版本不可继续采用", web.HTTPConflict)
            self.validate_artifacts(grant.plan, {"session_id": context.session_id, "chat_id": context.chat_id})
            binding = request.attributes[ATTRIBUTE]
            with self.store.connect() as db:
                run = self.store.get(db, "ui-check", "runtime_run", binding.run_id)
            for step in run["tool_results"]:
                if step["tool_id"] == "query_metrics":
                    actual = self.planner.api.artifact("BOSS", {"session_id": context.session_id, "chat_id": context.chat_id,
                        "run_id": binding.run_id, "kind": "query", "id": step["query_id"]})
                    require(checksum(actual["data"]) == step["result_sha256"], "当前运行查询产物已经变化", web.HTTPConflict)
        return True

    def validate_artifacts(self, plan, query):
        for parameters, digest in plan.artifact_checks:
            actual = self.planner.api.artifact("BOSS", {**query, **json.loads(parameters)})
            require(artifact_digest(actual) == digest, "会话历史产物或来源已经变化", web.HTTPConflict)

    async def scope_context(self, request):
        if self.handles(request):
            configured = getattr(self.registry, "configured_tool_names", self.registry.tool_names)
            tools = BUSINESS_TOOLS if request.attributes[CONVERSATION_REQUEST].business_entry_json is not None else CONVERSATION_TOOLS
            require(tools <= set(configured), "当前配置未启用本次正式会话工具", web.HTTPConflict)
            require(self.recorder.runtime_snapshot()["max_tool_rounds"] >= len(request.attributes[CONVERSATION_REQUEST].plan.calls) + 1,
                    "当前实际轮次配置不足以执行本次正式读取", web.HTTPConflict)
            request.attributes["product_feature_tool_scope"] = tools

    def query_context(self):
        request = current_request_context()
        context = self.scope.current(request)
        grant = request.attributes[CONVERSATION_REQUEST]
        return Fc02Context(context.role, context.owner_id, context.namespace, context.dataset_id, context.dataset_version,
            context.request_id, context.session_id, context.active, grant.plan.query_bindings, frozenset())

    async def events(self, messages, tools):
        request = current_request_context()
        self.scope.current(request)
        grant = request.attributes[CONVERSATION_REQUEST]
        start = max(index for index, item in enumerate(messages) if item["role"] == "user")
        outputs = [json.loads(item["content"]) for item in messages[start + 1:] if item["role"] == "tool"]
        require(len(outputs) <= len(grant.plan.calls), "实际会话工具步骤超出本次规划", web.HTTPConflict)
        if len(outputs) < len(grant.plan.calls):
            name, params = grant.plan.calls[len(outputs)]
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=name, arguments=json.loads(params))], usage=None)
        return LLMResponse(content=render_conversation(grant.plan.calls, outputs, grant.plan.required_inputs), usage=None)

    def runtime_reference(self, request):
        grant = request.attributes[CONVERSATION_REQUEST]
        with self.store.connect() as db:
            row = self.store.get(db, "ui-check", "conversation_intent", grant.key)
        result = {"client_request_id": grant.key, "media_sha256": row["media_sha256"],
                "attachment_refs": [{"attachment_id": key, "content_sha256": digest, "processing_state": state}
                                    for key, digest, state in grant.attachment_refs],
                "required_input_count": len(grant.plan.required_inputs)}
        if grant.task_entry_json is not None:
            result["task_entry"] = json.loads(grant.task_entry_json)
        if grant.business_entry_json is not None:
            result["business_entry"] = json.loads(grant.business_entry_json)
        return result

    def bind_runtime(self, request, binding):
        grant = request.attributes[CONVERSATION_REQUEST]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.store.get(db, "ui-check", "conversation_intent", grant.key)
            require(row["run_id"] in {None, binding.run_id}, "原意图已经关联其他运行", web.HTTPConflict)
            if row["run_id"] == binding.run_id:
                return
            require(row["status"] == "ADMITTED" and row["finished_at"] is None, "原意图已经终止，禁止重新进入Runtime", web.HTTPConflict)
            row.update(run_id=binding.run_id, runtime_request_id=binding.request_id, status="RUNNING")
            self.store.put(db, "ui-check", "conversation_intent", grant.key, row)

    def guard_context(self, provider):
        async def guarded(request):
            ready = False
            try:
                result = await provider(request)
                ready = True
                return result
            finally:
                if not ready and self.handles(request):
                    self.finish(request.attributes[CONVERSATION_REQUEST].key)
        return guarded

    def finish(self, key, *, status="FAILED"):
        require(status in {"FAILED", "CANCELED"}, "原生接收终止状态无效", web.HTTPBadRequest)
        self.proofs.pop(key, None)
        self.pending_media.pop(key, None)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.store.get(db, "ui-check", "conversation_intent", key)
            run = self.store.get(db, "ui-check", "runtime_run", row["run_id"]) if row["run_id"] else None
            if run and run["status"] == "QUEUED" and run["finished_at"] is None:
                run.update(status=status, stop_reason="context_preparation_failed", finished_at=now())
                self.store.put(db, "ui-check", "runtime_run", run["run_id"], run)
            row.update(status=run["status"] if run else status, finished_at=run["finished_at"] if run else now())
            self.store.put(db, "ui-check", "conversation_intent", key, row)
