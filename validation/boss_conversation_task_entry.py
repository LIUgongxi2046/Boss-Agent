from aiohttp import web
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key

from business import checksum, now, require
from boss_conversation import optional, owner_role, validate
from boss_simulation_api import _context


PREPARATION = "conversation_task_preparation"
BINDING = "conversation_task_binding"
IDENTITY = ("namespace", "owner_id", "dataset_id", "dataset_version")
SEALED = (*IDENTITY, "preparation_id", "client_request_id", "request_sha256", "prepared_at",
          "task_reference", "task_sha256", "source_binding_sha256", "source_references")


class ConversationTaskEntry:
    def __init__(self, conversation, native_sessions):
        require(native_sessions is not None, "任务会话入口需要实际原生会话服务", web.HTTPServiceUnavailable)
        self.conversation, self.store, self.sessions = conversation, conversation.store, native_sessions

    @staticmethod
    def _request_id(client_request_id):
        return "task-entry-" + checksum({"client_request_id": client_request_id})

    @staticmethod
    def _scope(row, context):
        require(all(row[field] == context[field] for field in IDENTITY), "任务会话准备不属于当前本人资料范围", web.HTTPForbidden)
        require(row["preparation_sha256"] == checksum({field: row[field] for field in SEALED}), "任务会话准备的固定引用不符", web.HTTPConflict)

    @staticmethod
    def _context(query):
        validate("TaskEntryNativeContext", query)
        require(is_valid_webui_chat_id(query["chat_id"]) and query["session_id"] == webui_session_key(query["chat_id"]),
                "任务会话绑定的原生会话归属不符", web.HTTPForbidden)
        return query

    def _pins(self, db, context, reference):
        task = self.conversation.task_in_transaction(db, context, reference["id"], reference["version"])
        ns = context["namespace"]
        initial = self.store.get(db, ns, "initial", "snapshot")
        identifiers = sorted(set(task["source_refs"]) | ({task["origin_source_id"]} if task.get("origin_source_id") else set()))
        documents = self.store.assignment_sources(db, ns, initial, identifiers)
        binding = self.store.get(db, ns, "assignment_source_binding", task["task_id"])
        return {"task_sha256": checksum(task), "source_binding_sha256": checksum(binding),
            "source_references": [{"kind": "document", "id": identifier, "version": documents[identifier]["version"],
                "content_sha256": checksum(documents[identifier])} for identifier in identifiers]}

    def _current(self, db, context, row):
        self._scope(row, context)
        pins = self._pins(db, context, row["task_reference"])
        require(all(row[field] == value for field, value in pins.items()), "任务或来源与本次选定的固定版本不符", web.HTTPConflict)
        if row["binding_state"] == "BOUND":
            query = row["context"]
            binding = optional(db, context["namespace"], BINDING, query["session_id"])
            require(binding is not None and all(binding[field] == context[field] for field in IDENTITY)
                    and all(binding[field] == query[field] for field in query)
                    and binding["preparation_id"] == row["preparation_id"] and binding["preparation_sha256"] == row["preparation_sha256"],
                    "任务会话固定选择与原绑定不符", web.HTTPConflict)
            session = self._session(query)
            require(session.created_at.isoformat() == binding["native_session_created_at"], "原生会话实例已经变化，需要新的明确选择", web.HTTPConflict)

    @staticmethod
    def _view(row, verified):
        reference = row["task_reference"]
        return validate("TaskEntryPreparation", {"source_type": "RUNTIME_RECORD",
            **{field: row[field] for field in ("preparation_id", "client_request_id", "preparation_sha256", "prepared_at",
                "bound_at", "binding_state", "context", "task_reference", "source_references")},
            "return_reference": {"page_id": "F06", "task_id": reference["id"], "task_version": reference["version"]},
            "current_use_verified": verified, "business_authorization_granted": False, "business_mutation_performed": False})

    def prepare(self, role, payload):
        owner_role(role)
        validate("TaskEntryPrepare", payload)
        identifier = self._request_id(payload["client_request_id"])
        digest = checksum(payload)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            row = optional(db, context["namespace"], PREPARATION, identifier)
            if row is not None:
                self._scope(row, context)
                require(row["request_sha256"] == digest, "同一任务会话原请求携带不同选择", web.HTTPConflict)
                self._current(db, context, row)
                return self._view(row, True)
            reference = {"kind": "task", "id": payload["task_id"], "version": payload["task_version"]}
            row = {**{field: context[field] for field in IDENTITY}, "preparation_id": identifier,
                "client_request_id": payload["client_request_id"], "request_sha256": digest, "prepared_at": now(),
                "task_reference": reference, **self._pins(db, context, reference)}
            row["preparation_sha256"] = checksum({field: row[field] for field in SEALED})
            row.update(binding_state="PREPARED", context=None, bound_at=None, bind_payload_sha256=None)
            self.store.put(db, context["namespace"], PREPARATION, identifier, row)
            return self._view(row, True)

    def _session(self, query):
        session = self.sessions.read_session_snapshot(query["session_id"])
        require(session is not None, "实际原生会话尚未创建", web.HTTPNotFound)
        require(session.key == query["session_id"], "实际原生会话标识不符", web.HTTPForbidden)
        return session

    def _unused_session(self, db, query):
        session = self._session(query)
        require(not session.messages, "任务入口需要尚未使用的原生会话", web.HTTPConflict)
        # 同一原生会话只承接一个明确入口，其他资料空间的既有绑定也不能被接管。
        occupied = db.execute("SELECT 1 FROM objects WHERE kind IN ('runtime_run','conversation_intent',"
            "'morning_native_binding','conversation_task_binding') AND (json_extract(body,'$.session_id')=? "
            "OR json_extract(body,'$.chat_id')=?) LIMIT 1", (query["session_id"], query["chat_id"])).fetchone()
        require(occupied is None, "原生会话已经承接其他事项或原意图", web.HTTPConflict)
        return session.created_at.isoformat()

    def bind(self, role, payload):
        owner_role(role)
        validate("TaskEntryBind", payload)
        query = self._context({"chat_id": payload["chat_id"], "session_id": webui_session_key(payload["chat_id"])})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            row = self.store.get(db, context["namespace"], PREPARATION, payload["preparation_id"])
            self._scope(row, context)
            require(row["client_request_id"] == payload["client_request_id"] and row["preparation_sha256"] == payload["preparation_sha256"],
                    "任务会话绑定与本次原选择不符", web.HTTPConflict)
            self._current(db, context, row)
            existing = optional(db, context["namespace"], BINDING, query["session_id"])
            if row["binding_state"] == "BOUND":
                require(row["bind_payload_sha256"] == checksum(payload) and row["context"] == query
                        and existing is not None and existing["preparation_id"] == row["preparation_id"],
                        "原准备已经绑定其他会话或选择", web.HTTPConflict)
                return self._view(row, True)
            require(existing is None, "当前原生会话已经绑定其他任务选择", web.HTTPConflict)
            native_created_at = self._unused_session(db, query)
            row.update(binding_state="BOUND", context=query, bound_at=now(), bind_payload_sha256=checksum(payload))
            self.store.put(db, context["namespace"], BINDING, query["session_id"], {
                **{field: context[field] for field in IDENTITY}, **query,
                "preparation_id": row["preparation_id"], "preparation_sha256": row["preparation_sha256"], "native_session_created_at": native_created_at})
            self.store.put(db, context["namespace"], PREPARATION, row["preparation_id"], row)
            return self._view(row, True)

    def read(self, role, query):
        owner_role(role)
        self._context(query)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            binding = optional(db, context["namespace"], BINDING, query["session_id"])
            row = None
            if binding is not None:
                require(all(binding[field] == context[field] for field in IDENTITY) and all(binding[field] == query[field] for field in query),
                        "任务会话绑定不属于当前会话及资料范围", web.HTTPForbidden)
                row = self.store.get(db, context["namespace"], PREPARATION, binding["preparation_id"])
                self._current(db, context, row)
                require(row["binding_state"] == "BOUND" and row["context"] == query and row["preparation_sha256"] == binding["preparation_sha256"],
                        "任务会话固定选择与原绑定不符", web.HTTPConflict)
            references = [row["task_reference"], *[{key: ref[key] for key in ("kind", "id", "version")} for ref in row["source_references"]]] if row else []
            return validate("TaskEntryContext", {"source_type": "RUNTIME_RECORD", **query,
                "binding_state": "BOUND" if row else "UNBOUND", "entry": self._view(row, True) if row else None,
                "references": references, "current_use_verified": row is not None,
                "business_authorization_granted": False, "business_mutation_performed": False})

    def receipt(self, role, payload):
        owner_role(role)
        validate("TaskEntryReceiptInput", payload)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            row = optional(db, context["namespace"], PREPARATION, self._request_id(payload["client_request_id"]))
            if row is not None:
                self._scope(row, context)
            return validate("TaskEntryReceipt", {"source_type": "RUNTIME_RECORD", **payload,
                "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "entry": self._view(row, False) if row else None,
                "business_authorization_granted": False, "business_mutation_performed": False})
