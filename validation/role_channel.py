import asyncio
import hmac
import json
import os
import time
import uuid
from contextvars import ContextVar
from urllib.parse import parse_qs, unquote, urlsplit

from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.webui.http_utils import bearer_token
from nanobot.command.builtin import builtin_command_starts_agent_turn
from websockets.datastructures import Headers
from websockets.http11 import Request
from aiohttp import web

from business import checksum, now
from boss_page_api import BossPageAPI
from boss_command_api import BossCommandAPI
from public_conversation import CONVERSATION_READ_ACTIONS, CONVERSATION_TASK_ACTIONS, PublicConversation, validate_request_result


class RoleChannel(WebSocketChannel):
    def __init__(self, original, secrets, audit, business_store=None, runtime_control=None, skills=None):
        super().__init__(original.config, original.bus, gateway=original.gateway)
        self.secrets = secrets
        self.audit = audit
        self.token_roles = {}
        self.connection_roles = {}
        self.token_expirations = {}
        self.connection_expirations = {}
        self.connection_tokens = {}
        self.fc01 = None
        self.bi = None
        self.morning = None
        self.mvp = None
        self.assignment = None
        self.reminders = None
        self.native_conversation = None
        self.morning_admission = ContextVar("morning_native_admission", default=None)
        self.conversation_admission = ContextVar("conversation_native_admission", default=None)
        self.conversation_upload = ContextVar("conversation_native_upload", default=None)
        self.bi_responses = set()
        self.skills = skills
        self.boss_pages = BossPageAPI(business_store, runtime_control=runtime_control, skills=skills) if business_store is not None else None
        self.boss_commands = BossCommandAPI(business_store, runtime_control=runtime_control, skills=skills) if business_store is not None else None
        self.conversation = PublicConversation(business_store, self.gateway.session_manager, self.gateway.media._media_dir("websocket"), workspaces=self.gateway.workspaces) if business_store is not None else None

    def record(self, role, operation, status):
        with self.audit.open("a") as output:
            output.write(json.dumps({"at": now(), "role": role, "operation": operation, "status": status}, ensure_ascii=False) + "\n")

    async def _dispatch_http(self, connection, request):
        address = urlsplit(request.path)
        if address.path.startswith("/boss-brand/"):
            asset_path = unquote(address.path, errors="strict")
            frontend = self.gateway.http.static_dist_path
            if frontend is None:
                return connection.respond(503, "当前界面资源尚未就绪")
            asset = (frontend / asset_path.lstrip("/")).resolve()
            if not asset.is_relative_to(frontend / "boss-brand") or not asset.is_file():
                return connection.respond(404, "界面资源不存在")
            return self.gateway.http._serve_static(asset_path, accept_encoding=request.headers.get("Accept-Encoding", ""))
        if address.path == "/webui/bootstrap":
            supplied = bearer_token(request.headers) or request.headers.get("X-Nanobot-Auth", "")
            role = next((role for role, secret in self.secrets.items() if hmac.compare_digest(supplied, secret)), None)
            if role is None:
                self.record(None, "bootstrap", 401)
                return connection.respond(401, "未认证")
            headers = Headers(request.headers.raw_items())
            if "Authorization" in headers:
                del headers["Authorization"]
            if "X-Nanobot-Auth" in headers:
                del headers["X-Nanobot-Auth"]
            headers["X-Nanobot-Auth"] = self.secrets["BOSS"]
            response = await super()._dispatch_http(connection, Request(request.path, headers))
            if response.status_code == 200:
                payload = json.loads(response.body)
                for key in ("token", "api_token"):
                    if key in payload:
                        self.token_roles[payload[key]] = role
                        self.token_expirations[payload[key]] = time.monotonic() + payload["expires_in"]
            self.record(role, "bootstrap", response.status_code)
            return response
        query = parse_qs(address.query)
        token = bearer_token(request.headers) or query.get("token", [""])[0]
        role = self.token_roles.get(token)
        if request.headers.get("Upgrade", "").lower() == "websocket":
            if role is None:
                return connection.respond(401, "未认证")
            response = await super()._dispatch_http(connection, request)
            if response is None:
                self.connection_roles[connection] = role
                self.connection_expirations[connection] = self.token_expirations[token]
                self.connection_tokens[connection] = token
            return response
        if address.path.startswith("/api/"):
            if not self.gateway.tokens.check_api_token(request):
                self.record(None, address.path, 401)
                return connection.respond(401, "未认证")
            if address.path == "/api/boss/identity":
                if role not in ("BOSS", "MAINTAINER"):
                    self.record(role, address.path, 403)
                    return connection.respond(403, "身份权限不足")
                self.record(role, address.path, 200)
                return connection.respond(200, json.dumps({"role": role, "owner_id": "boss-1" if role == "BOSS" else None, "execution_scope": os.environ.get("BOSS_EXECUTION_SCOPE")}))
            if address.path.startswith("/api/boss/ui/"):
                if address.path == "/api/boss/ui/conversation/task-entry":
                    try:
                        if self.conversation is None:
                            raise web.HTTPServiceUnavailable(text="任务会话接收服务尚未就绪")
                        values = parse_qs(address.query, keep_blank_values=True)
                        if set(values) != {"client_request_id"} or len(values["client_request_id"]) != 1:
                            raise web.HTTPBadRequest(text="原任务会话请求字段无效")
                        body = self.conversation.task(role, "boss.conversation.task.receipt", {"client_request_id": values["client_request_id"][0]},
                            attached=lambda chat_id: False, active=lambda: self.token_roles.get(token) == "BOSS" and self.gateway.tokens.check_api_token(request))
                        status = 200
                    except web.HTTPException as failure:
                        status, body = failure.status, {"error": failure.text}
                    self.record(role, address.path, status)
                    return connection.respond(status, json.dumps(body, ensure_ascii=False))
                if address.path == "/api/boss/ui/conversation/request":
                    try:
                        if self.native_conversation is None:
                            raise web.HTTPServiceUnavailable(text="当前会话接收服务尚未就绪")
                        values = parse_qs(address.query, keep_blank_values=True)
                        if set(values) != {"client_request_id"} or len(values["client_request_id"]) != 1 or not values["client_request_id"][0] or len(values["client_request_id"][0]) > 128:
                            raise web.HTTPBadRequest(text="原会话请求编号无效")
                        body = self.native_conversation.receipt(role, values["client_request_id"][0], active=lambda: self.token_roles.get(token) == "BOSS" and self.gateway.tokens.check_api_token(request))
                        status = 200
                    except web.HTTPException as failure:
                        status, body = failure.status, {"error": failure.text}
                    self.record(role, address.path, status)
                    return connection.respond(status, json.dumps(body, ensure_ascii=False))
                if address.path == "/api/boss/ui/reminder-preparation":
                    try:
                        if self.reminders is None:
                            raise web.HTTPServiceUnavailable(text="当前提醒读取服务尚未就绪")
                        values = parse_qs(address.query, keep_blank_values=True)
                        if set(values) != {"client_request_id"} or len(values["client_request_id"]) != 1 or not values["client_request_id"][0]:
                            raise web.HTTPBadRequest(text="提醒原请求字段无效")
                        body = self.reminders.receipt(role, values["client_request_id"][0], lambda: True)
                        status = 200
                    except web.HTTPException as failure:
                        status, body = failure.status, {"error": failure.text}
                    self.record(role, address.path, status)
                    return connection.respond(status, json.dumps(body, ensure_ascii=False))
                if address.path == "/api/boss/ui/assignment-preparation":
                    try:
                        if self.assignment is None:
                            raise web.HTTPServiceUnavailable(text="当前交办读取服务尚未就绪")
                        values = parse_qs(address.query, keep_blank_values=True)
                        if set(values) != {"client_request_id"} or len(values["client_request_id"]) != 1 or not values["client_request_id"][0]:
                            raise web.HTTPBadRequest(text="交办原请求字段无效")
                        body = self.assignment.receipt(role, values["client_request_id"][0], lambda: True)
                        status = 200
                    except web.HTTPException as failure:
                        status, body = failure.status, {"error": failure.text}
                    self.record(role, address.path, status)
                    return connection.respond(status, json.dumps(body, ensure_ascii=False))
                if address.path.startswith("/api/boss/ui/mvp/"):
                    try:
                        if self.mvp is None:
                            raise web.HTTPServiceUnavailable(text="当前采购体验尚未启用")
                        body = self.mvp.serve(role, address.path, address.query)
                        status = 200
                    except web.HTTPException as failure:
                        status, body = failure.status, {"error": failure.text}
                    self.record(role, address.path, status)
                    return connection.respond(status, json.dumps(body, ensure_ascii=False))
                if address.path in {"/api/boss/ui/morning/request", "/api/boss/ui/morning/history", "/api/boss/ui/morning/binding"}:
                    try:
                        if self.morning is None:
                            raise web.HTTPServiceUnavailable(text="晨间服务尚未就绪")
                        parameters = parse_qs(address.query, keep_blank_values=True)
                        if address.path.endswith("/history"):
                            if parameters:
                                raise web.HTTPBadRequest(text="晨间历史不接受查询字段")
                            body = self.morning.history(role)
                        else:
                            if set(parameters) != {"client_request_id"} or len(parameters["client_request_id"]) != 1 or not parameters["client_request_id"][0]:
                                raise web.HTTPBadRequest(text="晨间原请求编号无效")
                            if address.path.endswith("/binding"):
                                body = self.morning.native.binding_receipt(role, parameters["client_request_id"][0],
                                    active=lambda: self.token_roles.get(token) == "BOSS" and self.gateway.tokens.check_api_token(request))
                            else:
                                body = self.morning.receipt(role, parameters["client_request_id"][0])
                        status = 200
                    except web.HTTPException as failure:
                        status, body = failure.status, {"error": failure.text}
                    self.record(role, address.path, status)
                    return connection.respond(status, json.dumps(body, ensure_ascii=False))
                if address.path.startswith("/api/boss/ui/bi/"):
                    try:
                        if self.bi is None:
                            raise web.HTTPServiceUnavailable(text="经营服务尚未就绪")
                        body = self.bi.serve(role, address.path, address.query)
                        status = 200
                    except web.HTTPException as failure:
                        status, body = failure.status, {"error":failure.text}
                    self.record(role, address.path, status)
                    return connection.respond(status, json.dumps(body, ensure_ascii=False))
                if self.boss_pages is None:
                    return connection.respond(503, json.dumps({"error": "BOSS_SERVICE_NOT_READY"}))
                status, body = self.boss_pages.serve(role, address.path, address.query)
                self.record(role, address.path, status)
                return connection.respond(status, json.dumps(body, ensure_ascii=False))
            if self.skills is not None and address.path.startswith("/api/webui/skills/"):
                self.record(role, address.path, 403)
                return connection.respond(403, "方法管理需要通过获准入口")
            allowed = role == "BOSS" or role == "MAINTAINER" and address.path in {"/api/settings", "/api/settings/usage", "/api/settings/provider-models", "/api/webui/automations", "/api/webui/skills", "/api/settings/mcp-presets"}
            if not allowed:
                self.record(role, address.path, 403)
                return connection.respond(403, "身份权限不足")
        return await super()._dispatch_http(connection, request)

    async def _dispatch_active_envelope(self, connection, client_id, envelope):
        role = self.connection_roles.get(connection)
        kind = envelope.get("type")
        action = envelope.get("action", "")
        if kind == "webui_request" and action in CONVERSATION_READ_ACTIONS | CONVERSATION_TASK_ACTIONS:
            await self._conversation_response(connection, role, envelope)
            return
        if kind == "webui_request" and action in {"boss.conversation.request", "boss.conversation.requests"}:
            await self._conversation_receipt_response(connection, role, envelope)
            return
        if kind == "webui_request" and action == "boss.reminder.prepare":
            task = asyncio.create_task(self._reminder_response(connection, role, envelope))
            self.bi_responses.add(task)
            task.add_done_callback(self.bi_responses.discard)
            return
        if kind == "webui_request" and action == "boss.assignment.prepare":
            task = asyncio.create_task(self._assignment_response(connection, role, envelope))
            self.bi_responses.add(task)
            task.add_done_callback(self.bi_responses.discard)
            return
        if kind == "webui_request" and action in {"boss.mvp.query", "boss.mvp.cancel"}:
            task = asyncio.create_task(self._mvp_response(connection, role, envelope))
            self.bi_responses.add(task)
            task.add_done_callback(self.bi_responses.discard)
            return
        if kind == "webui_request" and action in {"boss.morning.query", "boss.morning.cancel", "boss.morning.bind"}:
            task = asyncio.create_task(self._morning_response(connection, role, envelope))
            self.bi_responses.add(task)
            task.add_done_callback(self.bi_responses.discard)
            return
        if kind == "webui_request" and action in {"boss.bi.query", "boss.bi.follow_up", "boss.bi.cancel"}:
            task = asyncio.create_task(self._bi_response(connection, role, envelope))
            self.bi_responses.add(task)
            task.add_done_callback(self.bi_responses.discard)
            return
        if kind == "webui_request" and action in {"boss.fc01.prepare", "boss.fc01.coordinate", "boss.fc01.status"}:
            request_id = envelope.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                raise ValueError("当前请求缺少编号")
            def active():
                return self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
            try:
                if self.fc01 is None:
                    raise web.HTTPServiceUnavailable(text="当前FC01 Runtime尚未就绪")
                if action == "boss.fc01.prepare":
                    result = await self.fc01.prepare(role, envelope.get("payload"), active)
                elif action == "boss.fc01.status":
                    result = self.fc01.status(role, envelope.get("payload"), active)
                else:
                    result = self.fc01.coordinate(role, envelope.get("payload"), active)
                status, response = 200, {"result": result}
            except web.HTTPException as failure:
                status, response = failure.status, {"error": {"status": failure.status, "message": failure.text}}
            self.record(role, action, status)
            await connection.send(json.dumps({"event":"webui_response", "request_id":request_id, "ok":status == 200, **response}, ensure_ascii=False))
            return
        if kind == "webui_request" and action == "skill.update":
            request_id = envelope.get("request_id")
            if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                raise ValueError("方法状态请求缺少有效标识")
            try:
                if role != "MAINTAINER":
                    raise web.HTTPForbidden(text="仅技术维护身份可以修改方法")
                if self.skills is None:
                    raise web.HTTPServiceUnavailable(text="当前方法服务尚未准备")
                http = self.gateway.http
                if http.skill_state_action is None:
                    raise web.HTTPServiceUnavailable(text="当前方法采用服务尚未准备")
                result = self.skills.update(role, envelope.get("payload"))
                disabled = set(self.skills.catalog.loader.disabled_skills)
                http.disabled_skills.clear()
                http.disabled_skills.update(disabled)
                http._apply_skill_state()
                status = 200
                response = {"result": result}
            except web.HTTPException as failure:
                status = failure.status
                response = {"error": {"status": status, "message": failure.text}}
            self.record(role, action, status)
            await connection.send(json.dumps({"event": "webui_response", "request_id": request_id,
                "ok": status == 200, **response}, ensure_ascii=False))
            return
        if kind == "webui_request" and action == "boss.auth.logout":
            request_id = envelope.get("request_id")
            if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                raise ValueError("退出请求缺少有效标识")
            if role not in ("BOSS", "MAINTAINER"):
                raise PermissionError("退出请求缺少认证身份")
            # 单桌面内退出当前身份时，撤销该身份的全部本机访问令牌。
            for token, identity in list(self.token_roles.items()):
                if identity == role:
                    self.gateway.tokens.api_tokens.pop(token, None)
                    self.gateway.tokens.issued_tokens.pop(token, None)
                    self.gateway.tokens.issued_token_audiences.pop(token, None)
                    self.token_roles.pop(token, None)
            peers = [peer for peer, identity in self.connection_roles.items() if identity == role]
            for peer in peers:
                self.connection_roles.pop(peer, None)
            self.record(role, action, 200)
            await connection.send(json.dumps({"event": "webui_response", "request_id": request_id, "ok": True, "result": {"signed_out": True}}))
            for peer in peers:
                await peer.close(code=1000, reason="身份已退出")
            return
        # Boss business commands reuse the authenticated WebUI mutation protocol.
        # Scope is the WebSocket's server-authenticated role, not payload.role.
        # Each domain command creates a transactional idempotency receipt and
        # survives the upstream client's same-request reconnect/replay behavior.
        if kind == "webui_request" and isinstance(action, str) and action.startswith("boss."):
            request_id = envelope.get("request_id")
            if not isinstance(request_id, str) or len(request_id) > 128:
                return
            if self.boss_commands is None:
                status, result = 503, {"error": "BOSS_SERVICE_NOT_READY"}
            elif action in {"boss.sop.activate", "boss.sop.enable", "boss.sop.disable", "boss.sop.recover", "boss.sop.cancel"} and self.gateway.http.skill_state_action is None:
                status, result = 503, {"error": "SKILL_ADOPTION_SERVICE_NOT_READY"}
            else:
                status, result = self.boss_commands.execute(role, action, envelope.get("payload"))
                if status == 200 and action in {"boss.sop.activate", "boss.sop.enable", "boss.sop.disable", "boss.sop.recover", "boss.sop.cancel"}:
                    disabled = set(self.skills.catalog.loader.disabled_skills)
                    self.gateway.http.disabled_skills.clear()
                    self.gateway.http.disabled_skills.update(disabled)
                    self.gateway.http._apply_skill_state()
            self.record(role, action, status)
            await connection.send(json.dumps({
                "event": "webui_response", "request_id": request_id,
                "ok": status == 200,
                **({"result": result} if status == 200 else {
                    "error": {"status": status, "message": result.get("error", "BUSINESS_REJECTED")}
                })
            }, ensure_ascii=False))
            return
        permitted = role == "BOSS" and kind != "webui_request"
        permitted = permitted or role == "BOSS" and action in {"sidebar.update", "session.rename", "session.delete"}
        permitted = permitted or role == "MAINTAINER" and kind == "webui_request" and action in {"settings.runtime_config.update", "settings.model_configuration.update", "settings.provider.update", "automation.enable", "automation.disable", "automation.delete", "automation.run", "automation.update"}
        if not permitted:
            self.record(role, action or kind, 403)
            event = {"event": "webui_response", "request_id": envelope.get("request_id"), "ok": False, "error": {"status": 403, "message": "身份权限不足"}} if kind == "webui_request" else {"event": "error", "detail": "access_denied", "reason": "身份权限不足"}
            await connection.send(json.dumps(event, ensure_ascii=False))
            return
        admitted = None
        control_message = kind == "message" and isinstance(envelope.get("content"), str) and not builtin_command_starts_agent_turn(envelope["content"])
        if kind == "message" and self.morning is not None and not control_message:
            try:
                admitted = self.morning.native.admit(role, envelope.get("chat_id"), envelope.get("turn_id"), envelope.get("content"),
                    attached=lambda chat_id: chat_id in self.webui_connection_chats(connection),
                    active=lambda: self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0))
                if admitted is not None and not admitted["enqueue"]:
                    await connection.send(json.dumps({"event":"error","detail":"morning_turn_already_recorded","reason":"本轮已经接收，请读取原会话记录。","chat_id":envelope.get("chat_id"),"turn_id":envelope.get("turn_id")}))
                    return
            except web.HTTPException as failure:
                self.record(role, "boss.morning.native.message", failure.status)
                await connection.send(json.dumps({"event":"error","detail":"morning_scope_rejected","reason":failure.text,"chat_id":envelope.get("chat_id"),"turn_id":envelope.get("turn_id")}, ensure_ascii=False))
                return
        general_admitted = None
        if kind == "message" and admitted is None and self.native_conversation is not None and not control_message:
            try:
                general_admitted = self.native_conversation.admit(role, envelope.get("chat_id"), envelope.get("turn_id"), envelope.get("content"),
                    media_sha256=checksum(envelope.get("media") or []),
                    attached=lambda chat_id: chat_id in self.webui_connection_chats(connection),
                    active=lambda: self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0))
                if general_admitted is not None and not general_admitted["enqueue"]:
                    await connection.send(json.dumps({"event": "error", "detail": "conversation_turn_already_recorded", "reason": "本轮已经接收，请读取原编号记录。", "chat_id": envelope.get("chat_id"), "turn_id": envelope.get("turn_id"), "receipt": general_admitted}, ensure_ascii=False))
                    return
            except web.HTTPException as failure:
                self.record(role, "boss.conversation.native.message", failure.status)
                await connection.send(json.dumps({"event": "error", "detail": "conversation_scope_rejected", "reason": failure.text, "chat_id": envelope.get("chat_id"), "turn_id": envelope.get("turn_id")}, ensure_ascii=False))
                return
        admission = {"request": admitted, "enqueued": False} if admitted is not None else None
        general_admission = {"request": general_admitted, "enqueued": False} if general_admitted is not None else None
        admission_token = self.morning_admission.set(admission)
        general_token = self.conversation_admission.set(general_admission)
        upload_token = self.conversation_upload.set({"role": role, "connection": connection, "chat_id": envelope.get("chat_id"), "media": envelope.get("media")} if kind == "message" and envelope.get("media") else None)
        try:
            await super()._dispatch_active_envelope(connection, "boss-1" if role == "BOSS" else "maintainer-1", envelope)
        finally:
            self.morning_admission.reset(admission_token)
            self.conversation_admission.reset(general_token)
            self.conversation_upload.reset(upload_token)
            if admission is not None and not admission["enqueued"]:
                self.morning.native.finish(admitted["client_request_id"])
            if general_admission is not None and not general_admission["enqueued"]:
                self.native_conversation.finish(general_admitted["client_request_id"])

    async def webui_dispatch_message(self, *, sender_id, chat_id, content, media, metadata, is_dm, session_key, require_existing_session):
        upload = self.conversation_upload.get()
        general_admission = self.conversation_admission.get()
        if general_admission is not None:
            accepted = general_admission["request"]
            if accepted["chat_id"] != chat_id or accepted["turn_id"] != metadata.get("webui_turn_id"):
                raise web.HTTPForbidden(text="原生入队对象与一般会话证明不符")
        if media and upload is not None and session_key in (None, "websocket:" + chat_id):
            connection = upload["connection"]
            if self.conversation is None or sender_id != "boss-1" or upload["chat_id"] != chat_id:
                raise web.HTTPForbidden(text="原生附件与当前本人会话不符")
            active = lambda: self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
            if general_admission is not None:
                self.native_conversation.record_media(upload["role"], general_admission["request"]["client_request_id"], upload["media"], media, active=active)
            else:
                self.conversation.record_upload(upload["role"], chat_id, upload["media"], media,
                    attached=lambda selected: selected in self.webui_connection_chats(connection), active=active)
        await super().webui_dispatch_message(sender_id=sender_id, chat_id=chat_id, content=content, media=media,
            metadata=metadata, is_dm=is_dm, session_key=session_key, require_existing_session=require_existing_session)
        if general_admission is not None:
            general_admission["enqueued"] = True
        admission = self.morning_admission.get()
        if admission is not None:
            accepted = admission["request"]
            if accepted["chat_id"] != chat_id or accepted["turn_id"] != metadata.get("webui_turn_id"):
                raise web.HTTPForbidden(text="原生入队对象与晨间证明不符")
            admission["enqueued"] = True

    async def _conversation_receipt_response(self, connection, role, envelope):
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("原会话读取缺少有效请求编号")
        def active():
            return self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
        try:
            if self.native_conversation is None:
                raise web.HTTPServiceUnavailable(text="当前会话接收服务尚未就绪")
            payload = envelope.get("payload")
            history=envelope["action"]=="boss.conversation.requests"
            if not isinstance(payload, dict) or set(payload) != ({"chat_id"} if history else {"chat_id", "turn_id"}):
                raise web.HTTPBadRequest(text="原会话读取字段无效")
            if not isinstance(payload["chat_id"],str):
                raise web.HTTPBadRequest(text="原请求读取需要有效会话编号")
            if payload["chat_id"] not in self.webui_connection_chats(connection):
                raise web.HTTPForbidden(text="当前连接尚未订阅所选会话")
            if history:
                result=self.native_conversation.requests(role,payload["chat_id"],attached=lambda chat_id:chat_id in self.webui_connection_chats(connection),active=active)
            else:
                key = self.native_conversation.turn_key(payload["chat_id"], payload["turn_id"])
                result = self.native_conversation.receipt(role, key, active=active)
            validate_request_result(result,history=history)
            status, response = 200, {"result": result}
        except web.HTTPException as failure:
            status, response = failure.status, {"error": {"status": failure.status, "message": failure.text}}
        self.record(role, envelope["action"], status)
        if connection.close_code is None:
            await connection.send(json.dumps({"event": "webui_response", "request_id": request_id, "ok": status == 200, **response}, ensure_ascii=False))

    async def _conversation_response(self, connection, role, envelope):
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("会话读取缺少有效请求编号")
        def active():
            return self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
        try:
            if self.conversation is None:
                raise web.HTTPServiceUnavailable(text="当前会话读取服务尚未就绪")
            operation = self.conversation.task if envelope["action"] in CONVERSATION_TASK_ACTIONS else self.conversation.read
            result = operation(role, envelope["action"], envelope.get("payload"),
                attached=lambda chat_id: chat_id in self.webui_connection_chats(connection), active=active)
            status, response = 200, {"result": result}
        except web.HTTPException as failure:
            status, response = failure.status, {"error": {"status": failure.status, "message": failure.text}}
        self.record(role, envelope["action"], status)
        if connection.close_code is None:
            await connection.send(json.dumps({"event": "webui_response", "request_id": request_id, "ok": status == 200, **response}, ensure_ascii=False))

    async def _reminder_response(self, connection, role, envelope):
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("提醒读取缺少有效请求编号")
        def active():
            return self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
        try:
            if self.reminders is None:
                raise web.HTTPServiceUnavailable(text="当前提醒读取服务尚未就绪")
            result = await self.reminders.prepare(role, envelope.get("payload"), active)
            status, response = 200, {"result": result}
        except web.HTTPException as failure:
            status, response = failure.status, {"error": {"status": failure.status, "message": failure.text}}
        self.record(role, "boss.reminder.prepare", status)
        if connection.close_code is None:
            await connection.send(json.dumps({"event": "webui_response", "request_id": request_id, "ok": status == 200, **response}, ensure_ascii=False))

    async def _assignment_response(self, connection, role, envelope):
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("交办读取缺少有效请求编号")
        def active():
            return self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
        try:
            if self.assignment is None:
                raise web.HTTPServiceUnavailable(text="当前交办读取服务尚未就绪")
            result = await self.assignment.prepare(role, envelope.get("payload"), active)
            status, response = 200, {"result": result}
        except web.HTTPException as failure:
            status, response = failure.status, {"error": {"status": failure.status, "message": failure.text}}
        self.record(role, "boss.assignment.prepare", status)
        if connection.close_code is None:
            await connection.send(json.dumps({"event": "webui_response", "request_id": request_id, "ok": status == 200, **response}, ensure_ascii=False))

    async def _mvp_response(self, connection, role, envelope):
        request_id, action = envelope.get("request_id"), envelope["action"]
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("采购请求缺少有效编号")
        def active():
            return self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
        try:
            if self.mvp is None:
                raise web.HTTPServiceUnavailable(text="当前采购体验尚未启用")
            payload = envelope.get("payload")
            if action == "boss.mvp.cancel":
                if not isinstance(payload, dict) or set(payload) != {"client_request_id"}:
                    raise web.HTTPBadRequest(text="取消请求字段无效")
                result = self.mvp.cancel_query(role, payload["client_request_id"], active)
            else:
                result = await self.mvp.query(role, payload, active)
            status, response = 200, {"result": result}
        except asyncio.CancelledError:
            status, response = 409, {"error": {"status": 409, "message": "当前查询已取消，请读取原编号确认结果"}}
        except web.HTTPException as failure:
            status, response = failure.status, {"error": {"status": failure.status, "message": failure.text}}
        self.record(role, action, status)
        if connection.close_code is None:
            await connection.send(json.dumps({"event": "webui_response", "request_id": request_id, "ok": status == 200, **response}, ensure_ascii=False))

    async def _morning_response(self, connection, role, envelope):
        request_id, action = envelope.get("request_id"), envelope["action"]
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("晨间请求缺少有效编号")
        def active():
            return self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
        try:
            if self.morning is None:
                raise web.HTTPServiceUnavailable(text="晨间Runtime尚未就绪")
            payload = envelope.get("payload")
            if action == "boss.morning.bind":
                if not isinstance(payload, dict) or not {"client_request_id", "chat_id", "date", "timezone"} <= set(payload) <= {"client_request_id", "chat_id", "date", "timezone", "list_id", "item_id"}:
                    raise web.HTTPBadRequest(text="原生晨间绑定字段无效")
                result = self.morning.native.bind(role, payload["client_request_id"], {key:value for key,value in payload.items() if key != "client_request_id"},
                    attached=lambda chat_id: chat_id in self.webui_connection_chats(connection), active=active)
            elif action == "boss.morning.cancel":
                if not isinstance(payload, dict) or set(payload) != {"client_request_id"}:
                    raise web.HTTPBadRequest(text="取消请求字段无效")
                result = self.morning.cancel(role, payload["client_request_id"], active)
            else:
                result = await self.morning.execute(role, payload, active)
            status, response = 200, {"result": result}
        except asyncio.CancelledError:
            status, response = 409, {"error": {"status": 409, "message": "晨间运行已取消，请读取原请求结果"}}
        except web.HTTPException as failure:
            status, response = failure.status, {"error": {"status": failure.status, "message": failure.text}}
        self.record(role, action, status)
        if connection.close_code is None:
            await connection.send(json.dumps({"event": "webui_response", "request_id": request_id, "ok": status == 200, **response}, ensure_ascii=False))

    async def _bi_response(self, connection, role, envelope):
        request_id, action = envelope.get("request_id"), envelope["action"]
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("经营请求缺少有效编号")
        def active():
            return self.connection_roles.get(connection) == "BOSS" and self.token_roles.get(self.connection_tokens.get(connection)) == "BOSS" and connection.close_code is None and time.monotonic() < self.connection_expirations.get(connection, 0)
        try:
            if self.bi is None:
                raise web.HTTPServiceUnavailable(text="经营Runtime尚未就绪")
            payload = envelope.get("payload")
            if action == "boss.bi.cancel":
                if not isinstance(payload, dict) or set(payload) != {"client_request_id"}:
                    raise web.HTTPBadRequest(text="取消请求字段无效")
                result = self.bi.cancel(role, payload["client_request_id"], active)
            else:
                result = await self.bi.execute(role, payload, action == "boss.bi.follow_up", active)
            status, response = 200, {"result":result}
        except asyncio.CancelledError:
            status, response = 409, {"error":{"status":409,"message":"经营运行已取消，请读取原请求结果"}}
        except web.HTTPException as failure:
            status, response = failure.status, {"error":{"status":failure.status,"message":failure.text}}
        self.record(role, action, status)
        if connection.close_code is None:
            await connection.send(json.dumps({"event":"webui_response","request_id":request_id,"ok":status == 200,**response}, ensure_ascii=False))

    async def _connection_loop(self, connection):
        if self.connection_roles.get(connection) == "BOSS":
            try:
                await super()._connection_loop(connection)
            finally:
                self.connection_roles.pop(connection, None)
            return
        await connection.send(json.dumps({"event": "ready", "chat_id": str(uuid.uuid4()), "client_id": "maintainer-1"}))
        try:
            async for raw in connection:
                frame = json.loads(raw)
                if not isinstance(frame, dict):
                    raise ValueError("维护请求必须为已定义的 JSON 对象")
                await self._dispatch_active_envelope(connection, "maintainer-1", frame)
        finally:
            await self._cleanup_connection(connection)
            self.connection_roles.pop(connection, None)
