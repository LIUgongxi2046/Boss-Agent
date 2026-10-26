import json

from nanobot.agent.autocompact import AutoCompact
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META, detach_runtime_context
from nanobot.session.manager import SessionManager

from business import now, require
from boss_execution_scope import NAMESPACE
from boss_memory_runtime import memory_adoption, memory_context_source


ADOPTION_KEY = "boss_memory_adoption"


class MemoryAutoCompact(AutoCompact):
    def invalidate_memory_context(self, key):
        self._summaries.pop(key, None)


class MemorySessionManager(SessionManager):
    def __init__(self, workspace, *, business_store, namespace=NAMESPACE, sessions_root=None):
        super().__init__(workspace, sessions_root=sessions_root)
        self.business_store = business_store
        self.namespace = namespace
        self.invalidate_context = None

    def _sanitize(self, session):
        with self.business_store.connect() as db:
            db.execute("BEGIN")
            self.business_store.active(db, self.namespace)
            reference, _ = memory_adoption(self.business_store, db, self.namespace)
            running = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='runtime_run' "
                "AND json_extract(body,'$.session_id')=? "
                "AND json_extract(body,'$.status') IN ('QUEUED','RUNNING')",
                (self.namespace, session.key),
            )]
        source = memory_context_source(reference)
        previous = session.metadata.get(ADOPTION_KEY)
        invalid = previous is not None and previous != source
        invalid = invalid or any(
            row.get("memory_reference") and row["memory_reference"].get("eligible") is True
            and memory_context_source(row["memory_reference"]) != source for row in running
        )
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
        return changed

    def get_or_create(self, key):
        session = super().get_or_create(key)
        if self._sanitize(session) and session.messages:
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

    def reconcile_memory(self):
        with self.business_store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            reference, _ = memory_adoption(self.business_store, db, self.namespace)
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
