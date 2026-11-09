import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from filelock import FileLock

from agent_run_scope import RunScopeService
from agent_run_store import RunStore, utc_now
from boss_memory_runtime import memory_adoption
from boss_simulation_api import _context
from business import checksum
from controls import ControlStore


VERSION = "upgrade2_legacy_inventory_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentLegacyInventory:
    def __init__(self, store, scope, *, allow_migration=False):
        if not isinstance(store, ControlStore) or not isinstance(scope, RunScopeService) or store.path.resolve() != scope.store.path.resolve():
            raise ValueError("会话范围与业务数据库不匹配")
        self.store = store
        self.scope = scope
        RunStore(store.path, allow_migration=False)
        source = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("历史清单迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_legacy_inventory'").fetchone() is not None:
                raise ValueError("历史清单迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def _require_transaction(self, db):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("历史清单需要同一业务数据库事务")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (digest,):
            raise ValueError("历史清单迁移摘要不符")
        context = _context(db)
        if context["namespace"] != self.scope.namespace:
            raise ValueError("历史清单空间已经变化")
        return context

    def _record(self, db, namespace, record_type, record_id, metadata):
        encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        row = db.execute("SELECT source_digest,metadata_json FROM agent_legacy_inventory WHERE namespace=? AND record_type=? AND record_id=?", (namespace, record_type, record_id)).fetchone()
        if row is not None:
            if row != (digest, encoded):
                raise ValueError("历史记录内容或当前范围已经变化")
            return {"metadata": metadata, "source_digest": digest, "created": False}
        db.execute("INSERT INTO agent_legacy_inventory VALUES (?,?,?,?,?,?)", (namespace, record_type, record_id, digest, encoded, utc_now().isoformat()))
        return {"metadata": metadata, "source_digest": digest, "created": True}

    def session_in_transaction(self, db, chat_id, selected_refs):
        context = self._require_transaction(db)
        proof = self.scope.prove_in_transaction(db, chat_id, selected_refs)
        session = self.scope.sources.sessions.read_session_snapshot(proof.session_id)
        if session is None or session.created_at.isoformat() != proof.native_session_created_at:
            raise ValueError("历史会话已经变化")
        reference, _ = memory_adoption(self.store, db, context["namespace"])
        invalidations = db.execute("SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN ('hermes_source_cleanup','memory_deletion','hermes_memory_invalidation') ORDER BY kind,id", (context["namespace"],)).fetchall()
        metadata = {"engine": "nanobot", "scope": asdict(proof), "message_count": len(session.messages),
                    "messages_sha256": checksum(session.messages), "memory_reference_sha256": checksum(reference),
                    "invalidations_sha256": checksum(invalidations)}
        return self._record(db, context["namespace"], "SESSION", proof.session_id, metadata)

    def plan_in_transaction(self, db, plan_id):
        context = self._require_transaction(db)
        plan = self.store.get(db, context["namespace"], "owner_plan", plan_id)
        if plan.get("plan_id") != plan_id or plan.get("owner_id") != context["owner_id"] or plan.get("source_type") != "SIMULATED" or not isinstance(plan.get("version"), str):
            raise ValueError("本人计划身份或版本不可核查")
        event_ids = plan.get("event_ids")
        versions = plan.get("event_versions")
        if not isinstance(event_ids, list) or len(event_ids) != len(set(event_ids)) or not isinstance(versions, dict) or set(event_ids) != set(versions):
            raise ValueError("本人计划事件关联不可核查")
        events = []
        for event_id in event_ids:
            event = self.store.get(db, context["namespace"], "event", event_id)
            if event.get("owner_plan_id") != plan_id or event.get("version") != versions[event_id]:
                raise ValueError("本人计划事件版本已经变化")
            events.append(event)
        schedule = self.store.get(db, context["namespace"], "schedule", "current")
        receipts = db.execute("SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN ('notification','dispatch','dispatch_history') AND json_extract(body,'$.owner_plan_id')=? ORDER BY kind,id", (context["namespace"], plan_id)).fetchall()
        metadata = {"owner_id": context["owner_id"], "namespace": context["namespace"], "dataset_id": context["dataset_id"],
                    "dataset_version": context["dataset_version"], "plan_id": plan_id, "plan_version": plan["version"],
                    "plan_sha256": checksum(plan), "event_count": len(events), "events_sha256": checksum(events),
                    "schedule_sha256": checksum(schedule), "receipt_count": len(receipts), "receipts_sha256": checksum(receipts), "activation": "DISABLED"}
        return self._record(db, context["namespace"], "PLAN", plan_id, metadata)
