import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

from boss_execution_transition import pending_transition
from boss_simulation_api import _context
from boss_source_access import require_current_business_source
from business import checksum
from hermes_bridge import EngineEventSink
from agent_run_scope import RunScopeService
from agent_artifact_formats import FORMATS, create_format, verify_format


def artifact_format(storage_key):
    if not isinstance(storage_key, str):
        raise ValueError("成果文件编号无效")
    suffix = Path(storage_key).suffix
    matches = [name for name, (extension, _) in FORMATS.items() if suffix == extension]
    if len(matches) != 1:
        raise ValueError("成果文件格式无效")
    identifier = storage_key.removesuffix(suffix)
    if str(UUID(identifier)) != identifier or storage_key != identifier + suffix:
        raise ValueError("成果文件编号无效")
    return matches[0]


def open_workspace_directory(workspace):
    workspace = Path(workspace)
    if not workspace.is_absolute() or any(part in {"", ".", ".."} for part in workspace.parts[1:]):
        raise ValueError("成果工作区不可核查")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    returned = False
    try:
        for part in workspace.parts[1:]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            previous_directory = directory
            directory = next_directory
            os.close(previous_directory)
        returned = True
        return directory
    finally:
        if not returned:
            os.close(directory)


def read_verified_file(workspace, storage_key, expected_size, expected_sha256):
    format_name = artifact_format(storage_key)
    if type(expected_size) is not int or expected_size <= 0:
        raise ValueError("成果文件大小无效")
    workspace = Path(workspace)
    directory = open_workspace_directory(workspace)
    try:
        workspace_before = os.fstat(directory)
        descriptor = os.open(storage_key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
                    raise ValueError("成果文件摘要或大小不符")
                content = stream.read(expected_size + 1)
                after = os.fstat(descriptor)
            current = os.stat(storage_key, dir_fd=directory, follow_symlinks=False)
            current_workspace = os.stat(workspace, follow_symlinks=False)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
    if (current_workspace.st_dev, current_workspace.st_ino) != (workspace_before.st_dev, workspace_before.st_ino):
        raise ValueError("成果工作区路径已经替换")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("成果文件读取期间发生变化")
    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("成果文件路径已经替换")
    if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("成果文件摘要不符")
    verify_format(format_name, content)
    return content


def verify_stored_artifact_file_in_transaction(db, artifact_id, expected_version):
    if not db.in_transaction:
        raise ValueError("成果文件核查需要事务")
    record = db.execute("SELECT run_id,version,workspace,storage_key,sha256,size_bytes,verification_status,status FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
    if record is None or record[1] != expected_version or record[6] != "VERIFIED" or record[7] not in {"VERIFIED", "PUBLISHED"}:
        raise ValueError("成果文件元数据不可核查")
    workspace = Path(record[2])
    if workspace.is_symlink() or not workspace.is_dir() or workspace.resolve(strict=True) != workspace:
        raise ValueError("成果工作区不可核查")
    read_verified_file(workspace, record[3], record[5], record[4])
    if record[7] == "PUBLISHED":
        publication = db.execute("SELECT run_id,version,sha256 FROM agent_artifact_publications WHERE artifact_id=?", (artifact_id,)).fetchone()
        if publication != (record[0], expected_version, record[4]):
            raise ValueError("成果发布记录不可核查")
    return {"artifact_id": artifact_id, "version": expected_version, "sha256": record[4], "size_bytes": record[5], "file_state": "VERIFIED"}


def store_exact_file(workspace, storage_key, content):
    artifact_format(storage_key)
    expected_sha256 = hashlib.sha256(content).hexdigest()
    path = workspace / storage_key
    if os.path.lexists(path):
        return read_verified_file(workspace, storage_key, len(content), expected_sha256)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return read_verified_file(workspace, storage_key, len(content), expected_sha256)


class ArtifactPreparation:
    @classmethod
    def for_run_workspace(cls, store, mapping, *, run_gate, scope_service, max_files, max_bytes):
        from agent_artifact_workspace import ArtifactWorkspace
        if not isinstance(mapping, ArtifactWorkspace) or not isinstance(run_gate, EngineEventSink):
            raise ValueError("需要成果目录映射与运行租约")
        service = cls(store, mapping.open(run_gate.config.run_id), run_gate=run_gate,
                      scope_service=scope_service, max_files=max_files, max_bytes=max_bytes)
        service.mapping = mapping
        return service

    def __init__(self, store, workspace, *, run_gate, scope_service, max_files, max_bytes):
        self.store = store
        if not isinstance(run_gate, EngineEventSink) or not isinstance(scope_service, RunScopeService):
            raise ValueError("需要运行租约和会话资料范围检查")
        if run_gate.store.path.resolve() != store.path.resolve() or scope_service.store.path.resolve() != store.path.resolve():
            raise ValueError("运行与资料必须使用同一数据库")
        if type(max_files) is not int or max_files <= 0 or type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("文件预算必须包含正整数")
        self.run_gate, self.scope_service = run_gate, scope_service
        self.max_files, self.max_bytes = max_files, max_bytes
        workspace = Path(workspace)
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("成果工作区必须是已存在的目录")
        self.workspace = workspace.resolve(strict=True)
        self.mapping = None

    def _require_run(self, db, run_id, source_ids, scope):
        gate = self.run_gate
        if run_id != gate.config.run_id:
            raise ValueError("运行编号与租约不符")
        gate.store._require_lease(db, run_id, gate.lease_owner, gate.config.lease_epoch)
        gate.store.require_active_lineage(db, run_id)
        row = db.execute("SELECT actor_id,space_id,status,cancel_requested_at,conversation_id,selected_refs,scope_proof,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[:2] != (scope["owner_id"], scope["namespace"]) or row[2] != "RUNNING" or row[3] is not None:
            raise ValueError("运行主体、空间、状态或取消检查未通过")
        if row[7] != row[8]:
            raise ValueError("运行目标补充尚未采用")
        if row[5] is None or row[6] is None:
            raise ValueError("运行缺少会话资料范围证明")
        selected_refs = json.loads(row[5])
        if not set(source_ids).issubset(selected_refs):
            raise ValueError("来源未包含在运行资料范围")
        proof = self.scope_service.prove_in_transaction(db, row[4], selected_refs)
        if json.loads(row[6]) != json.loads(json.dumps(asdict(proof))) or (proof.owner_id, proof.namespace) != row[:2]:
            raise ValueError("运行资料范围已经变化")

    def _require_budget(self, db, run_id):
        root = self.run_gate.store.require_active_lineage(db, run_id)
        row = db.execute("SELECT max_files,max_bytes FROM agent_file_budgets WHERE root_run_id=?", (root,)).fetchone()
        if row != (self.max_files, self.max_bytes):
            raise ValueError("运行文件预算尚未配置或已经变化")

    @staticmethod
    def _uuid(value):
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError("编号格式无效")
        return value

    @staticmethod
    def _validate_sources(source_ids):
        if not isinstance(source_ids, list) or not source_ids or any(not isinstance(item, str) or not item.strip() for item in source_ids) or len(set(source_ids)) != len(source_ids):
            raise ValueError("需要明确且不重复的来源")

    def _current_scope(self, db):
        context = _context(db)
        if pending_transition(db, context["namespace"]) is not None:
            raise ValueError("当前执行空间正在切换")
        return {key: context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")}

    def _sources(self, db, source_ids, *, require_titles=True):
        self._validate_sources(source_ids)
        scope = self._current_scope(db)
        documents = [require_current_business_source(self.store, db, scope["namespace"], scope["owner_id"], item) for item in source_ids]
        if any((require_titles and (not isinstance(item.get("title"), str) or not item["title"].strip())) or not isinstance(item.get("content"), str) or not item["content"].strip() for item in documents):
            raise ValueError("来源缺少标题或正文")
        refs = [{"source_id": item["source_id"], "revision": item["version"], "locator": item["original_locator"],
                 "classification": item["source_type"], "sha256": checksum(item)} for item in documents]
        return scope, refs, documents

    def _read_bytes(self, storage_key):
        artifact_format(storage_key)
        path = self.workspace / storage_key
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()

    def _read_verified_bytes(self, storage_key, expected_size, expected_sha256):
        return read_verified_file(self.workspace, storage_key, expected_size, expected_sha256)

    def verify_meeting_brief_in_transaction(self, db, artifact_id, expected_version):
        self._uuid(artifact_id)
        if type(expected_version) is not int or expected_version < 1 or not db.in_transaction:
            raise ValueError("成果核查需要有效版本和数据库事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("成果核查需要同一数据库事务")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        record = db.execute("SELECT run_id,version,media_type,workspace,storage_key,sha256,size_bytes,source_refs,context,verification_status,status FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if record is None or record[0] != self.run_gate.config.run_id or record[1] != expected_version or record[3] != str(self.workspace) or record[9] != "VERIFIED" or record[10] not in {"VERIFIED", "PUBLISHED"}:
            raise ValueError("成果登记或版本不可核查")
        if self.workspace.is_symlink() or not self.workspace.is_dir() or self.workspace.resolve(strict=True) != self.workspace:
            raise ValueError("成果工作区不可核查")
        format_name = artifact_format(record[4])
        if record[2] != FORMATS[format_name][1]:
            raise ValueError("成果格式与媒体类型不符")
        version = db.execute("SELECT version FROM agent_artifact_versions WHERE artifact_id=?", (artifact_id,)).fetchone()
        reservation = db.execute("SELECT run_id,status,size_bytes FROM agent_file_reservations WHERE artifact_id=?", (artifact_id,)).fetchone()
        revoked = db.execute("SELECT 1 FROM agent_artifact_revocations WHERE artifact_id=?", (artifact_id,)).fetchone()
        if version != (expected_version,) or reservation != (record[0], "COMPLETED", record[6]) or revoked is not None:
            raise ValueError("成果版本、预留或撤销状态不可核查")
        scope = self._current_scope(db)
        refs = json.loads(record[7])
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str) for ref in refs):
            raise ValueError("成果来源记录不可核查")
        source_ids = [ref["source_id"] for ref in refs]
        self._require_run(db, record[0], source_ids, scope)
        self._require_budget(db, record[0])
        current_scope, current_refs, documents = self._sources(db, source_ids)
        if current_scope != json.loads(record[8]) or current_refs != refs:
            raise ValueError("成果来源或执行空间已经变化")
        if record[10] == "PUBLISHED" and db.execute("SELECT run_id,version,sha256,actor_id FROM agent_artifact_publications WHERE artifact_id=?", (artifact_id,)).fetchone() != (record[0], expected_version, record[5], scope["owner_id"]):
            raise ValueError("成果发布记录不可核查")
        content = self._read_verified_bytes(record[4], record[6], record[5])
        verify_format(format_name, content, documents)
        self._require_run(db, record[0], source_ids, scope)
        return {"artifact_id": artifact_id, "version": expected_version, "format": format_name, "sha256": record[5], "size_bytes": record[6], "file_state": "VERIFIED"}

    def release_unwritten_reservation(self, run_id, artifact_id, request_key):
        self._uuid(run_id)
        self._uuid(artifact_id)
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("成果请求编号无效")
        gate = self.run_gate
        if run_id != gate.config.run_id:
            raise ValueError("运行编号与租约不符")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            gate.store._require_lease(db, run_id, gate.lease_owner, gate.config.lease_epoch)
            scope = self._current_scope(db)
            run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run[:2] != (scope["owner_id"], scope["namespace"]) or run[3] is None or run[4] is None or run[5] not in {"RUNNING", "CANCEL_REQUESTED", "RECONCILING"}:
                raise ValueError("运行范围不可核查")
            selected = json.loads(run[3])
            proof = self.scope_service.prove_in_transaction(db, run[2], selected)
            if json.loads(run[4]) != json.loads(json.dumps(asdict(proof))):
                raise ValueError("运行资料范围已经变化")
            reservation = db.execute("SELECT root_run_id,status,size_bytes FROM agent_file_reservations WHERE artifact_id=? AND run_id=? AND request_key=?", (artifact_id, run_id, request_key)).fetchone()
            if reservation is None:
                raise ValueError("成果预留不存在")
            current, seen = run_id, set()
            while True:
                if current in seen:
                    raise ValueError("运行关系存在循环")
                seen.add(current)
                parent = db.execute("SELECT parent_run_id,actor_id,space_id FROM agent_runs WHERE run_id=?", (current,)).fetchone()
                if parent is None or parent[1:] != (scope["owner_id"], scope["namespace"]):
                    raise ValueError("运行主体或空间已经变化")
                if parent[0] is None:
                    break
                current = parent[0]
            budget = db.execute("SELECT max_files,max_bytes FROM agent_file_budgets WHERE root_run_id=?", (current,)).fetchone()
            if reservation[0] != current or budget != (self.max_files, self.max_bytes):
                raise ValueError("成果预算不可核查")
            if reservation[1] == "RELEASED":
                return {"artifact_id": artifact_id, "status": "RELEASED"}
            if reservation[1] != "RESERVED" or db.execute("SELECT 1 FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone() is not None:
                raise ValueError("已登记成果不能释放")
            pending = db.execute("SELECT workspace,format_name,content,sha256,source_refs,context FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,)).fetchone()
            if pending is None or pending[0] != str(self.workspace) or pending[1] not in FORMATS or len(pending[2]) != reservation[2] or hashlib.sha256(pending[2]).hexdigest() != pending[3] or json.loads(pending[5]) != scope:
                raise ValueError("成果预留内容不可核查")
            refs = json.loads(pending[4])
            if not refs or not {item["source_id"] for item in refs}.issubset(selected):
                raise ValueError("成果预留来源不可核查")
            current_scope, current_refs, _ = self._sources(db, [item["source_id"] for item in refs])
            if current_scope != scope or current_refs != refs:
                raise ValueError("成果预留来源已经变化")
            storage_key = artifact_id + FORMATS[pending[1]][0]
            with os.scandir(self.workspace) as entries:
                if any(entry.name == storage_key for entry in entries):
                    raise ValueError("成果文件存在，预留不能释放")
            changed = db.execute("UPDATE agent_file_reservations SET status='RELEASED' WHERE artifact_id=? AND status='RESERVED'", (artifact_id,))
            if changed.rowcount != 1:
                raise ValueError("成果预留状态已经变化")
            if db.execute("DELETE FROM agent_artifact_versions WHERE artifact_id=?", (artifact_id,)).rowcount != 1:
                raise ValueError("成果版本预留不可核查")
            if db.execute("DELETE FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,)).rowcount != 1:
                raise ValueError("成果预留内容不可核查")
            gate.store._require_lease(db, run_id, gate.lease_owner, gate.config.lease_epoch)
            return {"artifact_id": artifact_id, "status": "RELEASED"}

    def _require_previous(self, db, run_id, artifact_id, expected_version, scope):
        db.row_factory = sqlite3.Row
        old = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        db.row_factory = None
        if old is None or old["version"] != expected_version or old["status"] not in {"VERIFIED", "PUBLISHED"} or old["verification_status"] != "VERIFIED":
            raise ValueError("成果前一版本已经变化或不可读取")
        old_workspace = self.workspace if self.mapping is None else self.mapping.open(old["run_id"])
        if old["workspace"] != str(old_workspace):
            raise ValueError("成果前一版本目录不可核查")
        prior = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status FROM agent_runs WHERE run_id=?", (old["run_id"],)).fetchone()
        current = db.execute("SELECT conversation_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if prior is None or current is None or prior[:2] != (scope["owner_id"], scope["namespace"]) or prior[2] != current[0] or prior[3] is None or prior[4] is None or prior[5] not in {"RUNNING", "SUCCEEDED"}:
            raise ValueError("成果前一版本运行范围不可核查")
        old_refs = json.loads(old["source_refs"])
        old_ids = [ref["source_id"] for ref in old_refs]
        self._require_run(db, run_id, old_ids, scope)
        selected = json.loads(prior[3])
        proof = self.scope_service.prove_in_transaction(db, prior[2], selected)
        if not set(old_ids).issubset(selected) or json.loads(prior[4]) != json.loads(json.dumps(asdict(proof))):
            raise ValueError("成果前一版本会话范围已经变化")
        old_scope, current_refs, _ = self._sources(db, old_ids)
        if old_scope != json.loads(old["context"]) or current_refs != old_refs:
            raise ValueError("成果前一版本来源已经变化")
        if old["media_type"] != FORMATS[artifact_format(old["storage_key"])][1]:
            raise ValueError("成果前一版本媒体类型不符")
        read_verified_file(old_workspace, old["storage_key"], old["size_bytes"], old["sha256"])
        if old["status"] == "PUBLISHED":
            publication = db.execute("SELECT run_id,version,sha256,actor_id FROM agent_artifact_publications WHERE artifact_id=?", (artifact_id,)).fetchone()
            if publication != (old["run_id"], expected_version, old["sha256"], scope["owner_id"]):
                raise ValueError("成果发布记录不可核查")

    def create_meeting_brief(self, run_id, source_ids, *, request_key, format_name="DOCX", previous_artifact_id=None, expected_version=None):
        self._uuid(run_id)
        self._validate_sources(source_ids)
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("成果请求编号无效")
        if format_name not in FORMATS:
            raise ValueError("成果格式无效")
        if previous_artifact_id is None:
            if expected_version is not None:
                raise ValueError("成果前一版本无效")
        else:
            self._uuid(previous_artifact_id)
            if type(expected_version) is not int or expected_version <= 0:
                raise ValueError("成果前一版本无效")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            scope = self._current_scope(db)
            self._require_run(db, run_id, source_ids, scope)
            scope, refs, documents = self._sources(db, source_ids)
            self._require_run(db, run_id, source_ids, scope)
            content = create_format(format_name, documents)
            artifact_id = str(uuid4())
            digest = hashlib.sha256(json.dumps({"run_id": run_id, "source_refs": refs, "format": format_name, "previous_artifact_id": previous_artifact_id, "expected_version": expected_version}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
            self._require_budget(db, run_id)
            self._require_run(db, run_id, source_ids, scope)
            previous = self.run_gate.store.reserve_file_in_transaction(db, run_id, self.run_gate.lease_owner, self.run_gate.config.lease_epoch, request_key, digest, artifact_id, len(content), allow_reserved=True)
            if previous is not None:
                reservation = db.execute("SELECT status,size_bytes FROM agent_file_reservations WHERE artifact_id=? AND run_id=? AND request_key=?", (previous, run_id, request_key)).fetchone()
                if reservation is None:
                    raise ValueError("成果预留不可核查")
                if reservation[0] == "RESERVED":
                    pending = db.execute("SELECT workspace,format_name,content,sha256,source_refs,context FROM agent_artifact_pending WHERE artifact_id=?", (previous,)).fetchone()
                    link = db.execute("SELECT version,previous_artifact_id FROM agent_artifact_versions WHERE artifact_id=?", (previous,)).fetchone()
                    if pending is None or pending[0] != str(self.workspace) or pending[1] != format_name or len(pending[2]) != reservation[1] or hashlib.sha256(pending[2]).hexdigest() != pending[3] or json.loads(pending[4]) != refs or json.loads(pending[5]) != scope or link != (1 if expected_version is None else expected_version + 1, previous_artifact_id):
                        raise ValueError("成果预留内容不可核查")
                    if previous_artifact_id is not None:
                        self._require_previous(db, run_id, previous_artifact_id, expected_version, scope)
                    return self._save_brief(db, previous, run_id, request_key, source_ids, scope, refs, documents, format_name, pending[2], link[0])
                db.row_factory = sqlite3.Row
                record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=? AND run_id=?", (previous, run_id)).fetchone()
                db.row_factory = None
                if record is None or record["workspace"] != str(self.workspace) or record["media_type"] != FORMATS[format_name][1] or artifact_format(record["storage_key"]) != format_name or record["status"] not in {"VERIFIED", "PUBLISHED"} or record["verification_status"] != "VERIFIED" or json.loads(record["source_refs"]) != refs or json.loads(record["context"]) != scope:
                    raise ValueError("原成果登记不可核查")
                link = db.execute("SELECT version,previous_artifact_id FROM agent_artifact_versions WHERE artifact_id=?", (previous,)).fetchone()
                if link != (record["version"], previous_artifact_id) or record["version"] != (1 if expected_version is None else expected_version + 1):
                    raise ValueError("原成果版本关系不可核查")
                if record["status"] == "PUBLISHED":
                    publication = db.execute("SELECT run_id,version,sha256,actor_id FROM agent_artifact_publications WHERE artifact_id=?", (previous,)).fetchone()
                    if publication != (run_id, record["version"], record["sha256"], scope["owner_id"]):
                        raise ValueError("成果发布记录不可核查")
                self._read_verified_bytes(record["storage_key"], record["size_bytes"], record["sha256"])
                self._require_run(db, run_id, source_ids, scope)
                metadata = {key: (json.loads(record[key]) if key == "source_refs" else record[key]) for key in ("artifact_id", "run_id", "version", "media_type", "storage_key", "sha256", "size_bytes", "source_refs", "verification_status", "status")}
                self._record_candidate(db, metadata)
                return metadata
            version = 1
            series_id = artifact_id
            if previous_artifact_id is not None:
                self._require_previous(db, run_id, previous_artifact_id, expected_version, scope)
                old_link = db.execute("SELECT series_id,version FROM agent_artifact_versions WHERE artifact_id=?", (previous_artifact_id,)).fetchone()
                if old_link is None or old_link[1] != expected_version or db.execute("SELECT 1 FROM agent_artifact_versions WHERE previous_artifact_id=?", (previous_artifact_id,)).fetchone() is not None:
                    raise ValueError("成果版本已经变化")
                series_id, version = old_link[0], expected_version + 1
            db.execute("INSERT INTO agent_artifact_versions VALUES (?,?,?,?)", (artifact_id, series_id, version, previous_artifact_id))
            db.execute("INSERT INTO agent_artifact_pending VALUES (?,?,?,?,?,?,?)", (artifact_id, str(self.workspace), format_name, content, hashlib.sha256(content).hexdigest(), json.dumps(refs, ensure_ascii=False), json.dumps(scope, ensure_ascii=False)))
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            scope = self._current_scope(db)
            self._require_run(db, run_id, source_ids, scope)
            current_scope, current_refs, _ = self._sources(db, source_ids)
            if current_scope != scope or current_refs != refs:
                raise ValueError("成果来源或执行空间已经变化")
            self._require_budget(db, run_id)
            if previous_artifact_id is not None:
                self._require_previous(db, run_id, previous_artifact_id, expected_version, scope)
            return self._save_brief(db, artifact_id, run_id, request_key, source_ids, scope, refs, documents, format_name, content, version)

    def _record_candidate(self, db, metadata):
        payload = {key: metadata[key] for key in ("artifact_id", "version", "media_type", "sha256")}
        rows = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND type='ARTIFACT_CANDIDATE' AND json_extract(payload,'$.artifact_id')=?", (metadata["run_id"], metadata["artifact_id"])).fetchall()
        if rows:
            if len(rows) != 1 or json.loads(rows[0][0]) != payload:
                raise ValueError("成果运行事件不可核查")
            return
        self.run_gate.store._record_event(db, metadata["run_id"], "ARTIFACT_CANDIDATE", payload,
                                          self.run_gate.config.lease_epoch, "artifact:" + metadata["artifact_id"])

    def _save_brief(self, db, artifact_id, run_id, request_key, source_ids, scope, refs, documents, format_name, content, version):
        storage_key = artifact_id + FORMATS[format_name][0]
        content = store_exact_file(self.workspace, storage_key, content)
        verify_format(format_name, content, documents)
        metadata = {"artifact_id": artifact_id, "run_id": run_id, "version": version,
                    "media_type": FORMATS[format_name][1],
                    "storage_key": storage_key, "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content), "source_refs": refs,
                    "verification_status": "VERIFIED", "status": "VERIFIED"}
        self._require_run(db, run_id, source_ids, scope)
        from agent_source_history import AgentSourceHistory
        run = db.execute("SELECT conversation_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        proof = self.scope_service.prove_in_transaction(db, run[0], source_ids)
        AgentSourceHistory(self.run_gate.store, self.scope_service).retain_citations_in_transaction(db, proof, refs, run_id=run_id)
        db.execute("INSERT INTO agent_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (artifact_id, run_id, version, metadata["media_type"], str(self.workspace), storage_key, metadata["sha256"], len(content), json.dumps(refs, ensure_ascii=False), json.dumps(scope, ensure_ascii=False), "VERIFIED", "VERIFIED"))
        result = db.execute("UPDATE agent_file_reservations SET status='COMPLETED' WHERE run_id=? AND request_key=? AND artifact_id=? AND status='RESERVED'", (run_id, request_key, artifact_id))
        if result.rowcount != 1:
            raise ValueError("成果请求预留不可核查")
        deleted = db.execute("DELETE FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,))
        if deleted.rowcount != 1:
            raise ValueError("成果预留内容不可核查")
        self._record_candidate(db, metadata)
        from agent_artifact_goal import AgentArtifactGoal
        AgentArtifactGoal.record_in_transaction(db, run_id, artifact_id)
        return metadata

    def read_meeting_brief(self, artifact_id):
        self._uuid(artifact_id)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.row_factory = sqlite3.Row
            record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if record is None or record["workspace"] != str(self.workspace) or record["status"] not in {"VERIFIED", "PUBLISHED"} or record["verification_status"] != "VERIFIED":
                raise ValueError("成果不存在")
            if record["media_type"] != FORMATS[artifact_format(record["storage_key"])][1]:
                raise ValueError("成果媒体类型不符")
            refs, expected_scope = json.loads(record["source_refs"]), json.loads(record["context"])
            db.row_factory = None
            scope = self._current_scope(db)
            if record["status"] == "PUBLISHED":
                publication = db.execute("SELECT run_id,version,sha256,actor_id FROM agent_artifact_publications WHERE artifact_id=?", (artifact_id,)).fetchone()
                if publication != (record["run_id"], record["version"], record["sha256"], scope["owner_id"]):
                    raise ValueError("成果发布记录不可核查")
            self._require_run(db, record["run_id"], [item["source_id"] for item in refs], scope)
            scope, current_refs, _ = self._sources(db, [item["source_id"] for item in refs])
            if scope != expected_scope or current_refs != refs:
                raise ValueError("成果来源或执行空间已经变化")
            self._require_run(db, record["run_id"], [item["source_id"] for item in refs], scope)
            self._require_budget(db, record["run_id"])
            content = self._read_verified_bytes(record["storage_key"], record["size_bytes"], record["sha256"])
            self._require_run(db, record["run_id"], [item["source_id"] for item in refs], scope)
            return content
