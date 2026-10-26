import json
from pathlib import Path

from aiohttp import web
from jsonschema import Draft202012Validator
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key

from business import checksum, now, require
from boss_conversation import optional, owner_role
from boss_simulation_api import _context
from boss_source_access import require_current_business_source
from boss_source_policy import source_validity
from boss_supply_quality import external_adoption

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "specs/conversation-sources.schema.json").read_text())
BINDING = "conversation_source_binding"
RECEIPT = "conversation_source_receipt"
IDENTITY = ("namespace", "owner_id", "dataset_id", "dataset_version")
FLAGS = {"business_authorization_granted": False, "business_mutation_performed": False}


def validate(name, value):
    require(not list(Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}).iter_errors(value)),
            "会话资料输入输出不符合Schema", web.HTTPBadRequest)
    return value


class ConversationSources:
    def __init__(self, store, sessions):
        require(sessions is not None, "资料选择需要实际原生会话服务", web.HTTPServiceUnavailable)
        self.store, self.sessions = store, sessions

    def _session(self, db, context, chat_id, *, require_existing=True):
        require(is_valid_webui_chat_id(chat_id), "原生会话编号无效", web.HTTPBadRequest)
        session_id = webui_session_key(chat_id)
        other = db.execute("SELECT 1 FROM objects WHERE namespace<>? AND kind IN "
            "('conversation_source_binding','conversation_task_binding','conversation_business_binding','morning_native_binding','conversation_intent','runtime_run') "
            "AND (json_extract(body,'$.session_id')=? OR json_extract(body,'$.chat_id')=?) LIMIT 1",
            (context["namespace"], session_id, chat_id)).fetchone()
        require(other is None, "会话属于其他资料空间，请使用当前空间会话", web.HTTPForbidden)
        session = self.sessions.read_session_snapshot(session_id)
        require(not require_existing or session is not None, "当前原生会话尚未创建", web.HTTPNotFound)
        require(session is None or session.key == session_id, "原生会话身份不符", web.HTTPConflict)
        return {"chat_id": chat_id, "session_id": session_id, "native_session_created_at": session.created_at.isoformat() if session else None}

    def _binding(self, db, context, session):
        row = optional(db, context["namespace"], BINDING, session["session_id"])
        if row is not None:
            require(all(row[field] == context[field] for field in IDENTITY)
                    and all(row[field] == value for field, value in session.items()), "资料选择不属于当前本人会话实例", web.HTTPConflict)
        return row

    def _catalogue(self, db, context):
        ns = context["namespace"]
        initial = self.store.get(db, ns, "initial", "snapshot")
        clock = self.store.get(db, ns, "clock", "current")["at"]
        documents = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' "
            "AND json_extract(body,'$.access_scope')=? ORDER BY id", (ns, context["owner_id"]))]
        sources, digests = [], []
        for document in documents:
            state = source_validity(document, clock)
            adoption = external_adoption(db, ns, initial, clock, document)
            index = db.execute("SELECT content FROM knowledge_text WHERE namespace=? AND source_id=?", (ns, document["source_id"])).fetchall()
            indexed = len(index) == 1 and isinstance(document.get("content"), str) and index[0][0] == document["content"]
            reason = "资料当前状态：" + state if state != "VALID" else "来源依赖已经变化" if adoption["state"] == "NEEDS_REIMPORT" else "原文索引尚未核查" if not indexed else "当前来源种类尚未接入业务读取" if document["source_type"] != "SIMULATED" else None
            sources.append({"source_id": document["source_id"], "version": document["version"], "title": document.get("title") or document["source_id"],
                "source_type": document["source_type"], "author": document.get("author_display_name") or document.get("author_contact_id"),
                "published_at": document.get("published_at"), "validity_state": state, "allowed": reason is None, "reason": reason})
            digests.append({"source": checksum(document), "adoption": adoption, "indexed": indexed, "state": state})
        return sources, checksum({"identity": {key: context[key] for key in IDENTITY}, "sources": digests})

    @staticmethod
    def _running(db, context, session):
        return db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind IN ('conversation_intent','runtime_run','morning_public_request') "
            "AND json_extract(body,'$.session_id')=? AND json_extract(body,'$.status') IN ('ADMITTED','PREPARED','QUEUED','RUNNING') "
            "AND json_extract(body,'$.finished_at') IS NULL LIMIT 1", (context["namespace"], session["session_id"])).fetchone() is not None

    def listing(self, role, payload):
        owner_role(role)
        validate("ListInput", payload)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            session = self._session(db, context, payload["chat_id"], require_existing=False)
            binding = self._binding(db, context, session)
            sources, digest = self._catalogue(db, context)
            query = payload["query"]
            if query:
                pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                matches = {row[0] for row in db.execute("SELECT source_id FROM knowledge_text WHERE namespace=? AND content LIKE ? ESCAPE '\\'", (context["namespace"], pattern))}
                sources = [source for source in sources if source["source_id"] in matches or query.casefold() in source["title"].casefold() or query.casefold() in source["source_id"].casefold()]
            running = self._running(db, context, session)
            return validate("Catalogue", {"projection": "conversation-sources", "chat_id": payload["chat_id"], "session_id": session["session_id"],
                "execution_namespace": context["namespace"], "dataset_version": context["dataset_version"], "context_version": binding["context_version"] if binding else "0",
                "catalogue_version": digest, "query": query, "sources": sources, "selected_sources": binding["source_refs"] if binding else [],
                "coverage": "COMPLETE", "can_bind": not running, "unavailable_reason": "当前会话正在执行，请在运行结束后选择资料" if running else None, **FLAGS})

    def bind(self, role, payload, *, active):
        owner_role(role)
        require(callable(active) and active(), "当前会话资料认证已经失效", web.HTTPUnauthorized)
        validate("BindInput", payload)
        request_id = payload["client_request_id"]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            session = self._session(db, context, payload["chat_id"])
            identifier = "source-selection-" + checksum({"request": request_id})
            recorded = optional(db, context["namespace"], RECEIPT, identifier)
            if recorded is not None:
                require(all(recorded[field] == context[field] for field in IDENTITY) and recorded["payload_sha256"] == checksum(payload), "原资料请求已经用于其他选择", web.HTTPConflict)
                return validate("Receipt", recorded["result"])
            binding = self._binding(db, context, session)
            sources, catalogue_version = self._catalogue(db, context)
            source_map = {source["source_id"]: source for source in sources}
            version = binding["context_version"] if binding else "0"
            refs = payload["source_refs"]
            invalid_refs = len({ref["source_id"] for ref in refs}) != len(refs) or any(ref["source_id"] not in source_map or not source_map[ref["source_id"]]["allowed"] or source_map[ref["source_id"]]["version"] != ref["version"] for ref in refs)
            reason = "资料空间或资料集已经变化" if payload["execution_namespace"] != context["namespace"] or payload["dataset_version"] != context["dataset_version"] else "会话资料选择版本已经变化" if payload["expected_context_version"] != version else "资料目录版本已经变化" if payload["expected_catalogue_version"] != catalogue_version else "当前会话仍在执行" if self._running(db, context, session) else "所选资料缺少、重复或当前不可采用" if invalid_refs else None
            result = {"client_request_id": request_id, "chat_id": payload["chat_id"], "session_id": session["session_id"], "outcome": "REJECTED" if reason else "RECORDED", **FLAGS}
            if reason:
                result["reason"] = reason
            else:
                pins = [{**ref, "content_sha256": checksum(require_current_business_source(self.store, db, context["namespace"], context["owner_id"], ref["source_id"]))} for ref in refs]
                row = {**{field: context[field] for field in IDENTITY}, **session, "binding_id": identifier, "context_version": str(int(version) + 1),
                    "source_refs": refs, "source_pins": pins, "bound_at": now(), "client_request_id": request_id}
                self.store.put(db, context["namespace"], BINDING, session["session_id"], row)
                self.store.put(db, context["namespace"], "conversation_source_revision", identifier, row)
                result.update(binding_id=identifier, context_version=row["context_version"], source_refs=refs)
            validate("Receipt", result)
            self.store.put(db, context["namespace"], RECEIPT, identifier, {**{field: context[field] for field in IDENTITY},
                "payload_sha256": checksum(payload), "result": result, "recorded_at": now()})
            require(active(), "保存资料选择期间本人认证或会话已经变化", web.HTTPUnauthorized)
            return result

    def receipt(self, role, payload):
        owner_role(role)
        validate("ReceiptInput", payload)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            session = self._session(db, context, payload["chat_id"], require_existing=False)
            row = optional(db, context["namespace"], RECEIPT, "source-selection-" + checksum({"request": payload["client_request_id"]}))
            if row is not None:
                require(all(row[field] == context[field] for field in IDENTITY) and row["result"]["chat_id"] == payload["chat_id"], "原资料回执不属于当前本人会话", web.HTTPForbidden)
            result = row["result"] if row else {**payload, "session_id": session["session_id"], "outcome": "UNKNOWN", **FLAGS}
            return validate("Receipt", {**result, "write_performed_by_lookup": False})

    def pin(self, chat_id):
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            session_id = webui_session_key(chat_id)
            row = optional(db, context["namespace"], BINDING, session_id)
            if row is None:
                return None
            session = self._session(db, context, chat_id)
            row = self._binding(db, context, session)
            for ref in row["source_pins"]:
                document = require_current_business_source(self.store, db, context["namespace"], context["owner_id"], ref["source_id"])
                require(document["version"] == ref["version"] and checksum(document) == ref["content_sha256"], "本会话所选来源已经变化，请重新选择资料", web.HTTPConflict)
            return {key: row[key] for key in ("binding_id", "context_version", "source_refs", "source_pins", "native_session_created_at")}
