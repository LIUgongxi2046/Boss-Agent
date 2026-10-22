import hmac
import json
import uuid
from urllib.parse import parse_qs, urlsplit

from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.webui.http_utils import bearer_token
from websockets.datastructures import Headers
from websockets.http11 import Request

from business import now


class RoleChannel(WebSocketChannel):
    def __init__(self, original, secrets, audit):
        super().__init__(original.config, original.bus, gateway=original.gateway)
        self.secrets = secrets
        self.audit = audit
        self.token_roles = {}
        self.connection_roles = {}

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
            return response
        if address.path.startswith("/api/"):
            if not self.gateway.tokens.check_api_token(request):
                self.record(None, address.path, 401)
                return connection.respond(401, "未认证")
            if address.path == "/api/boss/identity":
                self.record(role, address.path, 200)
                return connection.respond(200, json.dumps({"role": role, "owner_id": "boss-1" if role == "BOSS" else None}))
            allowed = role == "BOSS" or role == "MAINTAINER" and address.path in {"/api/settings", "/api/settings/usage", "/api/settings/provider-models", "/api/webui/automations", "/api/webui/skills", "/api/settings/mcp-presets"}
            if not allowed:
                self.record(role, address.path, 403)
                return connection.respond(403, "身份权限不足")
        return await super()._dispatch_http(connection, request)

    async def _dispatch_active_envelope(self, connection, client_id, envelope):
        role = self.connection_roles.get(connection)
        kind = envelope.get("type")
        action = envelope.get("action", "")
        permitted = role == "BOSS" and kind != "webui_request"
        permitted = permitted or role == "BOSS" and action in {"sidebar.update", "session.rename", "session.delete"}
        permitted = permitted or role == "MAINTAINER" and kind == "webui_request" and action in {"settings.runtime_config.update", "settings.model_configuration.update", "settings.provider.update", "automation.enable", "automation.disable", "automation.delete", "automation.run", "automation.update"}
        if not permitted:
            self.record(role, action or kind, 403)
            event = {"event": "webui_response", "request_id": envelope.get("request_id"), "ok": False, "error": {"status": 403, "message": "身份权限不足"}} if kind == "webui_request" else {"event": "error", "detail": "access_denied", "reason": "身份权限不足"}
            await connection.send(json.dumps(event, ensure_ascii=False))
            return
        await super()._dispatch_active_envelope(connection, "boss-1" if role == "BOSS" else "maintainer-1", envelope)

    async def _connection_loop(self, connection):
        if self.connection_roles.get(connection) == "BOSS":
            await super()._connection_loop(connection)
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
