import json
from pathlib import Path

from aiohttp import web
from jsonschema import Draft202012Validator
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key

from business import require
from boss_conversation import ConversationAPI, owner_role, validate
from boss_conversation_attachments import ConversationAttachments
from boss_business_overview_entry import validate as validate_business_entry
from boss_conversation_sources import ConversationSources, validate as validate_sources

CONVERSATION_READ_ACTIONS = frozenset({
    "boss.conversation.read", "boss.conversation.artifact", "boss.conversation.messages", "boss.conversation.attachments",
})
CONVERSATION_TASK_ACTIONS = frozenset({
    "boss.conversation.task.prepare", "boss.conversation.task.bind", "boss.conversation.task.read", "boss.conversation.task.receipt",
})
CONVERSATION_BUSINESS_ACTIONS = frozenset({
    "boss.conversation.business.prepare", "boss.conversation.business.bind", "boss.conversation.business.read", "boss.conversation.business.receipt", "boss.conversation.business.clear",
})
CONVERSATION_SOURCE_ACTIONS = frozenset({"boss.conversation.sources.list", "boss.conversation.sources.bind", "boss.conversation.sources.receipt"})
REQUESTS_SCHEMA=json.loads((Path(__file__).resolve().parents[1]/"specs/conversation-requests.schema.json").read_text())


def validate_request_result(result, *, history=False):
    Draft202012Validator({**REQUESTS_SCHEMA,"$ref":"#/$defs/History" if history else "#/$defs/Receipt"}).validate(result)
    return result


class PublicConversation:
    def __init__(self, store, sessions, media_root, *, workspaces=None):
        require(sessions is not None, "原生会话服务尚未就绪", web.HTTPServiceUnavailable)
        self.api = ConversationAPI(store)
        self.attachments = ConversationAttachments(sessions, media_root)
        self.task_entry = self.api.task_entry(sessions)
        self.business_entry = self.api.business_entry(sessions)
        self.source_selection = ConversationSources(store, sessions)
        self.sessions, self.workspaces = sessions, workspaces

    def sources(self, role, action, payload, *, attached, active):
        owner_role(role)
        require(active(), "当前本人认证已经失效", web.HTTPUnauthorized)
        require(action in CONVERSATION_SOURCE_ACTIONS, "会话资料动作无效", web.HTTPBadRequest)
        operation, schema = {"boss.conversation.sources.list": (self.source_selection.listing, "ListInput"),
            "boss.conversation.sources.bind": (self.source_selection.bind, "BindInput"),
            "boss.conversation.sources.receipt": (self.source_selection.receipt, "ReceiptInput")}[action]
        validate_sources(schema, payload)
        chat_id = payload["chat_id"]
        require(is_valid_webui_chat_id(chat_id) and attached(chat_id), "当前连接未订阅所选资料会话", web.HTTPForbidden)
        if action == "boss.conversation.sources.bind":
            session_id = webui_session_key(chat_id)
            if self.sessions.read_session_snapshot(session_id) is None:
                require(self.workspaces is not None, "原生工作空间服务尚未就绪", web.HTTPServiceUnavailable)
                require(active() and attached(chat_id), "保存资料选择期间身份或会话已经变化", web.HTTPForbidden)
                self.workspaces.persist_scope(chat_id, self.workspaces.scope_for_session_key(session_id))
            result = operation(role, payload, active=lambda: active() and attached(chat_id))
        else:
            result = operation(role, payload)
        require(active() and attached(chat_id), "处理资料选择期间身份或会话已经变化", web.HTTPForbidden)
        return result

    def task(self, role, action, payload, *, attached, active):
        owner_role(role)
        require(active(), "当前本人认证已经失效", web.HTTPUnauthorized)
        require(action in CONVERSATION_TASK_ACTIONS and isinstance(payload, dict), "任务会话动作或字段无效", web.HTTPBadRequest)
        chat_id = None
        if action == "boss.conversation.task.prepare":
            result = self.task_entry.prepare(role, payload)
        elif action == "boss.conversation.task.receipt":
            result = self.task_entry.receipt(role, payload)
        else:
            if action == "boss.conversation.task.bind":
                validate("TaskEntryBind", payload)
            else:
                require(set(payload) == {"chat_id"}, "任务会话读取字段无效", web.HTTPBadRequest)
            chat_id = payload.get("chat_id")
            require(is_valid_webui_chat_id(chat_id) and attached(chat_id), "当前连接尚未订阅所选任务会话", web.HTTPForbidden)
            session_id = webui_session_key(chat_id)
            if action == "boss.conversation.task.bind":
                receipt = self.task_entry.receipt(role, {"client_request_id": payload["client_request_id"]})
                entry = receipt["entry"]
                require(entry is not None, "当前原请求没有任务会话准备记录", web.HTTPNotFound)
                require(entry["preparation_id"] == payload["preparation_id"] and entry["preparation_sha256"] == payload["preparation_sha256"],
                        "本次绑定与原任务会话准备不符", web.HTTPConflict)
                self.task_entry.prepare(role, {"client_request_id": payload["client_request_id"],
                    "task_id": entry["task_reference"]["id"], "task_version": entry["task_reference"]["version"]})
                if self.sessions.read_session_snapshot(session_id) is None:
                    require(self.workspaces is not None, "原生工作空间服务尚未就绪", web.HTTPServiceUnavailable)
                    require(active() and attached(chat_id), "准备任务会话期间身份或附着已经变化", web.HTTPForbidden)
                    self.workspaces.persist_scope(chat_id, self.workspaces.scope_for_session_key(session_id))
                result = self.task_entry.bind(role, payload)
            else:
                result = self.task_entry.read(role, {"session_id": session_id, "chat_id": chat_id})
        require(active() and (chat_id is None or attached(chat_id)), "任务会话处理期间身份或附着已经变化", web.HTTPForbidden)
        return result

    def business(self, role, action, payload, *, attached, active):
        owner_role(role)
        require(active(), "当前本人认证已经失效", web.HTTPUnauthorized)
        require(action in CONVERSATION_BUSINESS_ACTIONS and isinstance(payload, dict), "经营会话动作或字段无效", web.HTTPBadRequest)
        chat_id = None
        if action == "boss.conversation.business.clear":
            require(not payload, "清理当前经营选择不接受额外字段", web.HTTPBadRequest)
            result = {"source_type": "RUNTIME_RECORD", "current_selection_cleared": True,
                      "business_authorization_granted": False, "business_mutation_performed": False}
        elif action == "boss.conversation.business.prepare":
            result = self.business_entry.prepare(role, payload)
        elif action == "boss.conversation.business.receipt":
            result = self.business_entry.receipt(role, payload)
        else:
            if action == "boss.conversation.business.bind":
                validate_business_entry("EntryBind", payload)
            else:
                require(set(payload) in ({"chat_id"}, {"chat_id", "adopt_selection"})
                        and ("adopt_selection" not in payload or type(payload["adopt_selection"]) is bool),
                        "经营会话读取字段无效", web.HTTPBadRequest)
            chat_id = payload.get("chat_id")
            require(is_valid_webui_chat_id(chat_id) and attached(chat_id), "当前连接尚未订阅所选经营会话", web.HTTPForbidden)
            session_id = webui_session_key(chat_id)
            if action == "boss.conversation.business.bind":
                original = self.business_entry.receipt(role, {"client_request_id": payload["client_request_id"]})["entry"]
                require(original is not None, "当前原请求没有经营会话准备记录", web.HTTPNotFound)
                require(original["preparation_id"] == payload["preparation_id"] and original["preparation_sha256"] == payload["preparation_sha256"], "本次绑定与原经营范围准备不符", web.HTTPConflict)
                self.business_entry.prepare(role, {field: original[field] for field in ("client_request_id", "applied_scope", "snapshot_sha256", "topic_reference")})
                if self.sessions.read_session_snapshot(session_id) is None:
                    require(self.workspaces is not None, "原生工作空间服务尚未就绪", web.HTTPServiceUnavailable)
                    require(active() and attached(chat_id), "准备经营会话期间身份或附着已经变化", web.HTTPForbidden)
                    self.workspaces.persist_scope(chat_id, self.workspaces.scope_for_session_key(session_id))
                result = self.business_entry.bind(role, payload)
            else:
                result = self.business_entry.read(role, {"session_id": session_id, "chat_id": chat_id})
        require(active() and (chat_id is None or attached(chat_id)), "经营会话处理期间身份或附着已经变化", web.HTTPForbidden)
        return result

    def record_upload(self, role, chat_id, accepted_media, accepted_paths, *, attached, active):
        owner_role(role)
        require(active(), "当前本人认证已经失效", web.HTTPUnauthorized)
        require(is_valid_webui_chat_id(chat_id) and attached(chat_id), "原生上传不属于当前已订阅会话", web.HTTPForbidden)
        result = self.attachments.record_upload(role, {"session_id": webui_session_key(chat_id), "chat_id": chat_id}, accepted_media, accepted_paths)
        require(active() and attached(chat_id), "原生上传期间当前身份或会话发生变化", web.HTTPForbidden)
        return result

    def read(self, role, action, payload, *, attached, active):
        owner_role(role)
        require(active(), "当前本人认证已经失效", web.HTTPUnauthorized)
        require(action in CONVERSATION_READ_ACTIONS and isinstance(payload, dict), "会话读取动作或字段无效", web.HTTPBadRequest)
        if action == "boss.conversation.messages":
            require(not payload, "消息历史读取不接受额外字段", web.HTTPBadRequest)
            result = self.api.messages(role)
        else:
            fields = {"chat_id", "run_id", "kind", "id"} if action == "boss.conversation.artifact" else {"chat_id"}
            require(set(payload) == fields and is_valid_webui_chat_id(payload.get("chat_id")), "当前会话读取字段无效", web.HTTPBadRequest)
            chat_id = payload["chat_id"]
            require(attached(chat_id), "当前连接尚未订阅所选会话", web.HTTPForbidden)
            context = {"session_id": webui_session_key(chat_id), "chat_id": chat_id}
            if action == "boss.conversation.artifact":
                result = self.api.artifact(role, {**context, **{key: payload[key] for key in ("run_id", "kind", "id")}})
            elif action == "boss.conversation.attachments":
                result = self.attachments.read(role, context)
            else:
                result = self.api.read(role, context)
            require(attached(chat_id), "当前连接已经离开所选会话", web.HTTPForbidden)
        require(active(), "当前本人认证已经失效", web.HTTPUnauthorized)
        return result
