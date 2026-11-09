import hashlib
import json
from functools import lru_cache
from pathlib import Path

from agent_artifact_api import propagate_withdrawn_source_in_transaction
from boss_simulation_api import _context


ARTIFACT_TABLES = {
    "agent_artifacts": "upgrade2_001",
    "agent_artifact_versions": "upgrade2_001",
    "agent_artifact_pending": "upgrade2_001",
    "agent_artifact_revocations": "upgrade2_001",
    "agent_artifact_publications": "upgrade2_001",
    "agent_task_artifact_refs": "upgrade2_001",
    "agent_file_reservations": "upgrade2_001",
    "agent_file_budgets": "upgrade2_001",
    "agent_artifact_goals": "upgrade2_artifact_goal_001",
    "agent_artifact_briefs": "upgrade2_artifact_brief_001",
    "agent_artifact_brief_cleanup": "upgrade2_artifact_brief_cleanup_001",
}


@lru_cache(maxsize=1)
def migration_catalog():
    from agent_simulation_migration_install import _catalog
    return {version: (digest, objects) for version, _, _, digest, objects in _catalog()}


def _object_present(db, kind, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type=? AND name=?", (kind, name)).fetchone() is not None


def artifact_schema_state_in_transaction(db):
    catalog = migration_catalog()
    ledger = _object_present(db, "table", "agent_schema_migrations")
    registered = {version: digest for version, digest in db.execute("SELECT version,sha256 FROM agent_schema_migrations").fetchall()} if ledger else {}
    present_tables = {table for table in ARTIFACT_TABLES if _object_present(db, "table", table)}
    for table in present_tables:
        version = ARTIFACT_TABLES[table]
        if version not in catalog or registered.get(version) != catalog[version][0]:
            raise ValueError("成果升级表状态不可核查")
    for version in set(ARTIFACT_TABLES.values()):
        tables = {table for table, owner in ARTIFACT_TABLES.items() if owner == version}
        if version not in registered:
            if tables & present_tables:
                raise ValueError("成果升级表状态不可核查")
            continue
        if version not in catalog or registered[version] != catalog[version][0] or not tables.issubset(present_tables):
            raise ValueError("成果升级表状态不可核查")
    cleanup_version = "upgrade2_artifact_brief_cleanup_001"
    if cleanup_version in registered:
        for (kind, name), sql in catalog[cleanup_version][1].items():
            if db.execute("SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind, name)).fetchone() != (sql,):
                raise ValueError("会议简报清理迁移对象不可核查")
        original_update = catalog["upgrade2_artifact_brief_001"][1][("trigger", "agent_artifact_briefs_no_update")]
        if db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='agent_artifact_briefs_no_update'").fetchone() != (original_update,):
            raise ValueError("会议简报不可变约束不可核查")
    base_digest, base_objects = catalog["upgrade2_001"]
    present_base = [key for key in base_objects if _object_present(db, *key)]
    if "upgrade2_001" not in registered:
        if present_base or present_tables:
            raise ValueError("成果升级表状态不可核查")
        return "NOT_INSTALLED"
    if registered["upgrade2_001"] != base_digest or len(present_base) != len(base_objects):
        raise ValueError("成果升级表状态不可核查")
    return "INSTALLED"


def require_source_withdrawal_in_transaction(store, db, source_id):
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("来源编号无效")
    main = db.execute("PRAGMA database_list").fetchone()
    if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != store.path.resolve():
        raise ValueError("来源撤销传播需要同一业务数据库事务")
    context = _context(db)
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?", (context["namespace"], source_id)).fetchone()
    if row is None:
        raise ValueError("来源文档不存在")
    document = json.loads(row[0])
    if document.get("withdrawn") is not True and document.get("validity_state") != "WITHDRAWN":
        raise ValueError("来源尚未撤销")
    events = []
    for identifier, body in db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", (context["namespace"],)).fetchall():
        event = json.loads(body)
        if not isinstance(event, dict):
            raise ValueError("来源撤销事件不可核查")
        if event.get("source_id") != source_id:
            continue
        if (event.get("event_id") != identifier or event.get("namespace") != context["namespace"]
                or event.get("result") != "WITHDRAWN" or event.get("withdrawn_version") != document.get("version")
                or event.get("withdrawn_at") != document.get("withdrawn_at")):
            raise ValueError("来源撤销事件不可核查")
        events.append(event)
    if len(events) != 1:
        raise ValueError("来源撤销事件不唯一")
    return events[0]


def cleanup_withdrawn_briefs_in_transaction(store, db, source_id, event):
    if not _object_present(db, "table", "agent_artifact_briefs"):
        return []
    from business import checksum
    from agent_run_store import utc_now
    context = _context(db)
    scope = {key: context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")}
    rows = db.execute("SELECT b.artifact_id,b.snapshot,b.snapshot_sha256,f.run_id,f.status,r.actor_id,r.space_id,r.conversation_id,r.scope_proof,a.status,a.source_refs,a.context,p.content,p.sha256,p.source_refs,p.context,v.previous_artifact_id FROM agent_artifact_briefs b JOIN agent_file_reservations f ON f.artifact_id=b.artifact_id JOIN agent_runs r ON r.run_id=f.run_id JOIN agent_artifact_versions v ON v.artifact_id=b.artifact_id LEFT JOIN agent_artifacts a ON a.artifact_id=b.artifact_id LEFT JOIN agent_artifact_pending p ON p.artifact_id=b.artifact_id WHERE r.actor_id=? AND r.space_id=?", (scope["owner_id"], scope["namespace"])).fetchall()
    cleaned = []
    for artifact_id, raw_snapshot, digest, run_id, reservation, owner, space, conversation, raw_proof, artifact_status, artifact_refs, artifact_scope, pending_content, pending_digest, pending_refs, pending_scope, previous in rows:
        snapshot = json.loads(raw_snapshot)
        if not isinstance(snapshot, dict) or checksum(snapshot) != digest or snapshot.get("run_id") != run_id or not isinstance(snapshot.get("source_refs"), list):
            raise ValueError("会议简报快照不可核查")
        direct = any(isinstance(ref, dict) and ref.get("source_id") == source_id for ref in snapshot["source_refs"])
        revoked = db.execute("SELECT reason,source_id FROM agent_artifact_revocations WHERE artifact_id=?", (artifact_id,)).fetchone()
        ancestor = db.execute("SELECT reason,source_id FROM agent_artifact_revocations WHERE artifact_id=?", (previous,)).fetchone() if previous else None
        if not direct and revoked != ("SOURCE_WITHDRAWN", source_id) and ancestor != ("SOURCE_WITHDRAWN", source_id):
            continue
        proof = json.loads(raw_proof) if raw_proof is not None else None
        if (owner, space) != (scope["owner_id"], scope["namespace"]) or not isinstance(proof, dict) or any(proof.get(key) != scope[key] for key in scope) or proof.get("chat_id") != conversation:
            raise ValueError("会议简报清理范围不可核查")
        if reservation == "COMPLETED":
            valid = artifact_status == "REVOKED" and revoked is not None and artifact_refs is not None and json.loads(artifact_refs) == snapshot["source_refs"] and json.loads(artifact_scope) == scope and pending_refs is None
        elif reservation == "RESERVED":
            valid = artifact_status is None and pending_content == b"" and pending_digest == hashlib.sha256(b"").hexdigest() and pending_refs is not None and json.loads(pending_refs) == snapshot["source_refs"] and json.loads(pending_scope) == scope
        else:
            valid = False
        if not valid:
            raise ValueError("会议简报清理状态不可核查")
        if not _object_present(db, "table", "agent_artifact_brief_cleanup"):
            raise ValueError("会议简报清理迁移尚未安装")
        db.execute("INSERT INTO agent_artifact_brief_cleanup VALUES (?,?,?,?,?)", (artifact_id, run_id, source_id, event["event_id"], utc_now().isoformat()))
        if db.execute("DELETE FROM agent_artifact_briefs WHERE artifact_id=?", (artifact_id,)).rowcount != 1:
            raise ValueError("会议简报快照清理不可核查")
        cleaned.append(artifact_id)
    return cleaned


def propagate_domain_source_withdrawal_in_transaction(store, db, source_id):
    event = require_source_withdrawal_in_transaction(store, db, source_id)
    schema_state = artifact_schema_state_in_transaction(db)
    if schema_state == "NOT_INSTALLED":
        return {"source_id": source_id, "event_id": event["event_id"], "affected": [], "artifact_state": "NOT_INSTALLED"}
    affected = propagate_withdrawn_source_in_transaction(store, db, source_id)
    cleanup_withdrawn_briefs_in_transaction(store, db, source_id, event)
    return {"source_id": source_id, "event_id": event["event_id"], "affected": affected, "artifact_state": "PROPAGATED"}
