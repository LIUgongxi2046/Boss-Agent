import hashlib
import json
from pathlib import Path

from filelock import FileLock

from agent_run_store import RunStore, utc_now
from boss_execution_transition import pending_transition
from boss_simulation_api import _context
from boss_owner_plans import stop_business_until, valid_plan_budget
from business import checksum
from controls import ControlStore


VERSION = "upgrade2_plan_handover_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentPlanHandover:
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
                    raise ValueError("计划交接迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_plan_handovers'").fetchone() is not None:
                raise ValueError("计划交接迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def _manifest(self, db):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("计划交接需要同一数据库事务")
        db.execute("UPDATE spaces SET active=active WHERE 0")
        if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
            raise ValueError("计划交接迁移摘要不符")
        context = _context(db)
        namespace = context["namespace"]
        if pending_transition(db, namespace) is not None:
            raise ValueError("执行空间正在切换")
        schedule = self.store.get(db, namespace, "schedule", "current")
        if any(not isinstance(schedule.get(key), str) or not schedule[key] for key in ("schedule_id", "version", "schedule_version")):
            raise ValueError("计划调度编号或版本不可核查")
        kinds = ("owner_plan", "owner_plan_revision", "authorization", "event", "notification", "dispatch", "dispatch_history")
        rows = db.execute("SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN (?,?,?,?,?,?,?) ORDER BY kind,id", (namespace, *kinds)).fetchall()
        flags = set()
        plan_count = 0
        for kind, identifier, body in rows:
            if kind != "owner_plan":
                continue
            plan = json.loads(body)
            if plan.get("plan_id") != identifier or plan.get("owner_id") != context["owner_id"] or plan.get("source_type") != "SIMULATED" or not isinstance(plan.get("version"), str):
                raise ValueError("本人计划身份或版本不可核查")
            event_ids, versions = plan.get("event_ids"), plan.get("event_versions")
            if not isinstance(event_ids, list) or not event_ids or any(not isinstance(item, str) or not item for item in event_ids) or len(event_ids) != len(set(event_ids)) or not isinstance(versions, dict) or set(event_ids) != set(versions):
                raise ValueError("本人计划事件范围不可核查")
            for event_id in event_ids:
                event = self.store.get(db, namespace, "event", event_id)
                if event.get("owner_plan_id") != identifier or event.get("version") != versions[event_id]:
                    raise ValueError("本人计划事件版本已经变化")
            authorization_id = plan.get("authorization_id")
            if not isinstance(authorization_id, str) or not authorization_id or db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='authorization' AND id=?", (namespace, authorization_id)).fetchone() is None:
                flags.add("PLAN_AUTHORIZATION_MISSING")
            else:
                flags.add("PLAN_AUTHORIZATION_NOT_VERIFIED")
            if "stop_conditions" not in plan:
                flags.add("STOP_CONDITIONS_MISSING")
            else:
                stop_business_until(plan["stop_conditions"])
            if not valid_plan_budget(plan.get("budget")):
                flags.add("PLAN_BUDGET_MISSING_OR_INVALID")
            plan_count += 1
        receipts = db.execute("SELECT operation,key,digest,result FROM idempotency WHERE namespace=? AND operation LIKE 'boss.owner.plan.%' ORDER BY operation,key", (namespace,)).fetchall()
        tables = ("hermes_schedule_observations", "hermes_schedule_plan_candidates", "hermes_schedule_run_links", "hermes_schedule_notification_links")
        present = [db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None for table in tables]
        if any(present) and not all(present):
            raise ValueError("计划调度表不完整")
        projections = []
        if all(present):
            for table in tables:
                projections.append([table, db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()])
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_schedule_run_budgets'").fetchone() is None:
                flags.add("HERMES_SCHEDULE_BUDGET_NOT_INSTALLED")
            else:
                from hermes_schedule_adapter import RUN_BUDGET_MIGRATION_PATH, RUN_BUDGET_MIGRATION_VERSION
                migration = db.execute("SELECT sha256 FROM hermes_schedule_migrations WHERE version=?", (RUN_BUDGET_MIGRATION_VERSION,)).fetchone()
                if migration != (hashlib.sha256(RUN_BUDGET_MIGRATION_PATH.read_bytes()).hexdigest(),):
                    raise ValueError("计划运行预算迁移摘要不可核查")
                projections.append(["hermes_schedule_run_budgets", db.execute("SELECT * FROM hermes_schedule_run_budgets ORDER BY rowid").fetchall()])
        else:
            flags.add("HERMES_SCHEDULE_NOT_INSTALLED")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_schedule_occurrence_gate'").fetchone() is None:
            flags.add("OCCURRENCE_GATE_NOT_INSTALLED")
        else:
            from agent_schedule_occurrence_gate import MIGRATION as OCCURRENCE_MIGRATION, VERSION as OCCURRENCE_VERSION
            migration = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (OCCURRENCE_VERSION,)).fetchone()
            if migration != (hashlib.sha256(OCCURRENCE_MIGRATION.read_bytes()).hexdigest(),):
                raise ValueError("计划发生门禁迁移摘要不可核查")
            projections.append(["agent_schedule_occurrence_gate", db.execute("SELECT * FROM agent_schedule_occurrence_gate WHERE namespace=? ORDER BY rowid", (namespace,)).fetchall()])
        return {"namespace": namespace, "owner_id": context["owner_id"], "dataset_id": context["dataset_id"],
                "dataset_version": context["dataset_version"], "schedule_id": schedule["schedule_id"],
                "schedule_version": schedule["schedule_version"], "schedule_configuration_version": schedule["version"],
                "schedule_sha256": checksum(schedule), "plan_count": plan_count, "records_sha256": checksum(rows),
                "receipt_count": len(receipts), "receipts_sha256": checksum(receipts), "projection_sha256": checksum(projections),
                "conditions": sorted(flags | {"OLD_DRIVER_STOP_UNVERIFIED", "UNIQUE_SCHEDULER_LEASE_UNVERIFIED"}), "activation": "DISABLED"}

    def capture_in_transaction(self, db, request_key):
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200:
            raise ValueError("计划交接请求编号无效")
        manifest = self._manifest(db)
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        old = db.execute("SELECT source_digest,manifest_json FROM agent_plan_handovers WHERE namespace=? AND request_key=?", (manifest["namespace"], request_key)).fetchone()
        if old is not None:
            if old != (digest, encoded):
                raise ValueError("计划交接原资料已经变化")
            return {"manifest": manifest, "source_digest": digest, "created": False}
        db.execute("INSERT INTO agent_plan_handovers VALUES (?,?,?,?,?)", (manifest["namespace"], request_key, digest, encoded, utc_now().isoformat()))
        return {"manifest": manifest, "source_digest": digest, "created": True}
