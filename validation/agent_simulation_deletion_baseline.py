import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from agent_memory_deletion_log import inspect_memory_deletion_history_in_transaction
from agent_run_store import utc_now
from agent_simulation_snapshot import SIMULATION_ROOT
from boss_simulation_api import _context
from controls import ControlStore
from hermes_source_invalidation import verify_source_withdrawals_in_transaction


VERSION = "upgrade2_simulation_deletion_baseline_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")
KINDS = ("source_withdrawal_event", "memory_deletion_event")


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class SimulationDeletionBaseline:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, ControlStore) or store.path.is_symlink() or not store.path.resolve(strict=True).is_relative_to(SIMULATION_ROOT.resolve()):
            raise ValueError("删除基线仅允许独立模拟数据库")
        self.store = store
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is None:
                if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('agent_simulation_deletion_baselines','agent_simulation_deletion_baseline_events','agent_simulation_deletion_baseline_snapshots')").fetchone() is not None:
                    raise ValueError("删除基线迁移尚未安装")
                db.executescript("BEGIN IMMEDIATE;\n" + MIGRATION.read_text(encoding="utf-8"))
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, hashlib.sha256(MIGRATION.read_bytes()).hexdigest()))
            self._schema(db)

    @staticmethod
    def _schema(db):
        from agent_simulation_migration_install import _catalog
        match = [entry for entry in _catalog() if entry[0] == VERSION]
        if len(match) != 1 or db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (match[0][3],):
            raise ValueError("删除基线迁移摘要不可核查")
        for (kind, name), sql in match[0][4].items():
            if db.execute("SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind, name)).fetchone() != (sql,):
                raise ValueError("删除基线迁移对象不可核查")

    def _events(self, db, namespace):
        source = verify_source_withdrawals_in_transaction(self.store, db, namespace)
        memory = inspect_memory_deletion_history_in_transaction(self.store, db, namespace)
        if source["missing_source_ids"] or memory["pending"]:
            raise ValueError("删除记录存在待核查事项")
        rows = db.execute("SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN (?,?) ORDER BY kind,id", (namespace, *KINDS)).fetchall()
        return [(kind, identifier, hashlib.sha256(body.encode("utf-8")).hexdigest()) for kind, identifier, body in rows]

    def capture(self, request_key):
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 200:
            raise ValueError("删除基线请求编号无效")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._schema(db)
            namespace = _context(db)["namespace"]
            events = self._events(db, namespace)
            baselines = db.execute("SELECT baseline_id,event_count,events_sha256 FROM agent_simulation_deletion_baselines WHERE namespace=?", (namespace,)).fetchall()
            for baseline_id, count, digest in baselines:
                self._verify_saved(db, baseline_id, count, digest, events)
            row = db.execute("SELECT baseline_id,event_count,events_sha256 FROM agent_simulation_deletion_baselines WHERE namespace=? AND request_key=?", (namespace, request_key)).fetchone()
            if row is not None:
                if row[1:] != (len(events), _digest(events)):
                    raise ValueError("原删除基线内容已经变化")
                self._verify_saved(db, row[0], row[1], row[2], events)
                return {"baseline_id": row[0], "created": False, "event_count": len(events), "history_complete": False, "restore_state": "BLOCKED"}
            identifier = str(uuid4())
            db.execute("INSERT INTO agent_simulation_deletion_baselines VALUES (?,?,?,?,?,?)", (identifier, namespace, request_key, len(events), _digest(events), utc_now().isoformat()))
            db.executemany("INSERT INTO agent_simulation_deletion_baseline_events VALUES (?,?,?,?)", [(identifier, *event) for event in events])
            return {"baseline_id": identifier, "created": True, "event_count": len(events), "history_complete": False, "restore_state": "BLOCKED"}

    @staticmethod
    def _verify_saved(db, identifier, count, digest, current):
        rows = db.execute("SELECT kind,event_id,body_sha256 FROM agent_simulation_deletion_baseline_events WHERE baseline_id=? ORDER BY kind,event_id", (identifier,)).fetchall()
        if len(rows) != count or _digest(rows) != digest:
            raise ValueError("删除基线记录不可核查")
        existing = {(kind, event_id): sha for kind, event_id, sha in current}
        if any(existing.get((kind, event_id)) != sha for kind, event_id, sha in rows):
            raise ValueError("删除基线事件缺失或内容变化")
        return len(current) - len(rows)

    def inspect(self, baseline_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.inspect_in_transaction(db, baseline_id)

    def inspect_in_transaction(self, db, baseline_id):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("删除基线核查需要同一数据库事务")
        self._schema(db)
        namespace = _context(db)["namespace"]
        row = db.execute("SELECT event_count,events_sha256 FROM agent_simulation_deletion_baselines WHERE baseline_id=? AND namespace=?", (baseline_id, namespace)).fetchone()
        if row is None:
            raise ValueError("删除基线不存在")
        events = self._events(db, namespace)
        added = self._verify_saved(db, baseline_id, row[0], row[1], events)
        return {"baseline_id": baseline_id, "baseline_events": row[0], "new_events": added, "history_complete": False, "restore_state": "BLOCKED"}

    def bind_snapshot(self, snapshots, request_key, baseline_id):
        from agent_simulation_snapshot import AgentSimulationSnapshot
        if not isinstance(snapshots, AgentSimulationSnapshot) or snapshots.store.path.resolve() != self.store.path.resolve():
            raise ValueError("删除基线需要同一模拟快照服务")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            checked = self.inspect_in_transaction(db, baseline_id)
            if checked["new_events"]:
                raise ValueError("删除基线建立后存在新事件")
            namespace = _context(db)["namespace"]
            row = db.execute("SELECT checkpoint_request_key,checkpoint_id,snapshot_name,snapshot_sha256 FROM agent_simulation_snapshots WHERE namespace=? AND request_key=?", (namespace, request_key)).fetchone()
            if row is None:
                raise ValueError("模拟快照记录不存在")
            snapshots.checkpoint.verify_in_transaction(db, row[0], row[1])
            path = snapshots.directory / row[2]
            if path.is_symlink() or not path.is_file() or path.parent.resolve() != snapshots.directory:
                raise ValueError("模拟快照文件不可核查")
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != row[3]:
                    raise ValueError("模拟快照摘要不符")
            live_baseline = db.execute("SELECT event_count,events_sha256 FROM agent_simulation_deletion_baselines WHERE namespace=? AND baseline_id=?", (namespace, baseline_id)).fetchone()
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as snapshot:
                saved_baseline = snapshot.execute("SELECT event_count,events_sha256 FROM agent_simulation_deletion_baselines WHERE namespace=? AND baseline_id=?", (namespace, baseline_id)).fetchone()
                if saved_baseline is None or saved_baseline != live_baseline:
                    raise ValueError("模拟快照缺少匹配的删除基线")
                snapshot_rows = snapshot.execute("SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN (?,?) ORDER BY kind,id", (namespace, *KINDS)).fetchall()
                snapshot_events = [(kind, identifier, hashlib.sha256(body.encode("utf-8")).hexdigest()) for kind, identifier, body in snapshot_rows]
                if self._verify_saved(snapshot, baseline_id, saved_baseline[0], saved_baseline[1], snapshot_events) or snapshot_events != self._events(db, namespace):
                    raise ValueError("模拟快照删除基线事件不匹配")
            existing = db.execute("SELECT checkpoint_id,snapshot_sha256,baseline_id FROM agent_simulation_deletion_baseline_snapshots WHERE namespace=? AND snapshot_request_key=?", (namespace, request_key)).fetchone()
            expected = (row[1], row[3], baseline_id)
            if existing is not None:
                if existing != expected:
                    raise ValueError("模拟快照基线关联已经变化")
                return {"baseline_id": baseline_id, "created": False, "restore_state": "BLOCKED"}
            db.execute("INSERT INTO agent_simulation_deletion_baseline_snapshots VALUES (?,?,?,?,?)", (namespace, request_key, *expected))
            return {"baseline_id": baseline_id, "created": True, "restore_state": "BLOCKED"}
