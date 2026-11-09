import hashlib
import json
from pathlib import Path

from boss_execution_transition import pending_transition
from boss_memory_runtime import memory_adoption
from boss_simulation_api import _context
from controls import ControlStore
from agent_memory_deletion_log import inspect_memory_deletion_history_in_transaction
from hermes_source_invalidation import verify_source_withdrawals_in_transaction


ARTIFACT_STATE = (
    ("agent_artifact_versions", ("series_id", "version", "previous_artifact_id")),
    ("agent_artifact_revocations", ("reason", "source_id", "revoked_at")),
    ("agent_artifact_publications", ("run_id", "version", "sha256", "actor_id", "published_at")),
    ("agent_artifact_goals", ("run_id", "goal_revision", "goal_sha256", "scope_sha256", "event_id")),
    ("agent_artifact_briefs", ("snapshot_sha256",)),
    ("agent_artifact_brief_cleanup", ("run_id", "source_id", "withdrawal_event_id", "cleaned_at")),
    ("agent_file_reservations", ("root_run_id", "run_id", "request_key", "size_bytes", "status")),
)


def inspect_deletion_evidence_readonly(db, namespace):
    if not db.in_transaction or not isinstance(namespace, str) or not namespace:
        raise ValueError("删除记录核查需要数据库事务和执行空间")
    names = ("objects", "audit", "idempotency")
    schema = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name IN (?,?,?)", names).fetchall())
    if set(schema) != set(names) or any(not isinstance(value, str) or not value for value in schema.values()):
        raise ValueError("删除记录依赖表不可核查")
    events = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event' ORDER BY id", (namespace,)).fetchall()
    parsed = []
    for identifier, body in events:
        event = json.loads(body)
        if not isinstance(event, dict) or event.get("event_id") != identifier or event.get("namespace") != namespace or type(event.get("sequence")) is not int or event["sequence"] < 1 or not isinstance(event.get("source_id"), str) or not event["source_id"]:
            raise ValueError("来源撤销记录不可核查")
        parsed.append(event)
    if sorted(item["sequence"] for item in parsed) != list(range(1, len(parsed) + 1)):
        raise ValueError("来源撤销记录序号不连续")
    documents = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='document'", (namespace,)).fetchall()
    withdrawn = set()
    for identifier, body in documents:
        document = json.loads(body)
        if not isinstance(document, dict):
            raise ValueError("来源记录不可核查")
        if document.get("withdrawn") is True or document.get("validity_state") == "WITHDRAWN":
            withdrawn.add(identifier)
    source_ids = {item["source_id"] for item in parsed}
    memory_events = dict(db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='memory_deletion_event'", (namespace,)).fetchall())
    for identifier, body in memory_events.items():
        event = json.loads(body)
        if not isinstance(event, dict) or event.get("event_id") != identifier or event.get("namespace") != namespace or event.get("result") != "CURRENT_AND_HISTORY_CLEARED" or not isinstance(event.get("memory_id"), str) or not isinstance(event.get("deleted_version"), str) or identifier != event["memory_id"] + ":" + event["deleted_version"]:
            raise ValueError("记忆删除记录不可核查")
    markers = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='memory_deletion'", (namespace,)).fetchall()
    unmatched = 0
    for identifier, body in markers:
        marker = json.loads(body)
        if not isinstance(marker, dict) or not isinstance(marker.get("version"), str):
            raise ValueError("记忆删除标记不可核查")
        if identifier + ":" + marker["version"] not in memory_events:
            unmatched += 1
    return {"source_events": len(parsed), "withdrawn_without_event": len(withdrawn - source_ids),
            "memory_events": len(memory_events), "memory_markers_without_event": unmatched,
            "schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "source_history_complete": False, "memory_history_complete": False, "restore_state": "BLOCKED"}


def artifact_state_rows(db, namespace):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifacts'").fetchone()
    if exists is None:
        return []
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_brief_cleanup'").fetchone() is not None:
        migration = Path(__file__).parent / "migrations" / "upgrade2_artifact_brief_cleanup_001.sql"
        if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_artifact_brief_cleanup_001'").fetchone() != (hashlib.sha256(migration.read_bytes()).hexdigest(),):
            raise ValueError("会议简报清理迁移不可核查")
        records = db.execute("SELECT c.artifact_id,c.run_id,c.source_id,c.withdrawal_event_id,e.body,b.artifact_id FROM agent_artifact_brief_cleanup c JOIN agent_file_reservations f ON f.artifact_id=c.artifact_id AND f.run_id=c.run_id JOIN agent_runs r ON r.run_id=f.run_id LEFT JOIN objects e ON e.namespace=r.space_id AND e.kind='source_withdrawal_event' AND e.id=c.withdrawal_event_id LEFT JOIN agent_artifact_briefs b ON b.artifact_id=c.artifact_id WHERE r.space_id=?", (namespace,)).fetchall()
        for _, _, source_id, event_id, body, snapshot_id in records:
            event = json.loads(body) if body is not None else None
            if snapshot_id is not None or not isinstance(event, dict) or event.get("event_id") != event_id or event.get("namespace") != namespace or event.get("source_id") != source_id or event.get("result") != "WITHDRAWN":
                raise ValueError("会议简报清理记录不可核查")
    rows = [("agent_artifacts", row) for row in db.execute(
        "SELECT a.artifact_id,a.run_id,a.version,a.media_type,a.sha256,a.source_refs,a.context,a.verification_status,a.status,a.workspace,a.storage_key,a.size_bytes FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=? ORDER BY a.artifact_id",
        (namespace,)).fetchall()]
    identifiers = [row[1][0] for row in rows]
    if identifiers:
        placeholders = ",".join("?" for _ in identifiers)
        for table, columns in ARTIFACT_STATE:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
                continue
            for record in db.execute("SELECT artifact_id," + ",".join(columns) + " FROM " + table + " WHERE artifact_id IN (" + placeholders + ") ORDER BY artifact_id", identifiers).fetchall():
                rows.append((table, record))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_pending'").fetchone() is not None:
        pending = db.execute("SELECT p.artifact_id,p.sha256,p.source_refs,p.context,f.status,p.workspace,f.run_id FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.space_id=? ORDER BY p.artifact_id", (namespace,)).fetchall()
        rows.extend(("agent_artifact_pending", record) for record in pending)
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_brief_cleanup'").fetchone() is not None:
            records = db.execute("SELECT c.artifact_id,c.run_id,c.source_id,c.withdrawal_event_id,c.cleaned_at FROM agent_artifact_brief_cleanup c JOIN agent_file_reservations f ON f.artifact_id=c.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.space_id=? AND f.status='RESERVED' ORDER BY c.artifact_id", (namespace,)).fetchall()
            rows.extend(("agent_artifact_brief_cleanup", record) for record in records)
    return rows


def verify_artifact_files_in_transaction(db, namespace, mapping):
    from agent_artifact_workspace import ArtifactWorkspace
    from agent_artifacts import read_verified_file
    if not db.in_transaction or not isinstance(mapping, ArtifactWorkspace):
        raise ValueError("成果文件核查需要事务和目录映射")
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifacts'").fetchone() is None:
        raise ValueError("成果记录不可核查")
    rows = db.execute("SELECT a.run_id,a.workspace,a.storage_key,a.size_bytes,a.sha256,a.status,a.verification_status FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=? ORDER BY a.artifact_id", (namespace,)).fetchall()
    verified = revoked = 0
    for run_id, workspace, key, size, digest, status, verification in rows:
        directory = mapping.open(run_id)
        if str(directory) != workspace:
            raise ValueError("成果记录与运行目录不一致")
        if status in {"VERIFIED", "PUBLISHED"} and verification == "VERIFIED":
            read_verified_file(directory, key, size, digest)
            verified += 1
        elif status == "REVOKED":
            revoked += 1
        else:
            raise ValueError("成果记录状态不可核查")
    pending = db.execute("SELECT count(*) FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.space_id=?", (namespace,)).fetchone()[0]
    return {"verified_files": verified, "revoked_records": revoked, "pending_records": pending, "restore_state": "BLOCKED"}


def referenced_source_ids_in_transaction(db, namespace, rows):
    references = set()

    def collect(values, message):
        if not isinstance(values, list):
            raise ValueError(message)
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get("source_id"), str) or not item["source_id"]:
                raise ValueError(message)
            references.add(item["source_id"])

    for kind, _, body in rows:
        if kind != "conversation_source_binding":
            continue
        record = json.loads(body)
        if not isinstance(record, dict):
            raise ValueError("会话来源绑定不可核查")
        for key in ("source_refs", "source_pins"):
            collect(record.get(key, []), "会话来源绑定不可核查")
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifacts'").fetchone() is not None:
        for (raw,) in db.execute("SELECT a.source_refs FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=?", (namespace,)).fetchall():
            collect(json.loads(raw), "成果来源引用不可核查")
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_run_events'").fetchone() is not None:
        for (raw,) in db.execute("SELECT e.payload FROM agent_run_events e JOIN agent_runs r ON r.run_id=e.run_id WHERE r.space_id=? AND e.type='RESULT_RECORDED'", (namespace,)).fetchall():
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("运行结果来源引用不可核查")
            for key in ("source_pins", "citations"):
                collect(payload.get(key, []), "运行结果来源引用不可核查")
    return references


def artifact_withdrawal_pending_in_transaction(db, namespace, withdrawn_ids):
    if not withdrawn_ids or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifacts'").fetchone() is None:
        return []
    rows = db.execute("SELECT a.artifact_id,a.status,a.source_refs,v.series_id,v.version FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id JOIN agent_artifact_versions v ON v.artifact_id=a.artifact_id WHERE r.space_id=? ORDER BY v.series_id,v.version", (namespace,)).fetchall()
    series = {}
    for artifact_id, status, raw_refs, series_id, version in rows:
        refs = json.loads(raw_refs)
        if not isinstance(refs, list) or any(not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str) for ref in refs):
            raise ValueError("成果来源引用不可核查")
        series.setdefault(series_id, []).append((artifact_id, status, version, {ref["source_id"] for ref in refs}))
    pending = set()
    for records in series.values():
        direct = [version for _, status, version, source_ids in records if status in {"VERIFIED", "PUBLISHED"} and source_ids & withdrawn_ids]
        if not direct:
            continue
        start = min(direct)
        for artifact_id, status, version, _ in records:
            if version >= start and status in {"VERIFIED", "PUBLISHED"}:
                pending.add(artifact_id)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_briefs'").fetchone() is not None:
        briefs = db.execute("SELECT b.artifact_id,COALESCE(a.source_refs,p.source_refs),v.previous_artifact_id FROM agent_artifact_briefs b JOIN agent_file_reservations f ON f.artifact_id=b.artifact_id JOIN agent_runs r ON r.run_id=f.run_id JOIN agent_artifact_versions v ON v.artifact_id=b.artifact_id LEFT JOIN agent_artifacts a ON a.artifact_id=b.artifact_id LEFT JOIN agent_artifact_pending p ON p.artifact_id=b.artifact_id WHERE r.space_id=?", (namespace,)).fetchall()
        for artifact_id, raw_refs, previous in briefs:
            refs = json.loads(raw_refs) if raw_refs is not None else None
            if not isinstance(refs, list) or any(not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str) for ref in refs):
                raise ValueError("会议简报来源不可核查")
            revoked = db.execute("SELECT source_id FROM agent_artifact_revocations WHERE artifact_id=? AND reason='SOURCE_WITHDRAWN'", (artifact_id,)).fetchone()
            prior = db.execute("SELECT source_id FROM agent_artifact_revocations WHERE artifact_id=? AND reason='SOURCE_WITHDRAWN'", (previous,)).fetchone() if previous else None
            if {ref["source_id"] for ref in refs} & withdrawn_ids or revoked is not None and revoked[0] in withdrawn_ids or prior is not None and prior[0] in withdrawn_ids:
                pending.add(artifact_id)
    return sorted(pending)


class AgentRecoveryPreflight:
    def __init__(self, store):
        if not isinstance(store, ControlStore):
            raise ValueError("恢复核查需要业务数据库")
        self.store = store

    def current_state_in_transaction(self, db):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("恢复核查需要同一业务数据库事务")
        db.execute("UPDATE spaces SET active=active WHERE 0")
        context = _context(db)
        namespace = context["namespace"]
        if pending_transition(db, namespace) is not None:
            raise ValueError("执行空间正在切换")
        reference, _ = memory_adoption(self.store, db, namespace)
        withdrawal = verify_source_withdrawals_in_transaction(self.store, db, namespace)
        deletion = inspect_memory_deletion_history_in_transaction(self.store, db, namespace)
        kinds = ("document", "document_revision", "document_history", "memory", "memory_revision", "memory_deletion", "memory_deletion_event", "hermes_memory_adoption", "hermes_source_cleanup", "hermes_memory_invalidation", "hermes_document_result", "source_withdrawal_event", "conversation_source_binding", "authorization")
        placeholders = ",".join("?" for _ in kinds)
        rows = db.execute("SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN (" + placeholders + ") ORDER BY kind,id", (namespace, *kinds)).fetchall()
        digest = hashlib.sha256()
        for row in rows:
            encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        artifacts = artifact_state_rows(db, namespace)
        for table, record in artifacts:
            encoded = json.dumps([table, *record], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        pending = list(deletion["pending"])
        documents = {}
        cleanup = {}
        document_results = []
        for kind, identifier, body in rows:
            record = json.loads(body)
            if not isinstance(record, dict):
                raise ValueError("恢复核查记录格式无效")
            if kind == "hermes_source_cleanup" and (record.get("source_id") != identifier or record.get("state") not in {"PENDING", "FAILED", "COMPLETED"}):
                raise ValueError("来源清理状态不可核查")
            if kind == "hermes_source_cleanup" and record["state"] != "COMPLETED":
                pending.append("SOURCE_CLEANUP")
            if kind == "hermes_source_cleanup":
                cleanup[identifier] = record
                if identifier not in documents:
                    pending.append("SOURCE_DELETED")
            if kind == "document":
                documents[identifier] = record
                if record.get("withdrawn") is True or record.get("validity_state") == "WITHDRAWN":
                    if identifier in withdrawal["missing_source_ids"]:
                        pending.append("SOURCE_WITHDRAWAL_HISTORY_MISSING")
                    else:
                        pending.append("SOURCE_WITHDRAWAL_HISTORY_UNVERIFIED")
            if kind == "source_withdrawal_event" and record.get("source_id") not in documents:
                pending.append("SOURCE_DELETED")
            if kind == "hermes_document_result":
                document_results.append(record)
            if kind == "memory_deletion" and (record.get("state") != "CURRENT_AND_HISTORY_CLEARED" or record.get("backups") != "VERIFIED"):
                pending.append("MEMORY_BACKUPS")
        for identifier, marker in cleanup.items():
            document = documents.get(identifier)
            if marker["state"] == "COMPLETED" and (document is None or (document.get("withdrawn") is not True and document.get("validity_state") != "WITHDRAWN")):
                pending.append("SOURCE_CLEANUP_UNVERIFIED")
        for result in document_results:
            if any(not isinstance(result.get(field), str) or not result[field] for field in ("run_id", "call_id", "request_digest")):
                raise ValueError("文档工具结果不可核查")
            if result.get("state") == "REVOKED":
                if "result" in result or not isinstance(result.get("result_sha256"), str) or not isinstance(result.get("revoked_source_id"), str):
                    raise ValueError("文档工具失效记录不可核查")
                document = documents.get(result["revoked_source_id"])
                if document is None or (document.get("withdrawn") is not True and document.get("validity_state") != "WITHDRAWN"):
                    pending.append("DOCUMENT_RESULT_REVOCATION_UNVERIFIED")
                continue
            body = result.get("result")
            if not isinstance(body, dict) or not isinstance(body.get("records"), list) or not body["records"] or not isinstance(body.get("sources"), list) or not body["sources"]:
                raise ValueError("文档工具结果来源不可核查")
            refs = list(body["sources"])
            for record in body["records"]:
                if not isinstance(record, dict) or not isinstance(record.get("source_refs"), list) or not record["source_refs"]:
                    raise ValueError("文档工具结果来源不可核查")
                refs.extend(record["source_refs"])
            if any(not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str) or not ref["source_id"] for ref in refs):
                raise ValueError("文档工具结果来源不可核查")
            for ref in refs:
                document = documents.get(ref["source_id"])
                if document is None or document.get("withdrawn") is True or document.get("validity_state") == "WITHDRAWN":
                    pending.append("DOCUMENT_RESULT_SOURCE_UNAVAILABLE")
                elif document.get("version") != ref.get("version"):
                    pending.append("DOCUMENT_RESULT_SOURCE_CHANGED")
        for source_id in sorted(referenced_source_ids_in_transaction(db, namespace, rows)):
            if source_id not in documents:
                pending.append("SOURCE_DELETED")
        withdrawn_ids = {identifier for identifier, document in documents.items()
                         if document.get("withdrawn") is True or document.get("validity_state") == "WITHDRAWN"}
        pending_artifacts = artifact_withdrawal_pending_in_transaction(db, namespace, withdrawn_ids)
        if pending_artifacts:
            pending.append("ARTIFACT_WITHDRAWAL_PENDING")
        return {"namespace": namespace, "owner_id": context["owner_id"], "dataset_id": context["dataset_id"],
                "dataset_version": context["dataset_version"], "memory_reference": reference,
                "state_sha256": digest.hexdigest(), "pending": sorted(set(pending)),
                "source_event_count": withdrawal["event_count"], "source_missing_count": len(withdrawal["missing_source_ids"]),
                "source_history_complete": withdrawal["history_complete"],
                "memory_event_count": deletion["event_count"], "memory_marker_count": deletion["marker_count"], "memory_history_complete": deletion["history_complete"],
                "artifact_state_count": len(artifacts), "artifact_revocation_count": sum(1 for table, _ in artifacts if table == "agent_artifact_revocations"),
                "artifact_withdrawal_pending_count": len(pending_artifacts),
                "restore_state": "BLOCKED", "reason": "DELETION_LEDGER_COMPLETENESS_UNVERIFIED"}
