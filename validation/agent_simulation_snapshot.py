import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_run_store import utc_now


VERSION = "upgrade2_simulation_snapshot_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")
def _simulation_root():
    default = Path(__file__).resolve().parent.parent / ".work" / "upgrade2-u2-08-simulated"
    configured = os.environ.get("BOSS_SIMULATION_ROOT")
    if configured is None:
        return default
    package = Path(__file__).resolve().parent
    if package.name != "boss_agent_runtime" or package.parent.name != "site-packages":
        raise ValueError("模拟资料根目录配置仅适用于独立安装")
    root = Path(configured)
    if not root.is_absolute() or root.name != "upgrade2-u2-08-simulated" or root.parent.name != ".work":
        raise ValueError("模拟资料根目录配置无效")
    from application_paths import _reject_symlink_components
    _reject_symlink_components(root)
    if not root.is_dir() or root.stat().st_uid != os.getuid():
        raise ValueError("模拟资料根目录必须由当前用户拥有")
    return root


SIMULATION_ROOT = _simulation_root()


class AgentSimulationSnapshot:
    def __init__(self, checkpoint, directory, *, allow_migration=False):
        if not isinstance(checkpoint, AgentRecoveryCheckpoint):
            raise ValueError("需要当前恢复检查点")
        self.checkpoint = checkpoint
        self.store = checkpoint.store
        self.directory = Path(directory).resolve()
        root = SIMULATION_ROOT.resolve()
        if not self.store.path.resolve().is_relative_to(root) or not self.directory.is_relative_to(root) or not self.directory.is_dir():
            raise ValueError("仅允许独立模拟目录")
        source = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with FileLock(str(self.store.path) + ".migration.lock", timeout=10), self.store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("模拟快照迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_simulation_snapshots'").fetchone() is not None:
                raise ValueError("模拟快照迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def create(self, request_key, checkpoint_request_key, checkpoint_id):
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200:
            raise ValueError("模拟快照请求编号无效")
        with self.store.connect() as current:
            current.execute("BEGIN IMMEDIATE")
            if current.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
                raise ValueError("模拟快照迁移摘要不符")
            self.checkpoint.verify_in_transaction(current, checkpoint_request_key, checkpoint_id)
            state = self.checkpoint.preflight.current_state_in_transaction(current)
            namespace = state["namespace"]
            schema = current.execute("SELECT version,sha256 FROM agent_schema_migrations ORDER BY version").fetchall()
            old = current.execute("SELECT checkpoint_request_key,checkpoint_id,snapshot_name,snapshot_sha256,manifest_json FROM agent_simulation_snapshots WHERE namespace=? AND request_key=?", (namespace, request_key)).fetchone()
            if old is not None:
                if old[:2] != (checkpoint_request_key, checkpoint_id):
                    raise ValueError("模拟快照请求内容已经变化")
                path = self.directory / old[2]
                sidecars = (Path(str(path) + "-wal"), Path(str(path) + "-journal"), Path(str(path) + "-shm"))
                if path.parent.resolve() != self.directory or path.is_symlink() or not path.is_file() or any(item.exists() for item in sidecars):
                    raise ValueError("模拟快照文件缺少或摘要不符")
                with path.open("rb") as content:
                    if hashlib.file_digest(content, "sha256").hexdigest() != old[3]:
                        raise ValueError("模拟快照文件缺少或摘要不符")
                manifest = json.loads(old[4])
                if manifest["schema_versions"] != [list(row) for row in schema]:
                    raise ValueError("模拟快照迁移版本已经变化")
                return {"snapshot_name": old[2], "sha256": old[3], "manifest": manifest, "created": False, "restore_state": "BLOCKED"}
            name = "simulation-" + uuid4().hex + ".sqlite"
            path = self.directory / name
            path.touch(exist_ok=False, mode=0o600)
            with closing(sqlite3.connect(self.store.path)) as source, closing(sqlite3.connect(path)) as target:
                source.backup(target)
                if target.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
                    raise ValueError("模拟快照日志状态不可核查")
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as snapshot:
                if snapshot.execute("PRAGMA integrity_check").fetchone() != ("ok",) or snapshot.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("模拟快照完整性核查失败")
                if snapshot.execute("SELECT version,sha256 FROM agent_schema_migrations ORDER BY version").fetchall() != schema:
                    raise ValueError("模拟快照迁移版本不符")
                if snapshot.execute("SELECT checkpoint_id FROM agent_recovery_checkpoints WHERE namespace=? AND request_key=?", (namespace, checkpoint_request_key)).fetchone() != (checkpoint_id,):
                    raise ValueError("模拟快照缺少当前检查点")
            with path.open("rb") as content:
                digest = hashlib.file_digest(content, "sha256").hexdigest()
            manifest = {"namespace": namespace, "owner_id": state["owner_id"], "dataset_id": state["dataset_id"], "dataset_version": state["dataset_version"], "checkpoint_id": checkpoint_id, "state_sha256": state["state_sha256"], "schema_versions": schema, "coverage": ["business_sqlite"], "restore_state": "BLOCKED"}
            encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            current.execute("INSERT INTO agent_simulation_snapshots VALUES (?,?,?,?,?,?,?,?)", (namespace, request_key, checkpoint_request_key, checkpoint_id, name, digest, encoded, utc_now().isoformat()))
            return {"snapshot_name": name, "sha256": digest, "manifest": json.loads(encoded), "created": True, "restore_state": "BLOCKED"}
