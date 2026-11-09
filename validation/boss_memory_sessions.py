import json
from pathlib import Path

from nanobot.agent.autocompact import AutoCompact
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META, detach_runtime_context
from nanobot.session.manager import SessionManager

from business import checksum, now, require
from boss_execution_scope import NAMESPACE
from boss_memory_runtime import memory_adoption, memory_context_source
from boss_source_policy import source_validity
from boss_supply_quality import external_adoption


ADOPTION_KEY = "boss_memory_adoption"


class MemoryAutoCompact(AutoCompact):
    def invalidate_memory_context(self, key):
        self._summaries.pop(key, None)


class MemorySessionManager(SessionManager):
    def __init__(self, workspace, *, business_store, namespace=NAMESPACE, sessions_root=None, legacy_sessions_root=None):
        if legacy_sessions_root is None:
            super().__init__(workspace, sessions_root=sessions_root)
        else:
            super().__init__(workspace, sessions_root=sessions_root, legacy_sessions_root=legacy_sessions_root)
        self.business_store = business_store
        self.namespace = namespace
        self.invalidate_context = None

    def _sanitize(self, session):
        with self.business_store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.business_store.active(db, self.namespace)
            reference, _ = memory_adoption(self.business_store, db, self.namespace)
            self._invalidate_adoptions(db)
            running = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='runtime_run' "
                "AND json_extract(body,'$.session_id')=? "
                "AND json_extract(body,'$.status') IN ('QUEUED','RUNNING')",
                (self.namespace, session.key),
            )]
            invalidations = [row[0] for row in db.execute(
                "SELECT id FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' "
                "AND json_extract(body,'$.session_id')=? ORDER BY id", (self.namespace, session.key),
            )]
        source = memory_context_source(reference)
        previous = session.metadata.get(ADOPTION_KEY)
        invalid = previous is not None and previous != source
        invalid = invalid or any(
            row.get("memory_reference") and row["memory_reference"].get("eligible") is True
            and memory_context_source(row["memory_reference"]) != source for row in running
        )
        invalidation_marker = checksum(invalidations) if invalidations else None
        if invalidation_marker is not None and session.metadata.get("boss_hermes_invalidation") != invalidation_marker:
            invalid = True
        changed = previous != source
        for message in session.messages:
            marker = message.get(RUNTIME_CONTEXT_HISTORY_META)
            if marker is None:
                continue
            require(isinstance(marker, dict) and isinstance(marker.get("sources"), list),
                    "会话Runtime上下文标记无法核查")
            sources = marker["sources"]
            require(all(isinstance(value, str) for value in sources), "会话Runtime来源格式无效")
            memory_sources = [value for value in sources
                              if value == "boss-confirmed-memory" or value.startswith("boss-confirmed-memory:")]
            if not memory_sources or memory_sources == [source]:
                continue
            detached = detach_runtime_context(message.get("content"), marker)
            require(detached is not None, "会话Runtime正文与保存标记不符")
            message["content"] = detached[0]
            del message[RUNTIME_CONTEXT_HISTORY_META]
            invalid = changed = True
        if previous is None and (session.provider_state is not None or "_last_summary" in session.metadata):
            invalid = changed = True
        if invalid:
            session.last_archived = len(session.messages)
            session.provider_state = None
            session.metadata.pop("_last_summary", None)
            session.metadata.pop("runtime_checkpoint", None)
            session.metadata["boss_memory_replay"] = {
                "state": "PRIOR_CONTEXT_EXCLUDED", "at": now(), "boundary": len(session.messages),
                "memory_id": reference["memory_id"] if reference else None,
                "memory_version": reference["version"] if reference else None,
            }
            if self.invalidate_context is not None:
                self.invalidate_context(session.key)
            changed = True
        session.metadata[ADOPTION_KEY] = source
        if invalidation_marker is not None:
            session.metadata["boss_hermes_invalidation"] = invalidation_marker
        return changed

    def get_or_create(self, key):
        session = super().get_or_create(key)
        if self._sanitize(session) and (session.messages or self.read_session_snapshot(key) is not None):
            super().save(session, fsync=True)
        return session

    def save(self, session, *, fsync=False):
        self._sanitize(session)
        super().save(session, fsync=fsync)

    def save_runtime_checkpoint(self, session):
        if self._sanitize(session):
            super().save(session, fsync=True)
        else:
            super().save_runtime_checkpoint(session)

    def _invalidate_adoptions(self, db):
        reference, eligible = memory_adoption(self.business_store, db, self.namespace)
        initial = self.business_store.get(db, self.namespace, "initial", "snapshot")
        clock = self.business_store.get(db, self.namespace, "clock", "current")["at"]
        adoptions = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='hermes_memory_adoption'", (self.namespace,)).fetchall()
        for run_id, body in adoptions:
            marker = json.loads(body)
            record = db.execute("SELECT conversation_id,scope_proof FROM agent_runs WHERE run_id=? AND actor_id=? AND space_id=?", (run_id, initial["owner_id"], self.namespace)).fetchone()
            proof = json.loads(record[1]) if record is not None and record[1] is not None else None
            invalid = marker.get("owner_id") != initial["owner_id"] or marker.get("namespace") != self.namespace or marker.get("dataset_id") != initial["dataset_id"] or marker.get("dataset_version") != initial["dataset_version"]
            invalid = invalid or marker.get("memory_reference") != reference or marker.get("content_sha256") != (checksum(eligible) if eligible is not None else None)
            invalid = invalid or proof is None or record[0] != marker.get("conversation_id") or checksum(proof) != marker.get("scope_sha256")
            if proof is not None:
                session = self.read_session_snapshot(proof["session_id"])
                invalid = invalid or session is None or session.key != proof["session_id"] or session.created_at.isoformat() != proof["native_session_created_at"]
                row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='conversation_source_binding' AND id=?", (self.namespace, proof["session_id"])).fetchone()
                binding = json.loads(row[0]) if row is not None else None
                if binding is None:
                    invalid = invalid or proof["binding_id"] is not None or proof["context_version"] is not None or bool(proof["source_pins"])
                else:
                    invalid = invalid or binding["binding_id"] != proof["binding_id"] or binding["context_version"] != proof["context_version"] or binding["native_session_created_at"] != proof["native_session_created_at"]
                    selected = {pin[0] for pin in proof["source_pins"]}
                    pins = [[pin["source_id"], pin["version"], pin["content_sha256"]] for pin in binding["source_pins"] if pin["source_id"] in selected]
                    invalid = invalid or pins != proof["source_pins"]
                for source_id, version, digest in proof["source_pins"]:
                    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?", (self.namespace, source_id)).fetchone()
                    document = json.loads(row[0]) if row is not None else None
                    invalid = invalid or document is None or document.get("source_id") != source_id or document.get("version") != version or document.get("access_scope") != initial["owner_id"] or document.get("source_type") != "SIMULATED" or checksum(document) != digest or source_validity(document, clock) != "VALID" or external_adoption(db, self.namespace, initial, clock, document)["state"] == "NEEDS_REIMPORT"
            if invalid:
                session_id = "websocket:" + marker["conversation_id"]
                db.execute("INSERT OR IGNORE INTO objects VALUES(?,?,?,?)", (self.namespace, "hermes_memory_invalidation", run_id,
                    json.dumps({"run_id": run_id, "session_id": session_id, "reason": "MEMORY_OR_SOURCE_CHANGED", "at": now()}, ensure_ascii=False)))

    def source_withdrawn_in_transaction(self, db, source_id):
        if not db.in_transaction or not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("来源撤销传播参数无效")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.business_store.path.resolve():
            raise ValueError("来源撤销传播数据库不匹配")
        self.business_store.active(db, self.namespace)
        document = self.business_store.get(db, self.namespace, "document", source_id)
        initial = self.business_store.get(db, self.namespace, "initial", "snapshot")
        clock = self.business_store.get(db, self.namespace, "clock", "current")["at"]
        if document.get("source_id") != source_id or document.get("access_scope") != initial["owner_id"] or document.get("source_type") != "SIMULATED" or source_validity(document, clock) != "WITHDRAWN":
            raise ValueError("当前来源未撤销或不属于当前空间")
        self._invalidate_adoptions(db)

    def source_withdrawn(self, source_id):
        with self.business_store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.source_withdrawn_in_transaction(db, source_id)
        return self._reconcile_sessions()

    def reconcile_memory(self):
        with self.business_store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            reference, _ = memory_adoption(self.business_store, db, self.namespace)
            self._invalidate_adoptions(db)
            identifier = reference["memory_id"] if reference else None
            row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='memory_deletion' AND id=?",
                             (self.namespace, identifier)).fetchone()
            propagation = json.loads(row[0]) if row else None
            if propagation is not None:
                propagation.update(loaded_sessions="IN_PROGRESS", failure_reason=None)
                self.business_store.put(db, self.namespace, "memory_deletion", identifier, propagation)
        completed = False
        try:
            result = self._reconcile_sessions()
            completed = True
            return result
        finally:
            if propagation is not None and not completed:
                with self.business_store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    propagation = self.business_store.get(db, self.namespace, "memory_deletion", identifier)
                    propagation.update(loaded_sessions="FAILED", failure_reason="会话上下文清理未完成")
                    self.business_store.put(db, self.namespace, "memory_deletion", identifier, propagation)

    def _reconcile_sessions(self):
        keys = {item["key"] for item in self.list_sessions()}
        keys.update(self._cache)
        keys.update(self._overflow_cache)
        changed = 0
        for key in sorted(keys):
            session = super().get_or_create(key)
            if self._sanitize(session):
                super().save(session, fsync=True)
                changed += 1
        with self.business_store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            reference, _ = memory_adoption(self.business_store, db, self.namespace)
            if reference is not None:
                row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='memory_deletion' AND id=?",
                                 (self.namespace, reference["memory_id"])).fetchone()
                if row is not None:
                    propagation = json.loads(row[0])
                    propagation.update(loaded_sessions="NATIVE_REPLAY_AND_CONTEXT_CLEARED",
                                       sessions_checked=len(keys), sessions_changed=changed, sessions_checked_at=now())
                    self.business_store.put(db, self.namespace, "memory_deletion", reference["memory_id"], propagation)
        return {"sessions_checked": len(keys), "sessions_changed": changed}
