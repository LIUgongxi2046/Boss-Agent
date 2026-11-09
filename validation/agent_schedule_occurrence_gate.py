import hashlib
from pathlib import Path

from filelock import FileLock

from agent_run_store import RunStore, utc_now
from boss_execution_transition import pending_transition
from boss_simulation_api import _context
from controls import ControlStore
from hermes_schedule_adapter import aware_instant, stable_occurrence_id


VERSION = "upgrade2_schedule_occurrence_gate_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentScheduleOccurrenceGate:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, ControlStore):
            raise ValueError("需要业务计划数据库")
        self.store = store
        RunStore(store.path, allow_migration=False)
        source = MIGRATION.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("计划发生门禁迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_schedule_occurrence_gate'").fetchone() is not None:
                raise ValueError("计划发生门禁迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source.decode("utf-8"))
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def claim_in_transaction(self, db, plan_id, plan_version, occurrence_at):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("计划发生门禁需要同一数据库事务")
        db.execute("UPDATE spaces SET active=active WHERE 0")
        if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
            raise ValueError("计划发生门禁迁移摘要不符")
        context = _context(db)
        if pending_transition(db, context["namespace"]) is not None:
            raise ValueError("执行空间正在切换")
        plan = self.store.get(db, context["namespace"], "owner_plan", plan_id)
        if plan.get("plan_id") != plan_id or plan.get("version") != plan_version or plan.get("owner_id") != context["owner_id"]:
            raise ValueError("计划身份或版本已经变化")
        instant = aware_instant(occurrence_at).isoformat()
        key = (context["namespace"], context["dataset_id"], context["dataset_version"], plan_id, plan_version, instant)
        occurrence_id = stable_occurrence_id(*key)
        cursor = db.execute("INSERT INTO agent_schedule_occurrence_gate VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(occurrence_id) DO NOTHING", (occurrence_id, *key, utc_now().isoformat()))
        if cursor.rowcount == 0:
            row = db.execute("SELECT namespace,dataset_id,dataset_version,plan_id,plan_version,occurrence_at FROM agent_schedule_occurrence_gate WHERE occurrence_id=?", (occurrence_id,)).fetchone()
            if row != key:
                raise ValueError("计划发生编号与记录不符")
        return {"occurrence_id": occurrence_id, "claimed": cursor.rowcount == 1}
