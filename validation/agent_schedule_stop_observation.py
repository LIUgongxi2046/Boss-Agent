import hashlib
import os
from pathlib import Path

from filelock import FileLock
from nanobot.cron.service import CronService

from agent_run_store import utc_now
from agent_schedule_inspection import AgentScheduleInspectionLease, inspect_legacy_cron
from agent_simulation_snapshot import SIMULATION_ROOT
from boss_simulation_api import _context


VERSION = "upgrade2_schedule_stop_observation_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentScheduleStopObservation:
    def __init__(self, lease, *, allow_migration=False):
        if not isinstance(lease, AgentScheduleInspectionLease) or not lease.store.path.resolve().is_relative_to(SIMULATION_ROOT.resolve()):
            raise ValueError("需要独立模拟调度核查租约")
        self.lease = lease
        self.store = lease.store
        source = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with FileLock(str(self.store.path) + ".migration.lock", timeout=10), self.store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("调度停止观察迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_schedule_stop_observations'").fetchone() is not None:
                raise ValueError("调度停止观察迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def record_in_transaction(self, db, request_key, owner, epoch, cron):
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200 or not isinstance(cron, CronService):
            raise ValueError("调度停止观察参数无效")
        path = Path(cron.store_path).resolve()
        if not path.is_relative_to(SIMULATION_ROOT.resolve()):
            raise ValueError("仅允许独立模拟调度对象")
        self.lease.require_current_in_transaction(db, owner, epoch)
        if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
            raise ValueError("调度停止观察迁移摘要不符")
        if inspect_legacy_cron(cron)["local_state"] != "STOPPED":
            raise ValueError("当前调度对象尚未停止")
        namespace = _context(db)["namespace"]
        expected = (owner, epoch, os.getpid(), str(path), "LOCAL_OBJECT_ONLY")
        previous = db.execute("SELECT lease_owner,lease_epoch,observer_pid,cron_path,scope,observed_at FROM agent_schedule_stop_observations WHERE namespace=? AND request_key=?", (namespace, request_key)).fetchone()
        if previous is not None:
            if previous[:5] != expected:
                raise ValueError("调度停止观察内容已经变化")
            return {"scope": "LOCAL_OBJECT_ONLY", "global_state": "UNVERIFIED", "observed_at": previous[5], "created": False}
        timestamp = utc_now().isoformat()
        db.execute("INSERT INTO agent_schedule_stop_observations VALUES (?,?,?,?,?,?,?,?)", (namespace, request_key, owner, epoch, os.getpid(), str(path), timestamp, "LOCAL_OBJECT_ONLY"))
        if inspect_legacy_cron(cron)["local_state"] != "STOPPED":
            raise ValueError("调度对象状态已经变化")
        return {"scope": "LOCAL_OBJECT_ONLY", "global_state": "UNVERIFIED", "observed_at": timestamp, "created": True}
