import hashlib
import json
import math
import os
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from aiohttp import web
from filelock import FileLock

from agent_simulation_snapshot import AgentSimulationSnapshot, MIGRATION, VERSION
from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
from role_channel import RoleChannel


def artifact_state(db, namespace):
    tables = {"agent_artifacts", "agent_artifact_versions", "agent_artifact_revocations", "agent_artifact_publications"}
    present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if not tables & present:
        return None
    if not tables.issubset(present) or "agent_runs" not in present:
        raise ValueError("成果状态表不完整")
    queries = {
        "agent_artifacts": "SELECT a.artifact_id,a.status,a.version,a.sha256,a.source_refs,a.run_id,a.workspace,a.storage_key,a.size_bytes FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=? ORDER BY a.artifact_id",
        "agent_artifact_versions": "SELECT v.artifact_id,v.series_id,v.version,v.previous_artifact_id FROM agent_artifact_versions v JOIN agent_artifacts a ON a.artifact_id=v.artifact_id JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=? ORDER BY v.artifact_id",
        "agent_artifact_revocations": "SELECT v.artifact_id,v.reason,v.source_id,v.revoked_at FROM agent_artifact_revocations v JOIN agent_artifacts a ON a.artifact_id=v.artifact_id JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=? ORDER BY v.artifact_id",
        "agent_artifact_publications": "SELECT p.artifact_id,p.run_id,p.version,p.sha256,p.actor_id,p.published_at FROM agent_artifact_publications p JOIN agent_artifacts a ON a.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=? ORDER BY p.artifact_id",
    }
    if "agent_artifact_briefs" in present:
        queries["agent_artifact_briefs"] = "SELECT b.artifact_id,b.snapshot_sha256 FROM agent_artifact_briefs b JOIN agent_file_reservations f ON f.artifact_id=b.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.space_id=? ORDER BY b.artifact_id"
    if "agent_artifact_brief_cleanup" in present:
        queries["agent_artifact_brief_cleanup"] = "SELECT c.artifact_id,c.run_id,c.source_id,c.withdrawal_event_id,c.cleaned_at FROM agent_artifact_brief_cleanup c JOIN agent_file_reservations f ON f.artifact_id=c.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.space_id=? ORDER BY c.artifact_id"
    if "agent_artifact_pending" in present:
        queries["agent_artifact_pending"] = "SELECT p.artifact_id,p.sha256,p.source_refs,p.context,f.status,p.workspace,f.run_id FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.space_id=? ORDER BY p.artifact_id"
    return {table: {row[0]: hashlib.sha256(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest() for row in db.execute(query, (namespace,)).fetchall()} for table, query in queries.items()}


class AgentSimulationRecovery:
    def __init__(self, snapshots, journal):
        if not isinstance(snapshots, AgentSimulationSnapshot) or not isinstance(journal, AgentSimulationRecoveryJournal) or journal.snapshots is not snapshots:
            raise ValueError("需要独立模拟快照服务")
        self.snapshots = snapshots
        self.store = snapshots.store
        self.journal = journal

    def inspect_artifact_files(self, request_key, mapping, *, max_age_seconds):
        from agent_recovery_preflight import verify_artifact_files_in_transaction
        checked = self.preflight(request_key, max_age_seconds=max_age_seconds)
        path = self.snapshots.directory / checked["snapshot_name"]
        if path.parent.resolve() != self.snapshots.directory or path.is_symlink() or not path.is_file():
            raise ValueError("模拟快照文件不可核查")
        with path.open("rb") as content:
            if hashlib.file_digest(content, "sha256").hexdigest() != checked["sha256"]:
                raise ValueError("模拟快照文件摘要不符")
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as snapshot:
            snapshot.execute("BEGIN")
            namespace = snapshot.execute("SELECT namespace FROM agent_recovery_checkpoints WHERE checkpoint_id=?", (checked["checkpoint_id"],)).fetchone()
            if namespace is None:
                raise ValueError("模拟快照执行空间不可核查")
            result = verify_artifact_files_in_transaction(snapshot, namespace[0], mapping)
        return {**result, "snapshot_name": checked["snapshot_name"], "sha256": checked["sha256"], "coverage": "REFERENCED_FILES_ONLY"}

    def _artifact_backup(self, request_key, mapping, *, max_age_seconds, create):
        from agent_artifact_workspace import ArtifactWorkspace
        from agent_artifacts import read_verified_file, store_exact_file
        from agent_simulation_snapshot import SIMULATION_ROOT
        if not isinstance(mapping, ArtifactWorkspace) or not mapping.root.is_relative_to(SIMULATION_ROOT.resolve()):
            raise ValueError("成果备份仅允许独立模拟目录")
        checked = self.preflight(request_key, max_age_seconds=max_age_seconds)
        snapshot_path = self.snapshots.directory / checked["snapshot_name"]
        target = self.snapshots.directory / (checked["snapshot_name"] + ".artifacts")
        with closing(sqlite3.connect(snapshot_path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("BEGIN")
            namespace = db.execute("SELECT namespace FROM agent_recovery_checkpoints WHERE checkpoint_id=?", (checked["checkpoint_id"],)).fetchone()
            if namespace is None:
                raise ValueError("模拟快照执行空间不可核查")
            rows = db.execute("SELECT a.run_id,a.workspace,a.storage_key,a.size_bytes,a.sha256,a.status,a.verification_status FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=? ORDER BY a.run_id,a.artifact_id", (namespace[0],)).fetchall()
            pending = db.execute("SELECT count(*) FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.space_id=?", (namespace[0],)).fetchone()[0]
            if pending:
                raise ValueError("待登记成果文件尚未核查")
            if create:
                target.mkdir(mode=0o700)
            if target.is_symlink() or not target.is_dir() or target.resolve(strict=True) != target:
                raise ValueError("成果备份目录不可核查")
            backup = ArtifactWorkspace(target)
            directories = set()
            expected_files = {}
            count = 0
            for run_id, workspace, key, size, digest, status, verification in rows:
                if status == "REVOKED":
                    continue
                if status not in {"VERIFIED", "PUBLISHED"} or verification != "VERIFIED" or str(mapping.open(run_id)) != workspace:
                    raise ValueError("成果记录或目录不可核查")
                if run_id not in directories:
                    if create:
                        backup.create(run_id)
                    else:
                        backup.open(run_id)
                    directories.add(run_id)
                destination = backup.open(run_id)
                expected_files.setdefault(run_id, set()).add(key)
                if create:
                    content = read_verified_file(mapping.open(run_id), key, size, digest)
                    store_exact_file(destination, key, content)
                read_verified_file(destination, key, size, digest)
                count += 1
            if {item.name for item in target.iterdir()} != directories:
                raise ValueError("成果备份目录内容不可核查")
            for run_id, names in expected_files.items():
                if {item.name for item in backup.open(run_id).iterdir()} != names:
                    raise ValueError("成果备份文件清单不一致")
        self.preflight(request_key, max_age_seconds=max_age_seconds)
        return {"snapshot_name": checked["snapshot_name"], "sha256": checked["sha256"], "files": count, "restore_state": "BLOCKED"}

    def create_artifact_backup(self, request_key, mapping, *, max_age_seconds):
        return self._artifact_backup(request_key, mapping, max_age_seconds=max_age_seconds, create=True)

    def inspect_artifact_backup(self, request_key, mapping, *, max_age_seconds):
        return self._artifact_backup(request_key, mapping, max_age_seconds=max_age_seconds, create=False)

    def create_cleanup_trial(self, request_key, mapping, *, max_age_seconds):
        from agent_artifact_workspace import ArtifactWorkspace
        from agent_artifacts import read_verified_file, store_exact_file
        checked = self.inspect_artifact_backup(request_key, mapping, max_age_seconds=max_age_seconds)
        base = self.snapshots.directory / "cleanup-trials"
        base.mkdir(mode=0o700, exist_ok=True)
        if base.is_symlink() or not base.is_dir() or base.resolve(strict=True) != base:
            raise ValueError("清理试验根目录不可核查")
        trial_id = str(uuid4())
        trial = base / trial_id
        trial.mkdir(mode=0o700)
        payload = trial / "payload"
        payload.mkdir(mode=0o700)
        original = self.snapshots.directory / checked["snapshot_name"]
        source_fd = os.open(original, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(source_fd, "rb") as stream, (payload / "database.sqlite").open("xb") as destination:
            while chunk := stream.read(1024 * 1024):
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if hashlib.sha256((payload / "database.sqlite").read_bytes()).hexdigest() != checked["sha256"]:
            raise ValueError("清理试验数据库摘要不符")
        source = self.snapshots.directory / (checked["snapshot_name"] + ".artifacts")
        backup = ArtifactWorkspace(source)
        target_root = payload / "artifacts"
        target_root.mkdir(mode=0o700)
        target = ArtifactWorkspace(target_root)
        with closing(sqlite3.connect((payload / "database.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)) as snapshot:
            rows = snapshot.execute("SELECT a.run_id,a.storage_key,a.size_bytes,a.sha256 FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=(SELECT namespace FROM agent_recovery_checkpoints WHERE checkpoint_id=?) AND a.status IN ('VERIFIED','PUBLISHED') ORDER BY a.run_id,a.artifact_id", (self.preflight(request_key, max_age_seconds=max_age_seconds)["checkpoint_id"],)).fetchall()
            copied_runs = set()
            for run_id, key, size, digest in rows:
                if run_id not in copied_runs:
                    target.create(run_id)
                    copied_runs.add(run_id)
                store_exact_file(target.open(run_id), key, read_verified_file(backup.open(run_id), key, size, digest))
        files = []
        for directory, dirs, names in os.walk(payload, followlinks=False):
            for name in dirs:
                item = Path(directory) / name
                if item.is_symlink() or not item.is_dir():
                    raise ValueError("清理试验目录不可核查")
            for name in names:
                item = Path(directory) / name
                if item.is_symlink() or not item.is_file():
                    raise ValueError("清理试验文件不可核查")
                relative = item.relative_to(payload)
                digest = hashlib.sha256(item.read_bytes()).hexdigest()
                files.append([relative.as_posix(), digest])
        self.inspect_artifact_backup(request_key, mapping, max_age_seconds=max_age_seconds)
        with closing(sqlite3.connect(trial / "journal.sqlite")) as db:
            db.execute("CREATE TABLE cleanup_trial (request_key TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL, files TEXT NOT NULL, state TEXT NOT NULL)")
            db.execute("INSERT INTO cleanup_trial VALUES (?,?,?,?)", (request_key, checked["sha256"], json.dumps(sorted(files)), "PREPARED"))
            db.commit()
        return {"trial_id": trial_id, "files": len(files), "state": "PREPARED", "restore_state": "BLOCKED"}

    def cleanup_trial(self, trial_id):
        if not isinstance(trial_id, str) or str(UUID(trial_id)) != trial_id:
            raise ValueError("清理试验编号无效")
        base = self.snapshots.directory / "cleanup-trials"
        trial = base / trial_id
        if base.is_symlink() or trial.is_symlink() or not trial.is_dir() or trial.resolve(strict=True) != trial:
            raise ValueError("清理试验目录不可核查")
        journal = trial / "journal.sqlite"
        if journal.is_symlink() or not journal.is_file():
            raise ValueError("清理试验记录不可核查")
        with FileLock(str(trial / "cleanup.lock"), timeout=10), closing(sqlite3.connect(journal)) as db:
            row = db.execute("SELECT request_key,snapshot_sha256,files,state FROM cleanup_trial").fetchall()
            if len(row) != 1 or row[0][3] not in {"PREPARED", "CLEANING", "COMPLETED"}:
                raise ValueError("清理试验记录状态不可核查")
            request_key, snapshot_sha, raw_files, state = row[0]
            replay = self.inspect_withdrawal_replay(request_key)
            if replay["sha256"] != snapshot_sha or replay["new_withdrawal_events"] < 1 or replay["affected_artifacts"] < 1:
                raise ValueError("清理试验缺少实际来源撤销影响")
            files = json.loads(raw_files)
            if not isinstance(files, list) or not files or any(not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str) or not isinstance(item[1], str) or Path(item[0]).is_absolute() or ".." in Path(item[0]).parts for item in files) or len({item[0] for item in files}) != len(files):
                raise ValueError("清理试验文件清单不可核查")
            payload = trial / "payload"
            if payload.is_symlink() or not payload.is_dir():
                raise ValueError("清理试验内容目录不可核查")
            present = set()
            for directory, dirs, names in os.walk(payload, followlinks=False):
                for name in dirs:
                    item = Path(directory) / name
                    if item.is_symlink() or not item.is_dir():
                        raise ValueError("清理试验目录不可核查")
                for name in names:
                    item = Path(directory) / name
                    if item.is_symlink() or not stat.S_ISREG(item.lstat().st_mode):
                        raise ValueError("清理试验文件不可核查")
                    present.add(item.relative_to(payload).as_posix())
            expected = {item[0] for item in files}
            if not present.issubset(expected) or state == "PREPARED" and present != expected or state == "COMPLETED" and present:
                raise ValueError("清理试验文件清单不一致")
            for name, digest in files:
                if name in present and hashlib.sha256((payload / name).read_bytes()).hexdigest() != digest:
                    raise ValueError("清理试验文件摘要不符")
            if state == "PREPARED":
                db.execute("UPDATE cleanup_trial SET state='CLEANING'")
                db.commit()
            for name, _ in files:
                if name in present:
                    from agent_artifacts import open_workspace_directory
                    parts = Path(name).parts
                    descriptor = open_workspace_directory(payload)
                    try:
                        for part in parts[:-1]:
                            next_descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                            os.close(descriptor)
                            descriptor = next_descriptor
                        os.unlink(parts[-1], dir_fd=descriptor)
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            db.execute("UPDATE cleanup_trial SET state='COMPLETED'")
            db.commit()
            return {"trial_id": trial_id, "state": "COMPLETED", "removed_files": len(files), "restore_state": "BLOCKED"}

    def inspect_withdrawal_replay(self, request_key):
        from hermes_source_invalidation import verify_source_withdrawals_in_transaction
        delta = self.inspect_privacy_delta(request_key)
        path = self.snapshots.directory / delta["snapshot_name"]
        with self.store.connect() as current:
            current.execute("BEGIN IMMEDIATE")
            state = self.snapshots.checkpoint.preflight.current_state_in_transaction(current)
            verified = verify_source_withdrawals_in_transaction(self.store, current, state["namespace"])
            events = current.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event' ORDER BY id", (state["namespace"],)).fetchall()
            revoked = current.execute("SELECT a.artifact_id,x.source_id FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id JOIN agent_artifact_revocations x ON x.artifact_id=a.artifact_id WHERE r.space_id=? AND x.reason='SOURCE_WITHDRAWN'", (state["namespace"],)).fetchall()
            with path.open("rb") as content:
                if hashlib.file_digest(content, "sha256").hexdigest() != delta["sha256"]:
                    raise ValueError("模拟快照文件摘要不符")
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as snapshot:
                saved_events = dict(snapshot.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", (state["namespace"],)).fetchall())
                saved_artifacts = {row[0] for row in snapshot.execute("SELECT a.artifact_id FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id WHERE r.space_id=? AND a.status IN ('VERIFIED','PUBLISHED')", (state["namespace"],)).fetchall()}
                saved_pending = snapshot.execute("SELECT p.artifact_id,p.content,p.sha256,p.source_refs,f.status,f.size_bytes,v.series_id,v.version,v.previous_artifact_id,pv.series_id,pv.version FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id JOIN agent_artifact_versions v ON v.artifact_id=p.artifact_id LEFT JOIN agent_artifact_versions pv ON pv.artifact_id=v.previous_artifact_id WHERE r.space_id=?", (state["namespace"],)).fetchall()
                pending_count = snapshot.execute("SELECT count(*) FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.space_id=?", (state["namespace"],)).fetchone()[0]
                if len(saved_pending) != pending_count:
                    raise ValueError("快照待登记版本关系不可核查")
            current_events = dict(events)
            if any(current_events.get(identifier) != body for identifier, body in saved_events.items()):
                raise ValueError("来源撤销历史已经变化")
            newer = [json.loads(body) for identifier, body in events if identifier not in saved_events]
            sources = {event["source_id"] for event in newer}
            affected = {artifact_id for artifact_id, source_id in revoked if source_id in sources and artifact_id in saved_artifacts}
            revoked_ids = {artifact_id for artifact_id, source_id in revoked if source_id in sources}
            affected_pending = set()
            pending_with_content = 0
            for identifier, content, digest, raw_refs, status, size, series, version, previous, prior_series, prior_version in saved_pending:
                refs = json.loads(raw_refs)
                if status != "RESERVED" or not isinstance(refs, list) or not refs or any(not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str) or not ref["source_id"] for ref in refs) or hashlib.sha256(content).hexdigest() != digest or (content and len(content) != size) or (previous is not None and (series != prior_series or type(prior_version) is not int or version != prior_version + 1)):
                    raise ValueError("快照待登记成果不可核查")
                if {ref["source_id"] for ref in refs} & sources or previous in revoked_ids:
                    affected_pending.add(identifier)
                    pending_with_content += bool(content)
            cleared = 0
            for identifier in affected_pending:
                row = current.execute("SELECT p.content,p.sha256,f.status FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE p.artifact_id=? AND r.space_id=?", (identifier, state["namespace"])).fetchone()
                if row == (b"", hashlib.sha256(b"").hexdigest(), "RESERVED"):
                    cleared += 1
            return {"snapshot_name": delta["snapshot_name"], "sha256": delta["sha256"], "new_withdrawal_events": len(newer),
                    "affected_artifacts": len(affected), "affected_pending": len(affected_pending),
                    "affected_pending_with_content": pending_with_content, "current_pending_cleared": cleared, "history_complete": verified["history_complete"],
                    "database_backup_cleanup": "BLOCKED", "artifact_backup_cleanup": "BLOCKED", "restore_state": "BLOCKED"}

    def inspect_privacy_delta(self, request_key):
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200:
            raise ValueError("模拟快照请求编号无效")
        with self.store.connect() as current:
            current.execute("BEGIN IMMEDIATE")
            if current.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
                raise ValueError("模拟快照迁移摘要不符")
            state = self.snapshots.checkpoint.preflight.current_state_in_transaction(current)
            namespace = state["namespace"]
            current_artifacts = artifact_state(current, namespace)
            row = current.execute("SELECT checkpoint_request_key,checkpoint_id,snapshot_name,snapshot_sha256,manifest_json FROM agent_simulation_snapshots WHERE namespace=? AND request_key=?", (namespace, request_key)).fetchone()
            if row is None:
                raise ValueError("模拟快照记录不存在")
            manifest = json.loads(row[4])
            if (manifest.get("namespace"), manifest.get("owner_id"), manifest.get("dataset_id"), manifest.get("dataset_version"), manifest.get("checkpoint_id"), manifest.get("coverage"), manifest.get("restore_state")) != (namespace, state["owner_id"], state["dataset_id"], state["dataset_version"], row[1], ["business_sqlite"], "BLOCKED"):
                raise ValueError("模拟快照身份或范围不符")
            path = self.snapshots.directory / row[2]
            sidecars = (Path(str(path) + "-wal"), Path(str(path) + "-journal"), Path(str(path) + "-shm"))
            if path.parent.resolve() != self.snapshots.directory or path.is_symlink() or not path.is_file() or any(item.exists() for item in sidecars):
                raise ValueError("模拟快照文件缺少或日志状态无效")
            with path.open("rb") as content:
                if hashlib.file_digest(content, "sha256").hexdigest() != row[3]:
                    raise ValueError("模拟快照文件摘要不符")
            kinds = ("memory", "memory_revision", "memory_deletion", "memory_deletion_event", "hermes_memory_adoption", "hermes_memory_invalidation", "hermes_document_result", "conversation_source_binding", "document", "document_revision", "document_history", "hermes_source_cleanup", "source_withdrawal_event", "authorization")
            placeholders = ",".join("?" for _ in kinds)
            query = "SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN (" + placeholders + ") ORDER BY kind,id"
            current_rows = {(kind, identifier): hashlib.sha256(body.encode("utf-8")).hexdigest() for kind, identifier, body in current.execute(query, (namespace, *kinds))}
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as snapshot:
                if snapshot.execute("PRAGMA integrity_check").fetchone() != ("ok",) or snapshot.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("模拟快照完整性核查失败")
                checkpoint = snapshot.execute("SELECT checkpoint_id,state_json FROM agent_recovery_checkpoints WHERE namespace=? AND request_key=?", (namespace, row[0])).fetchone()
                if checkpoint is None or checkpoint[0] != row[1] or json.loads(checkpoint[1]).get("state_sha256") != manifest.get("state_sha256"):
                    raise ValueError("模拟快照检查点不符")
                if [list(item) for item in snapshot.execute("SELECT version,sha256 FROM agent_schema_migrations ORDER BY version").fetchall()] != manifest.get("schema_versions"):
                    raise ValueError("模拟快照迁移版本不符")
                saved_rows = {(kind, identifier): hashlib.sha256(body.encode("utf-8")).hexdigest() for kind, identifier, body in snapshot.execute(query, (namespace, *kinds))}
                snapshot_artifacts = artifact_state(snapshot, namespace)
            missing = {kind: sum(1 for key in current_rows if key[0] == kind and key not in saved_rows) for kind in kinds}
            changed = {kind: sum(1 for key, digest in current_rows.items() if key[0] == kind and key in saved_rows and saved_rows[key] != digest) for kind in kinds}
            older_only = {kind: sum(1 for key in saved_rows if key[0] == kind and key not in current_rows) for kind in kinds}
            current_tables, snapshot_tables = current_artifacts or {}, snapshot_artifacts or {}
            artifact_changed = artifact_current_only = artifact_snapshot_only = 0
            for table in set(current_tables) | set(snapshot_tables):
                current_table, snapshot_table = current_tables.get(table, {}), snapshot_tables.get(table, {})
                artifact_changed += sum(1 for key, digest in current_table.items() if key in snapshot_table and snapshot_table[key] != digest)
                artifact_current_only += sum(1 for key in current_table if key not in snapshot_table)
                artifact_snapshot_only += sum(1 for key in snapshot_table if key not in current_table)
            artifact_available = current_artifacts is not None and snapshot_artifacts is not None
            if artifact_available:
                artifact_reason = None
            elif current_artifacts is None and snapshot_artifacts is None:
                artifact_reason = "ARTIFACT_TABLES_ABSENT"
            elif current_artifacts is None:
                artifact_reason = "CURRENT_ARTIFACT_TABLES_MISSING"
            else:
                artifact_reason = "SNAPSHOT_ARTIFACT_TABLES_MISSING"
            return {"snapshot_name": row[2], "sha256": row[3], "checkpoint_id": row[1], "state_matches_current": manifest.get("state_sha256") == state["state_sha256"], "missing_current_records": missing, "changed_records": changed, "snapshot_only_records": older_only, "artifact_state_available": artifact_available, "artifact_state_reason": artifact_reason, "artifact_state_matches_current": current_artifacts == snapshot_artifacts, "artifact_changed_records": artifact_changed, "artifact_current_only_records": artifact_current_only, "artifact_snapshot_only_records": artifact_snapshot_only, "source_history_complete": state["source_history_complete"], "memory_history_complete": state["memory_history_complete"], "restore_state": "BLOCKED", "reason": "DELETION_LEDGER_COMPLETENESS_UNVERIFIED"}

    def preflight(self, request_key, *, max_age_seconds, baseline_id=None):
        if not isinstance(request_key, str) or not request_key or isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float)) or not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("模拟恢复核查参数无效")
        baseline = None
        if baseline_id is not None:
            from agent_simulation_deletion_baseline import SimulationDeletionBaseline
            baseline = SimulationDeletionBaseline(self.store)
        with self.store.connect() as current:
            current.execute("BEGIN IMMEDIATE")
            if current.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
                raise ValueError("模拟快照迁移摘要不符")
            state = self.snapshots.checkpoint.preflight.current_state_in_transaction(current)
            row = current.execute("SELECT checkpoint_request_key,checkpoint_id,snapshot_name,snapshot_sha256,manifest_json,created_at FROM agent_simulation_snapshots WHERE namespace=? AND request_key=?", (state["namespace"], request_key)).fetchone()
            if row is None:
                raise ValueError("模拟快照记录不存在")
            baseline_result = None
            if baseline is not None:
                link = current.execute("SELECT checkpoint_id,snapshot_sha256,baseline_id FROM agent_simulation_deletion_baseline_snapshots WHERE namespace=? AND snapshot_request_key=?", (state["namespace"], request_key)).fetchone()
                if link != (row[1], row[3], baseline_id):
                    raise ValueError("模拟快照删除基线关联不符")
                baseline_result = baseline.inspect_in_transaction(current, baseline_id)
                if baseline_result["new_events"]:
                    raise ValueError("模拟快照之后存在删除事件")
            self.snapshots.checkpoint.verify_in_transaction(current, row[0], row[1])
            created = datetime.fromisoformat(row[5])
            if created.tzinfo is None or created.utcoffset() is None or created > datetime.now(timezone.utc) or datetime.now(timezone.utc) - created > timedelta(seconds=max_age_seconds):
                raise ValueError("模拟快照已经过期或时间无效")
            manifest = json.loads(row[4])
            schema = [list(item) for item in current.execute("SELECT version,sha256 FROM agent_schema_migrations ORDER BY version").fetchall()]
            expected = {"namespace": state["namespace"], "owner_id": state["owner_id"], "dataset_id": state["dataset_id"],
                        "dataset_version": state["dataset_version"], "checkpoint_id": row[1], "state_sha256": state["state_sha256"],
                        "schema_versions": schema, "coverage": ["business_sqlite"], "restore_state": "BLOCKED"}
            if manifest != expected:
                raise ValueError("模拟快照身份、版本或范围不符")
            path = self.snapshots.directory / row[2]
            sidecars = (Path(str(path) + "-wal"), Path(str(path) + "-journal"), Path(str(path) + "-shm"))
            if path.parent.resolve() != self.snapshots.directory or path.is_symlink() or not path.is_file() or any(item.exists() for item in sidecars):
                raise ValueError("模拟快照文件缺少或日志状态无效")
            with path.open("rb") as content:
                if hashlib.file_digest(content, "sha256").hexdigest() != row[3]:
                    raise ValueError("模拟快照文件摘要不符")
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as snapshot:
                if snapshot.execute("PRAGMA integrity_check").fetchone() != ("ok",) or snapshot.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("模拟快照完整性核查失败")
                if [list(item) for item in snapshot.execute("SELECT version,sha256 FROM agent_schema_migrations ORDER BY version").fetchall()] != schema:
                    raise ValueError("模拟快照迁移版本不符")
                if snapshot.execute("SELECT checkpoint_id FROM agent_recovery_checkpoints WHERE namespace=? AND request_key=?", (state["namespace"], row[0])).fetchone() != (row[1],):
                    raise ValueError("模拟快照检查点不符")
            result = {"snapshot_name": row[2], "sha256": row[3], "checkpoint_id": row[1], "restore_state": "BLOCKED", "reason": "DELETION_LEDGER_COMPLETENESS_UNVERIFIED"}
            if baseline_result is not None:
                result["deletion_baseline"] = baseline_result
            return result

    def target_path(self, target_id):
        if not isinstance(target_id, str):
            raise ValueError("模拟恢复目录标识无效")
        identifier = UUID(target_id)
        if str(identifier) != target_id:
            raise ValueError("模拟恢复目录标识无效")
        root = self.snapshots.directory / "recovery"
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise ValueError("模拟恢复目录不可用")
        target = root / target_id
        if target.is_symlink() or target.exists():
            raise ValueError("模拟恢复目录已经存在")
        return target

    def restore(self, request, channel, request_key, target_id, *, max_age_seconds):
        if not isinstance(request, web.Request) or not isinstance(channel, RoleChannel) or channel.boss_commands is None or channel.boss_commands.store.path.resolve() != self.store.path.resolve():
            raise ValueError("需要同一业务数据库的本人身份服务")
        channel.require_run_api_role(request)
        self.target_path(target_id)
        checked = self.preflight(request_key, max_age_seconds=max_age_seconds)
        channel.require_run_api_role(request)
        self.journal.record_blocked(request_key, target_id, checked)
        raise web.HTTPServiceUnavailable(text="可信删除历史尚未完成，恢复不可用")
