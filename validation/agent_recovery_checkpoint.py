import hashlib
import json
from pathlib import Path

from filelock import FileLock

from agent_recovery_preflight import AgentRecoveryPreflight
from agent_run_store import RunStore, utc_now


VERSION = "upgrade2_recovery_checkpoint_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentRecoveryCheckpoint:
    def __init__(self, preflight, *, allow_migration=False):
        if not isinstance(preflight, AgentRecoveryPreflight):
            raise ValueError("需要当前恢复状态核查")
        self.preflight = preflight
        self.store = preflight.store
        RunStore(self.store.path, allow_migration=False)
        source = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with FileLock(str(self.store.path) + ".migration.lock", timeout=10), self.store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("恢复检查点迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_recovery_checkpoints'").fetchone() is not None:
                raise ValueError("恢复检查点迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def _state(self, db):
        state = self.preflight.current_state_in_transaction(db)
        if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
            raise ValueError("恢复检查点迁移摘要不符")
        return state

    def capture_in_transaction(self, db, request_key):
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200:
            raise ValueError("恢复检查点请求编号无效")
        state = self._state(db)
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        identity = json.dumps([VERSION, state["namespace"], request_key, encoded], ensure_ascii=False, separators=(",", ":"))
        checkpoint_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        old = db.execute("SELECT checkpoint_id,state_json FROM agent_recovery_checkpoints WHERE namespace=? AND request_key=?", (state["namespace"], request_key)).fetchone()
        if old is not None:
            if old != (checkpoint_id, encoded):
                raise ValueError("恢复检查点对应的当前状态已经变化")
            return {"checkpoint_id": checkpoint_id, "created": False, "restore_state": "BLOCKED"}
        db.execute("INSERT INTO agent_recovery_checkpoints VALUES (?,?,?,?,?)", (state["namespace"], request_key, checkpoint_id, encoded, utc_now().isoformat()))
        return {"checkpoint_id": checkpoint_id, "created": True, "restore_state": "BLOCKED"}

    def verify_in_transaction(self, db, request_key, checkpoint_id):
        if not isinstance(request_key, str) or not request_key or not isinstance(checkpoint_id, str) or len(checkpoint_id) != 64:
            raise ValueError("恢复检查点标识无效")
        state = self._state(db)
        old = db.execute("SELECT checkpoint_id,state_json FROM agent_recovery_checkpoints WHERE namespace=? AND request_key=?", (state["namespace"], request_key)).fetchone()
        if old is None or old[0] != checkpoint_id:
            raise ValueError("恢复检查点不存在或不匹配")
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        identity = json.dumps([VERSION, state["namespace"], request_key, encoded], ensure_ascii=False, separators=(",", ":"))
        expected = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        if old != (expected, encoded):
            raise ValueError("恢复检查点对应的当前状态已经变化")
        return {"checkpoint_id": checkpoint_id, "restore_state": "BLOCKED"}
