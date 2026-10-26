from dataclasses import dataclass, replace
import json

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.hook import AgentHook
from nanobot.session.manager import SessionManager
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key
from nanobot.webui.transcript import normalize_webui_turn_id

from business import checksum, now, require
from boss_morning import SCHEMA
from boss_simulation_api import _context
from boss_conversation import ConversationAPI
from boss_conversation_sources import ConversationSources


VERSION = "1.1.0"
BIND_SCHEMA = {"type": "object", "additionalProperties": False, "$defs": SCHEMA["$defs"],
    "required": ["chat_id", "date", "timezone"], "properties": {
        "chat_id": {"type": "string"}, **SCHEMA["$defs"]["Day"]["properties"],
        "list_id": {"$ref": "#/$defs/Id"}, "item_id": {"$ref": "#/$defs/Id"}},
    "dependentRequired": {"list_id": ["item_id"], "item_id": ["list_id"]}}
REQUEST_ID_SCHEMA = {"type": "string", "minLength": 8, "maxLength": 128, "pattern": "^[A-Za-z0-9_.-]+$"}
TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELED", "TIMED_OUT"})
from boss_execution_scope import NAMESPACE as NS


@dataclass(frozen=True)
class NativeTurnProof:
    grant: object
    binding_id: str
    content_sha256: str
    turn_id: str


class NativeMorningAdapter:
    def __init__(self, service, *, request_attribute="product_morning_request"):
        self.service, self.store = service, service.store
        self.request_attribute = request_attribute
        self.proofs = {}
        self.native_sessions = None
        self.source_selection = None

    def bind_sessions(self, native_sessions):
        require(isinstance(native_sessions, SessionManager), "晨间绑定需要实际原生SessionManager", web.HTTPBadRequest)
        require(self.native_sessions is None or self.native_sessions is native_sessions,
                "晨间绑定已经采用其他原生会话服务", web.HTTPConflict)
        self.native_sessions = native_sessions
        self.source_selection = ConversationSources(self.store, native_sessions)

    def _identity(self, db):
        self.store.active(db, NS)
        return _context(db)

    @staticmethod
    def _same_scope(row, identity):
        require(all(row[field] == identity[field] for field in ("owner_id", "dataset_id", "dataset_version")),
                "原生晨间绑定不属于当前本人资料范围", web.HTTPForbidden)

    @staticmethod
    def _authorize(role, active, attached=None, chat_id=None):
        require(role == "BOSS" and callable(active) and active(), "原生晨间需要当前本人认证", web.HTTPUnauthorized)
        if attached is not None:
            require(callable(attached) and attached(chat_id), "当前连接没有采用该原生会话", web.HTTPForbidden)

    @staticmethod
    def turn_key(chat_id, turn_id):
        require(is_valid_webui_chat_id(chat_id) and isinstance(turn_id, str)
                and normalize_webui_turn_id(turn_id) == turn_id, "原生会话或轮次编号无效", web.HTTPBadRequest)
        return "morning-native-" + checksum({"chat_id": chat_id, "turn_id": turn_id})

    def _binding(self, db, chat_id):
        rows = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='morning_native_binding' AND json_extract(body,'$.chat_id')=?",
                          (NS, chat_id)).fetchall()
        require(len(rows) <= 1, "原生会话包含冲突晨间绑定", web.HTTPConflict)
        return json.loads(rows[0][0]) if rows else None

    def _current(self, binding):
        preview = self.service.api.read("BOSS", {key: binding[key] for key in ("date", "timezone")})
        require(all(preview[key] == binding[key] for key in ("snapshot_sha256", "order_version")),
                "原生晨间资料或本人次序已变化", web.HTTPConflict)
        if binding["list_id"] is not None:
            result = self.service.api.read_list("BOSS", binding["list_id"])
            require(all(result["result"][key] == binding[key] for key in ("date", "timezone", "snapshot_sha256"))
                    and result["current_order"]["version"] == binding["order_version"], "原生清单与当前绑定不符", web.HTTPConflict)
            if binding["item_id"] is not None:
                self.service.api.detail("BOSS", binding["list_id"], binding["item_id"])
        return preview

    @staticmethod
    def _binding_result(row):
        return {key: row[key] for key in ("binding_id", "chat_id", "session_id", "date", "timezone",
                "snapshot_sha256", "order_version", "list_id", "item_id", "last_request_id")}

    def bind(self, role, client_request_id, payload, *, attached, active):
        require(callable(attached), "缺少当前连接的原生会话证明", web.HTTPForbidden)
        self._authorize(role, active)
        require(not list(Draft202012Validator(REQUEST_ID_SCHEMA).iter_errors(client_request_id))
                and not list(Draft202012Validator(BIND_SCHEMA, format_checker=FormatChecker()).iter_errors(payload)),
                "原生晨间绑定不符合Schema", web.HTTPBadRequest)
        require(is_valid_webui_chat_id(payload["chat_id"]), "原生会话编号无效", web.HTTPBadRequest)
        self._authorize(role, active, attached, payload["chat_id"])
        with self.store.connect() as db:
            db.execute("BEGIN")
            identity = self._identity(db)
            previous = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='morning_native_binding' AND id=?",
                                  (NS, client_request_id)).fetchone()
            if previous:
                row = json.loads(previous[0])
                self._same_scope(row, identity)
                require(row["payload_sha256"] == checksum(payload), "原绑定编号内容已变化", web.HTTPConflict)
                return self.binding_receipt(role, client_request_id, active=active)
        preview = self.service.api.read(role, {key: payload[key] for key in ("date", "timezone")})
        row = {**{key: identity[key] for key in ("owner_id", "dataset_id", "dataset_version")},
            **{key: preview[key] for key in ("date", "timezone", "snapshot_sha256", "order_version")},
            "binding_id": client_request_id, "chat_id": payload["chat_id"], "session_id": webui_session_key(payload["chat_id"]),
            "payload_sha256": checksum(payload), "list_id": payload.get("list_id"), "item_id": payload.get("item_id"),
            "last_request_id": None, "created_at": now()}
        self._current(row)
        self._authorize(role, active, attached, row["chat_id"])
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._same_scope(row, self._identity(db))
            require(self._binding(db, row["chat_id"]) is None, "当前会话已经绑定晨间范围", web.HTTPConflict)
            require(db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='morning_native_binding' AND id=?",
                               (NS, client_request_id)).fetchone() is None, "原绑定编号已经存在，请读取原结果", web.HTTPConflict)
            require(isinstance(self.native_sessions, SessionManager), "晨间新增绑定尚未接收实际原生会话服务", web.HTTPServiceUnavailable)
            # 占用检查与保存共用当前写入事务，其他入口不能同时接管同一会话。
            ConversationAPI(self.store).business_entry(self.native_sessions).require_available_in_transaction(
                db, {"session_id": row["session_id"], "chat_id": row["chat_id"]})
            self.store.put(db, NS, "morning_native_binding", client_request_id, row)
        return self.binding_receipt(role, client_request_id, active=active)

    def binding_receipt(self, role, client_request_id, *, active):
        self._authorize(role, active)
        require(not list(Draft202012Validator(REQUEST_ID_SCHEMA).iter_errors(client_request_id)), "原绑定编号无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            identity = self._identity(db)
            saved = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='morning_native_binding' AND id=?",
                               (NS, client_request_id)).fetchone()
            row = json.loads(saved[0]) if saved else None
            if row is not None:
                self._same_scope(row, identity)
        self._authorize(role, active)
        return {"source_type": "SIMULATED", "client_request_id": client_request_id,
            "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE",
            "result": self._binding_result(row) if row else None,
            "adoption_state": "NOT_REVALIDATED_BY_LOOKUP", "write_performed_by_lookup": False,
            "business_authority_granted": False}

    def _synchronize(self, binding):
        if binding["last_request_id"] is None:
            return binding
        receipt = self.service.receipt("BOSS", binding["last_request_id"])
        require(receipt["request_state"] in TERMINAL, "当前晨间轮次尚未终止，请读取原编号", web.HTTPConflict)
        result = receipt["receipt"]["result"]
        if binding["list_id"] is None and result is not None:
            require(all(result[key] == binding[key] for key in ("date", "timezone", "snapshot_sha256")),
                    "首轮实际清单与原生绑定不符", web.HTTPConflict)
            binding = {**binding, "list_id": result["list_id"]}
        return binding

    def admit(self, role, chat_id, turn_id, content, *, attached, active):
        with self.store.connect() as db:
            binding = self._binding(db, chat_id)
            if binding is None:
                return None
            require(callable(attached), "缺少当前连接的原生会话证明", web.HTTPForbidden)
            self._authorize(role, active, attached, chat_id)
            key = self.turn_key(chat_id, turn_id)
            require(isinstance(content, str) and 1 <= len(content) <= 4000 and bool(content.strip()),
                    "晨间原生输入无效", web.HTTPBadRequest)
            identity = self._identity(db)
            self._same_scope(binding, identity)
            existing = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='morning_public_request' AND id=?", (NS, key)).fetchone()
            if existing:
                row = json.loads(existing[0])
                self._same_scope(row, identity)
                require(row.get("native_binding_id") == binding["binding_id"] and row.get("native_content_sha256") == checksum(content),
                        "原生轮次编号内容已变化", web.HTTPConflict)
                return {"enqueue": False, **self.turn_receipt(role, chat_id, turn_id, active=active)}
        previous_key = binding["last_request_id"]
        binding = self._synchronize(binding)
        self._current(binding)
        require(self.source_selection is not None, "晨间会话资料服务尚未接入", web.HTTPServiceUnavailable)
        source_selection = self.source_selection.pin(chat_id)
        payload = {"client_request_id": key, "question": content, **{field: binding[field] for field in ("date", "timezone")}}
        if binding["list_id"] is not None:
            payload["list_id"] = binding["list_id"]
        if binding["item_id"] is not None:
            payload["item_id"] = binding["item_id"]
        def current_active():
            if not active() or not attached(chat_id):
                return False
            require(self.source_selection.pin(chat_id) == source_selection, "晨间会话选择的知识资料已经变化", web.HTTPConflict)
            with self.store.connect() as db:
                self._same_scope(binding, self._identity(db))
            self._current(binding)
            return True
        grant = self.service._request(role, payload, current_active)
        require(grant is not None, "原生轮次已经准备，请读取原编号", web.HTTPConflict)
        prepared = False
        try:
            grant = replace(grant, session_id=binding["session_id"], source_selection_json=json.dumps(source_selection) if source_selection is not None else None)
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._same_scope(binding, self._identity(db))
                saved = self.store.get(db, NS, "morning_native_binding", binding["binding_id"])
                require(saved["last_request_id"] == previous_key, "晨间会话已经采用其他轮次", web.HTTPConflict)
                row = self.store.get(db, NS, "morning_public_request", key)
                require(row["status"] == "PREPARED", "晨间原生轮次已经开始", web.HTTPConflict)
                row.update(session_id=binding["session_id"], native_binding_id=binding["binding_id"],
                           native_chat_id=chat_id, native_turn_id=turn_id, native_content_sha256=checksum(content), source_selection=source_selection)
                self.store.put(db, NS, "morning_public_request", key, row)
                binding["last_request_id"] = key
                self.store.put(db, NS, "morning_native_binding", binding["binding_id"], binding)
            self.proofs[key] = NativeTurnProof(grant, binding["binding_id"], checksum(content), turn_id)
            result = {"enqueue": True, **self.turn_receipt(role, chat_id, turn_id, active=active)}
            prepared = True
            return result
        finally:
            if not prepared:
                self.finish(key)

    def turn_receipt(self, role, chat_id, turn_id, *, active):
        self._authorize(role, active)
        key = self.turn_key(chat_id, turn_id)
        result = self.service.receipt(role, key)
        with self.store.connect() as db:
            row = self.store.get(db, NS, "morning_public_request", key)
        require(row.get("native_chat_id") == chat_id and row.get("native_turn_id") == turn_id,
                "原请求不属于当前原生轮次", web.HTTPForbidden)
        self._authorize(role, active)
        return {**result, "chat_id": chat_id, "turn_id": turn_id, "session_id": row["session_id"],
                "binding_id": row["native_binding_id"]}

    async def native_context(self, request):
        with self.store.connect() as db:
            rows = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='morning_native_binding' AND (json_extract(body,'$.chat_id')=? OR json_extract(body,'$.session_id')=?)",
                              (NS, request.chat_id, request.session_key)).fetchall()
            if not rows:
                return None
            require(len(rows) == 1, "原生晨间会话归属冲突", web.HTTPForbidden)
            binding = json.loads(rows[0][0])
            self._same_scope(binding, self._identity(db))
        require(request.channel == "websocket" and request.sender_id == binding["owner_id"]
                and request.chat_id == binding["chat_id"] and request.session_key == binding["session_id"],
                "原生晨间请求身份或会话不符", web.HTTPForbidden)
        key = self.turn_key(request.chat_id, request.metadata.get("webui_turn_id"))
        proof = self.proofs.get(key)
        require(proof is not None, "当前晨间轮次缺少已认证连接证明", web.HTTPForbidden)
        ready = False
        try:
            require(proof.binding_id == binding["binding_id"] and binding["last_request_id"] == key
                    and proof.content_sha256 == checksum(request.original_user_text), "原生晨间输入或绑定不符", web.HTTPForbidden)
            self._authorize("BOSS", proof.grant.active)
            self._current(binding)
            with self.store.connect() as db:
                row = self.store.get(db, NS, "morning_public_request", key)
                require(row["status"] == "PREPARED" and "run_id" not in row, "原生晨间轮次已经进入Runtime", web.HTTPConflict)
            require(self.request_attribute not in request.attributes, "原生请求包含其他晨间授权上下文", web.HTTPForbidden)
            request.attributes[self.request_attribute] = proof.grant
            ready = True
        finally:
            if not ready:
                self.finish(key)
        return None

    def finish(self, client_request_id):
        self.proofs.pop(client_request_id, None)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.store.get(db, NS, "morning_public_request", client_request_id)
            if "run_id" not in row and row["status"] == "PREPARED":
                row.update(status="FAILED", finished_at=now())
                self.store.put(db, NS, "morning_public_request", client_request_id, row)

    def hook_factory(self, context):
        grant = context.attributes.get(self.request_attribute)
        if grant is None:
            return None
        proof = self.proofs.get(grant.key)
        if proof is None:
            return None
        require(grant is proof.grant and context.session_key == grant.session_id,
                "原生晨间运行证明不符", web.HTTPForbidden)
        return NativeMorningHook(self, grant.key)


class NativeMorningHook(AgentHook):
    def __init__(self, adapter, key):
        super().__init__(reraise=True)
        self.adapter, self.key = adapter, key

    async def on_finally(self, context):
        self.adapter.finish(self.key)
