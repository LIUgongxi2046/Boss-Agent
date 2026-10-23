import asyncio
import hmac
import json
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.webui.http_utils import bearer_token
from websockets.datastructures import Headers
from websockets.http11 import Request
from aiohttp import web

from business import now
from boss_page_api import BossPageAPI
from boss_command_api import BossCommandAPI


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
        self.bi_responses = set()
        self.skills = skills
        self.boss_pages = BossPageAPI(business_store, runtime_control=runtime_control, skills=skills) if business_store is not None else None
        self.boss_commands = BossCommandAPI(business_store, runtime_control=runtime_control, skills=skills) if business_store is not None else None

    def record(self, role, operation, status):
        with self.audit.open("a") as output:
            output.write(json.dumps({"at": now(), "role": role, "operation": operation, "status": status}, ensure_ascii=False) + "\n")

    async def _dispatch_http(self, connection, request):
        address = urlsplit(request.path)
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
                return connection.respond(200, json.dumps({"role": role, "owner_id": "boss-1" if role == "BOSS" else None}))
            if address.path.startswith("/api/boss/ui/"):
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
        await super()._dispatch_active_envelope(connection, "boss-1" if role == "BOSS" else "maintainer-1", envelope)

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
