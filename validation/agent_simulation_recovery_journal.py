import hashlib
from pathlib import Path
from uuid import UUID

from filelock import FileLock

from agent_run_store import utc_now
from agent_simulation_snapshot import AgentSimulationSnapshot


VERSION = "upgrade2_simulation_recovery_journal_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentSimulationRecoveryJournal:
    def __init__(self, snapshots, *, allow_migration=False):
        if not isinstance(snapshots, AgentSimulationSnapshot):
            raise ValueError("需要独立模拟快照服务")
        self.snapshots = snapshots
        self.store = snapshots.store
        source = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with FileLock(str(self.store.path) + ".migration.lock", timeout=10), self.store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("模拟恢复记录迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_simulation_recovery_requests'").fetchone() is not None:
                raise ValueError("模拟恢复记录迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def record_blocked(self, request_key, target_id, checked):
        if not isinstance(request_key, str) or not request_key or not isinstance(target_id, str) or str(UUID(target_id)) != target_id:
            raise ValueError("模拟恢复请求参数无效")
        if not isinstance(checked, dict) or checked.get("restore_state") != "BLOCKED" or checked.get("reason") != "DELETION_LEDGER_COMPLETENESS_UNVERIFIED":
            raise ValueError("模拟恢复核查状态无效")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
            if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (digest,):
                raise ValueError("模拟恢复记录迁移摘要不符")
            state = self.snapshots.checkpoint.preflight.current_state_in_transaction(db)
            namespace = state["namespace"]
            snapshot = db.execute("SELECT checkpoint_request_key,checkpoint_id,snapshot_name,snapshot_sha256 FROM agent_simulation_snapshots WHERE namespace=? AND request_key=?", (namespace, request_key)).fetchone()
            if snapshot is None or (snapshot[1], snapshot[2], snapshot[3]) != (checked.get("checkpoint_id"), checked.get("snapshot_name"), checked.get("sha256")):
                raise ValueError("模拟恢复快照记录不符")
            self.snapshots.checkpoint.verify_in_transaction(db, snapshot[0], snapshot[1])
            path = self.snapshots.directory / snapshot[2]
            sidecars = (Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal"))
            if path.parent.resolve() != self.snapshots.directory or path.is_symlink() or not path.is_file() or any(item.exists() for item in sidecars):
                raise ValueError("模拟恢复快照文件不可核查")
            with path.open("rb") as content:
                if hashlib.file_digest(content, "sha256").hexdigest() != snapshot[3]:
                    raise ValueError("模拟恢复快照摘要已经变化")
            expected = (snapshot[2], snapshot[3], snapshot[1], target_id, "BLOCKED")
            old = db.execute("SELECT snapshot_name,snapshot_sha256,checkpoint_id,target_id,state FROM agent_simulation_recovery_requests WHERE namespace=? AND request_key=?", (namespace, request_key)).fetchone()
            if old is not None:
                if old != expected:
                    raise ValueError("模拟恢复请求内容已经变化")
                return {"state": "BLOCKED", "created": False}
            db.execute("INSERT INTO agent_simulation_recovery_requests VALUES (?,?,?,?,?,?,?,?)", (namespace, request_key, *expected, utc_now().isoformat()))
            return {"state": "BLOCKED", "created": True}

    def inspect_target(self, target_id):
        if not isinstance(target_id, str) or str(UUID(target_id)) != target_id:
            raise ValueError("模拟恢复目录标识无效")
        root = self.snapshots.directory / "recovery"
        target = root / target_id
        if root.is_symlink() or target.is_symlink():
            raise ValueError("模拟恢复目录不可核查")
        if target.exists():
            return {"state": "UNVERIFIED", "cleanup": "BLOCKED"}
        return {"state": "ABSENT", "cleanup": "NONE"}
