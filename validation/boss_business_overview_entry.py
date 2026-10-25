import json
from pathlib import Path
from uuid import uuid4

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key

from business import checksum, now, require
from boss_business_overview import BusinessOverviewAPI, owner
from boss_conversation import optional
from boss_simulation_api import _context


STORE = "conversation_business_store"
PREPARATION = "conversation_business_preparation"
BINDING = "conversation_business_binding"
IDENTITY = ("namespace", "owner_id", "dataset_id", "dataset_version")
SEALED = (*IDENTITY, "store_reference", "preparation_id", "client_request_id", "request_sha256", "prepared_at",
          "applied_scope", "scope_sha256", "topic_reference", "topic_sha256", "snapshot_sha256", "source_references", "business_at")
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "specs/business-overview.schema.json").read_text())


def validate(name, value):
    require(not list(Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}, format_checker=FormatChecker()).iter_errors(value)),
            "经营会话入口输入输出不符合Schema", web.HTTPBadRequest)
    return value


class BusinessOverviewEntry:
    def __init__(self, conversation, native_sessions):
        require(native_sessions is not None, "经营会话入口需要实际原生会话服务", web.HTTPServiceUnavailable)
        self.store, self.sessions = conversation.store, native_sessions
        self.overview = BusinessOverviewAPI(self.store)

    @staticmethod
    def _request_id(client_request_id):
        return "business-entry-" + checksum({"client_request_id": client_request_id})

    @staticmethod
    def _context(query):
        validate("EntryNativeContext", query)
        require(is_valid_webui_chat_id(query["chat_id"]) and query["session_id"] == webui_session_key(query["chat_id"]),
                "经营会话绑定的原生会话归属不符", web.HTTPForbidden)
        return query

    def _scope(self, db, row, context):
        require(all(row[field] == context[field] for field in IDENTITY), "经营会话选择不属于当前本人资料范围", web.HTTPForbidden)
        identity = self.store.get(db, context["namespace"], STORE, "instance")
        require(row["store_reference"] == identity["store_reference"], "经营会话选择不属于当前资料实例", web.HTTPConflict)
        require(row["preparation_sha256"] == checksum({field: row[field] for field in SEALED}), "经营会话准备的固定引用不符", web.HTTPConflict)

    def _pins(self, db, scope, topic_reference, snapshot_sha256):
        view = self.overview.project_in_transaction("BOSS", db, scope)
        require(view["snapshot_sha256"] == snapshot_sha256, "已应用经营范围或来源快照已经变化", web.HTTPConflict)
        topic = None
        if topic_reference is not None:
            topic = next(row for row in view["topics"] if row["page_id"] == topic_reference["page_id"])
            require(topic_reference["use"] is None or topic_reference["use"] in topic["uses"], "当前专题不支持所选用途", web.HTTPBadRequest)
        return view, {"scope_sha256": checksum(view["applied_scope"]), "topic_sha256": checksum(topic) if topic is not None else None,
            "business_at": view["business_at"], "source_references": [{"kind": "document", "id": row["source_id"],
                "version": row["version"], "content_sha256": row["sha256"], "status": row["status"]}
                for row in sorted(view["sources"], key=lambda row: row["source_id"])]}

    def _session(self, query):
        session = self.sessions.read_session_snapshot(query["session_id"])
        require(session is not None, "实际原生会话尚未创建", web.HTTPNotFound)
        require(session.key == query["session_id"], "实际原生会话标识不符", web.HTTPForbidden)
        return session

    def require_available_in_transaction(self, db, query):
        self._context(query)
        # 共享入口在自己的写入事务内调用，检查与绑定能够保持原子性。
        occupied = db.execute("SELECT 1 FROM objects WHERE kind IN ('runtime_run','conversation_intent',"
            "'morning_native_binding','conversation_task_binding','conversation_business_binding') "
            "AND (json_extract(body,'$.session_id')=? OR json_extract(body,'$.chat_id')=?) LIMIT 1",
            (query["session_id"], query["chat_id"])).fetchone()
        require(occupied is None, "原生会话已经承接其他事项或原意图", web.HTTPConflict)

    def _current(self, db, context, row):
        self._scope(db, row, context)
        view, pins = self._pins(db, row["applied_scope"], row["topic_reference"], row["snapshot_sha256"])
        require(all(row[field] == value for field, value in pins.items()), "经营范围或来源与固定选择不符", web.HTTPConflict)
        if row["binding_state"] == "BOUND":
            native = row["context"]
            query = {field: native[field] for field in ("session_id", "chat_id")}
            binding = optional(db, context["namespace"], BINDING, query["session_id"])
            require(binding is not None and all(binding[field] == context[field] for field in IDENTITY)
                    and all(binding[field] == native[field] for field in native)
                    and all(binding[field] == row[field] for field in ("store_reference", "preparation_id", "preparation_sha256")),
                    "经营会话固定选择与原绑定不符", web.HTTPConflict)
            require(self._session(query).created_at.isoformat() == native["native_session_created_at"],
                    "原生会话实例已经变化，需要新的明确选择", web.HTTPConflict)
            conflict = db.execute("SELECT 1 FROM objects WHERE kind IN ('morning_native_binding','conversation_task_binding') "
                "AND (json_extract(body,'$.session_id')=? OR json_extract(body,'$.chat_id')=?) LIMIT 1",
                (query["session_id"], query["chat_id"])).fetchone()
            require(conflict is None, "当前原生会话存在其他入口绑定", web.HTTPConflict)
        return view

    @staticmethod
    def _view(row, verified):
        return validate("EntryPreparation", {"source_type": "RUNTIME_RECORD", **{field: row[field] for field in
            ("store_reference", "preparation_id", "client_request_id", "preparation_sha256", "prepared_at", "bound_at", "binding_state",
             "context", "applied_scope", "scope_sha256", "topic_reference", "topic_sha256", "snapshot_sha256", "source_references", "business_at")},
            "return_reference": {"page_id": "N03", **{field: row[field] for field in ("applied_scope", "topic_reference", "snapshot_sha256")}},
            "current_use_verified": verified, "business_authorization_granted": False, "business_mutation_performed": False})

    def prepare(self, role, payload):
        owner(role)
        validate("EntryPrepare", payload)
        identifier = self._request_id(payload["client_request_id"])
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            row = optional(db, context["namespace"], PREPARATION, identifier)
            if row is not None:
                self._scope(db, row, context)
                require(row["request_sha256"] == checksum(payload), "同一经营会话原请求携带不同选择", web.HTTPConflict)
                self._current(db, context, row)
                return self._view(row, True)
            _, pins = self._pins(db, payload["applied_scope"], payload["topic_reference"], payload["snapshot_sha256"])
            identity = optional(db, context["namespace"], STORE, "instance")
            if identity is None:
                identity = {"store_reference": str(uuid4())}
                self.store.put(db, context["namespace"], STORE, "instance", identity)
            row = {**{field: context[field] for field in IDENTITY}, **identity, **pins,
                **{field: payload[field] for field in ("client_request_id", "applied_scope", "topic_reference", "snapshot_sha256")},
                "preparation_id": identifier, "request_sha256": checksum(payload), "prepared_at": now()}
            row["preparation_sha256"] = checksum({field: row[field] for field in SEALED})
            row.update(binding_state="PREPARED", context=None, bound_at=None, bind_payload_sha256=None)
            self.store.put(db, context["namespace"], PREPARATION, identifier, row)
            return self._view(row, True)

    def bind(self, role, payload):
        owner(role)
        validate("EntryBind", payload)
        query = self._context({"chat_id": payload["chat_id"], "session_id": webui_session_key(payload["chat_id"])})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            row = self.store.get(db, context["namespace"], PREPARATION, payload["preparation_id"])
            self._scope(db, row, context)
            require(row["client_request_id"] == payload["client_request_id"] and row["preparation_sha256"] == payload["preparation_sha256"],
                    "经营会话绑定与本次原选择不符", web.HTTPConflict)
            self._current(db, context, row)
            if row["binding_state"] == "BOUND":
                require(row["bind_payload_sha256"] == checksum(payload) and all(row["context"][field] == query[field] for field in query),
                        "原准备已经绑定其他会话或选择", web.HTTPConflict)
                return self._view(row, True)
            session = self._session(query)
            require(not session.messages, "经营入口需要尚未使用的原生会话", web.HTTPConflict)
            self.require_available_in_transaction(db, query)
            native = {**query, "native_session_created_at": session.created_at.isoformat()}
            row.update(binding_state="BOUND", context=native, bound_at=now(), bind_payload_sha256=checksum(payload))
            self.store.put(db, context["namespace"], BINDING, query["session_id"], {**{field: row[field] for field in
                (*IDENTITY, "store_reference", "preparation_id", "preparation_sha256")}, **native})
            self.store.put(db, context["namespace"], PREPARATION, row["preparation_id"], row)
            return self._view(row, True)

    def read(self, role, query):
        owner(role)
        self._context(query)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            binding = optional(db, context["namespace"], BINDING, query["session_id"])
            row, view = None, None
            if binding is not None:
                require(all(binding[field] == context[field] for field in IDENTITY) and all(binding[field] == query[field] for field in query),
                        "经营会话绑定不属于当前会话及资料范围", web.HTTPForbidden)
                row = self.store.get(db, context["namespace"], PREPARATION, binding["preparation_id"])
                require(row["binding_state"] == "BOUND" and all(row["context"][field] == query[field] for field in query),
                        "经营会话选择与当前绑定不符", web.HTTPConflict)
                view = self._current(db, context, row)
            return validate("EntryContext", {"source_type": "RUNTIME_RECORD", **query,
                "binding_state": "BOUND" if row else "UNBOUND", "entry": self._view(row, True) if row else None, "overview": view,
                "references": [{key: ref[key] for key in ("kind", "id", "version")} for ref in row["source_references"]
                    if ref["status"] == "VALID" and ref["version"] is not None] if row else [],
                "current_use_verified": row is not None, "business_authorization_granted": False, "business_mutation_performed": False})

    def receipt(self, role, payload):
        owner(role)
        validate("EntryReceiptInput", payload)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            row = optional(db, context["namespace"], PREPARATION, self._request_id(payload["client_request_id"]))
            if row is not None:
                self._scope(db, row, context)
            return validate("EntryReceipt", {"source_type": "RUNTIME_RECORD", **payload,
                "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "entry": self._view(row, False) if row else None,
                "business_authorization_granted": False, "business_mutation_performed": False})
