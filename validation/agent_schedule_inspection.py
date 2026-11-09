import hashlib
import math
from datetime import datetime, timedelta
from pathlib import Path

from filelock import FileLock
from nanobot.cron.service import CronService

from agent_run_store import RunStore, utc_now
from boss_execution_transition import pending_transition
from boss_simulation_api import _context
from controls import ControlStore


VERSION = "upgrade2_schedule_inspection_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


def inspect_legacy_cron(cron):
    if not isinstance(cron, CronService):
        raise ValueError("需要实际 CronService 对象")
    stopped = not cron._running and cron._timer_task is None and cron._active_executions == 0
    return {"local_state": "STOPPED" if stopped else "ACTIVE_OR_DRAINING", "other_instances": "UNVERIFIED"}


class AgentScheduleInspectionLease:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, ControlStore):
            raise ValueError("需要业务计划数据库")
        self.store = store
        RunStore(store.path, allow_migration=False)
        source = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("调度核查租约迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_schedule_inspection_leases'").fetchone() is not None:
                raise ValueError("调度核查租约迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def acquire(self, owner, ttl):
        if not isinstance(owner, str) or not owner or isinstance(ttl, bool) or not isinstance(ttl, (float, int)) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("调度核查租约参数无效")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
                raise ValueError("调度核查租约迁移摘要不符")
            context = _context(db)
            namespace = context["namespace"]
            if pending_transition(db, namespace) is not None:
                raise ValueError("执行空间正在切换")
            current = db.execute("SELECT owner,epoch,expires_at FROM agent_schedule_inspection_leases WHERE namespace=?", (namespace,)).fetchone()
            now = utc_now()
            if current is not None and datetime.fromisoformat(current[2]) > now:
                if current[0] != owner:
                    raise ValueError("调度核查租约已被占用")
                return {"owner": owner, "epoch": current[1], "expires_at": current[2], "purpose": "INSPECTION_ONLY"}
            epoch = current[1] + 1 if current else 1
            expires = (now + timedelta(seconds=ttl)).isoformat()
            db.execute("INSERT INTO agent_schedule_inspection_leases VALUES (?,?,?,?,'INSPECTION_ONLY') ON CONFLICT(namespace) DO UPDATE SET owner=excluded.owner,epoch=excluded.epoch,expires_at=excluded.expires_at", (namespace, owner, epoch, expires))
            return {"owner": owner, "epoch": epoch, "expires_at": expires, "purpose": "INSPECTION_ONLY"}

    def require_current_in_transaction(self, db, owner, epoch):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("调度核查租约需要同一数据库事务")
        db.execute("UPDATE spaces SET active=active WHERE 0")
        if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
            raise ValueError("调度核查租约迁移摘要不符")
        context = _context(db)
        if pending_transition(db, context["namespace"]) is not None:
            raise ValueError("执行空间正在切换")
        row = db.execute("SELECT owner,epoch,expires_at,purpose FROM agent_schedule_inspection_leases WHERE namespace=?", (context["namespace"],)).fetchone()
        if row is None or row[0] != owner or row[1] != epoch or datetime.fromisoformat(row[2]) <= utc_now() or row[3] != "INSPECTION_ONLY":
            raise ValueError("调度核查租约已经失效")
        return "INSPECTION_ONLY"
