import json
from pathlib import Path

from aiohttp import web
from jsonschema import Draft202012Validator
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key

from business import require
from boss_conversation import ConversationAPI, owner_role
from boss_conversation_attachments import ConversationAttachments

CONVERSATION_READ_ACTIONS = frozenset({
    "boss.conversation.read", "boss.conversation.artifact", "boss.conversation.messages", "boss.conversation.attachments",
})
REQUESTS_SCHEMA=json.loads((Path(__file__).resolve().parents[1]/"specs/conversation-requests.schema.json").read_text())


def validate_request_result(result, *, history=False):
    Draft202012Validator({**REQUESTS_SCHEMA,"$ref":"#/$defs/History" if history else "#/$defs/Receipt"}).validate(result)
    return result


class PublicConversation:
    def __init__(self, store, sessions, media_root):
        require(sessions is not None, "原生会话服务尚未就绪", web.HTTPServiceUnavailable)
        self.api = ConversationAPI(store)
        self.attachments = ConversationAttachments(sessions, media_root)

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
