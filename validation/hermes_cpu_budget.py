import hashlib
from datetime import datetime
from pathlib import Path

from aiohttp import web
from filelock import FileLock

from agent_run_store import RunConnection, RunStore, utc_now
from hermes_vm_host import HermesVMHostClient
from hermes_vm_identity import HermesVMRunAccess


VERSION = "hermes_cpu_budget_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


def vm_cpu_allocation_seconds(budget):
    if not isinstance(budget, dict) or type(budget.get("cpu_seconds")) is not int or type(budget.get("concurrency")) is not int:
        raise ValueError("CPU 分配需要本人批准的预算和并发额度")
    total, concurrency = budget["cpu_seconds"], budget["concurrency"]
    if total <= 0 or concurrency <= 0:
        raise ValueError("CPU 预算和并发额度必须为正数")
    if total < concurrency:
        raise web.HTTPTooManyRequests(text="CPU 预算不足以支持已批准的并发额度")
    return total // concurrency


class HermesCPUBudget:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, RunStore):
            raise ValueError("CPU 预算需要运行存储")
        self.store = store
        script = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("CPU 预算迁移摘要不符")
            else:
                if not allow_migration or db.execute("SELECT 1 FROM agent_schema_migrations WHERE version='hermes_vm_binding_001'").fetchone() is None:
                    raise ValueError("CPU 预算迁移尚未完成")
                db.executescript("BEGIN IMMEDIATE;\n" + script)
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))
                db.commit()
            extra = Path(__file__).parent / "migrations" / "hermes_cpu_budget_002.sql"
            extra_script = extra.read_text(encoding="utf-8")
            extra_digest = hashlib.sha256(extra_script.encode("utf-8")).hexdigest()
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_002'").fetchone()
            if row is None:
                if not allow_migration:
                    raise ValueError("CPU 退出记录迁移尚未完成")
                db.executescript("BEGIN IMMEDIATE;\n" + extra_script)
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_cpu_budget_002", extra_digest))
            elif row[0] != extra_digest:
                raise ValueError("CPU 退出记录迁移摘要不符")
            db.commit()
            observation_migration = Path(__file__).parent / "migrations" / "hermes_cpu_budget_003.sql"
            observation_script = observation_migration.read_text(encoding="utf-8")
            observation_digest = hashlib.sha256(observation_script.encode("utf-8")).hexdigest()
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_003'").fetchone()
            if row is None:
                if not allow_migration:
                    raise ValueError("CPU 退出观察迁移尚未完成")
                db.executescript("BEGIN IMMEDIATE;\n" + observation_script)
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_cpu_budget_003", observation_digest))
            elif row[0] != observation_digest:
                raise ValueError("CPU 退出观察迁移摘要不符")
            db.commit()
            source_migration = Path(__file__).parent / "migrations" / "hermes_cpu_budget_004.sql"
            source_script = source_migration.read_text(encoding="utf-8")
            source_digest = hashlib.sha256(source_script.encode("utf-8")).hexdigest()
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_004'").fetchone()
            if row is None:
                if not allow_migration:
                    raise ValueError("CPU 来源迁移尚未完成")
                db.executescript("BEGIN IMMEDIATE;\n" + source_script)
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_cpu_budget_004", source_digest))
            elif row[0] != source_digest:
                raise ValueError("CPU 来源迁移摘要不符")
            db.commit()
            final_migration = Path(__file__).parent / "migrations" / "hermes_cpu_budget_005.sql"
            final_script = final_migration.read_text(encoding="utf-8")
            final_digest = hashlib.sha256(final_script.encode("utf-8")).hexdigest()
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_005'").fetchone()
            if row is None:
                if not allow_migration:
                    raise ValueError("CPU 最终结算迁移尚未完成")
                db.executescript("BEGIN IMMEDIATE;\n" + final_script)
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_cpu_budget_005", final_digest))
            elif row[0] != final_digest:
                raise ValueError("CPU 最终结算迁移摘要不符")
            db.commit()
            recovery_migration = Path(__file__).parent / "migrations" / "hermes_cpu_budget_006.sql"
            recovery_script = recovery_migration.read_text(encoding="utf-8")
            recovery_digest = hashlib.sha256(recovery_script.encode("utf-8")).hexdigest()
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_006'").fetchone()
            if row is None:
                if not allow_migration:
                    raise ValueError("CPU 恢复结算迁移尚未完成")
                db.executescript("BEGIN IMMEDIATE;\n" + recovery_script)
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_cpu_budget_006", recovery_digest))
            elif row[0] != recovery_digest:
                raise ValueError("CPU 恢复结算迁移摘要不符")
            db.commit()
            tree_migration = Path(__file__).parent / "migrations" / "hermes_cpu_budget_007.sql"
            tree_script = tree_migration.read_text(encoding="utf-8")
            tree_digest = hashlib.sha256(tree_script.encode("utf-8")).hexdigest()
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_007'").fetchone()
            if row is None:
                if not allow_migration:
                    raise ValueError("虚拟机进程范围退出迁移尚未完成")
                db.executescript("BEGIN IMMEDIATE;\n" + tree_script)
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_cpu_budget_007", tree_digest))
            elif row[0] != tree_digest:
                raise ValueError("虚拟机进程范围退出迁移摘要不符")

    def _require_transaction(self, db):
        if not isinstance(db, RunConnection) or not db.in_transaction:
            raise ValueError("CPU 预算需要运行写事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("CPU 预算数据库不匹配")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")

    def configure_in_transaction(self, db, root_run_id, owner, epoch, limit_ns):
        self._require_transaction(db)
        if type(limit_ns) is not int or not 0 < limit_ns < 2**63:
            raise ValueError("CPU 预算无效")
        self.store._require_lease(db, root_run_id, owner, epoch)
        if self.store.require_active_lineage(db, root_run_id) != root_run_id:
            raise ValueError("CPU 预算需要根运行")
        db.execute("INSERT INTO hermes_cpu_budgets VALUES (?,?) ON CONFLICT(root_run_id) DO NOTHING", (root_run_id, limit_ns))
        if db.execute("SELECT limit_ns FROM hermes_cpu_budgets WHERE root_run_id=?", (root_run_id,)).fetchone() != (limit_ns,):
            raise ValueError("CPU 预算已经变化")

    def reserve_in_transaction(self, db, access, reserved_ns):
        self._require_transaction(db)
        if not isinstance(access, HermesVMRunAccess) or access.bindings.store.path.resolve() != self.store.path.resolve():
            raise ValueError("CPU 预留需要当前虚拟机绑定")
        if type(reserved_ns) is not int or not 0 < reserved_ns < 2**63:
            raise ValueError("CPU 预留无效")
        access.require_in_transaction(db)
        root = self.store.require_active_lineage(db, access.run_id)
        limit = db.execute("SELECT limit_ns FROM hermes_cpu_budgets WHERE root_run_id=?", (root,)).fetchone()
        if limit is None:
            raise ValueError("根运行缺少 CPU 预算")
        old = db.execute("SELECT root_run_id,lease_epoch,reserved_ns FROM hermes_cpu_reservations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
        if old is not None:
            if old != (root, access.epoch, reserved_ns):
                raise ValueError("CPU 预留已经变化")
            return False
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_cpu_unknown_exits'").fetchone() is not None:
            unknown = db.execute("SELECT 1 FROM hermes_cpu_unknown_exits e JOIN hermes_cpu_reservations c ON c.run_id=e.run_id AND c.request_key=e.request_key LEFT JOIN hermes_cpu_final_exits f ON f.run_id=e.run_id AND f.request_key=e.request_key WHERE c.root_run_id=? AND f.run_id IS NULL LIMIT 1", (root,)).fetchone()
            if unknown is not None:
                raise ValueError("CPU 退出用量不可核查")
        rows = db.execute("SELECT c.reserved_ns,c.observed_ns,c.lease_epoch,r.lease_epoch,r.lease_expires_at,r.status,p.state,f.cpu_ns FROM hermes_cpu_reservations c LEFT JOIN agent_runs r ON r.run_id=c.run_id LEFT JOIN hermes_process_evidence p ON p.run_id=c.run_id AND p.request_key=c.request_key LEFT JOIN hermes_cpu_final_exits f ON f.run_id=c.run_id AND f.request_key=c.request_key WHERE c.root_run_id=?", (root,)).fetchall()
        used = 0
        for reserved, observed, epoch, current_epoch, expires_at, status, process_state, final_cpu in rows:
            if final_cpu is not None:
                used += final_cpu
                continue
            if epoch != current_epoch or expires_at is None or datetime.fromisoformat(expires_at) <= utc_now() or status != "RUNNING" or process_state not in {"STARTING", "RUNNING"}:
                raise ValueError("CPU 预留状态不可核查")
            used += max(reserved, observed)
        if reserved_ns > limit[0] - used:
            raise ValueError("CPU 预算不足")
        db.execute("INSERT INTO hermes_cpu_reservations VALUES (?,?,?,?,?,0)", (access.run_id, access.request_key, root, access.epoch, reserved_ns))
        db.execute("INSERT INTO hermes_cpu_sources VALUES (?,?,'SLICE_CPU_NSEC_V1')", (access.run_id, access.request_key))
        return True

    def record_sample(self, host, sample_id, *, authority=None):
        if not isinstance(host, HermesVMHostClient) or not isinstance(sample_id, str) or not sample_id:
            raise ValueError("CPU 采样需要客体控制和采样编号")
        access = host.access
        if authority is None:
            result = host.slice_cpu_usage()
        else:
            state, result = host.monitor_read(authority, "cpu-slice")
            if state != "RUNNING":
                return state
        if result is None:
            return None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_transaction(db)
            if authority is None:
                access.require_in_transaction(db)
            else:
                state = authority.monitor_state_in_transaction(db)
                if state != "RUNNING":
                    return state
                access.require_in_transaction(db)
            root = self.store.require_active_lineage(db, access.run_id)
            row = db.execute("SELECT root_run_id,lease_epoch,observed_ns FROM hermes_cpu_reservations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if row is None or row[:2] != (root, access.epoch):
                raise ValueError("CPU 采样没有有效预留")
            if db.execute("SELECT source FROM hermes_cpu_sources WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone() != ("SLICE_CPU_NSEC_V1",):
                raise ValueError("CPU 采样来源不匹配")
            if db.execute("SELECT 1 FROM hermes_cpu_final_exits WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone() is not None:
                raise ValueError("CPU 预留已经结算")
            old = db.execute("SELECT cpu_ns FROM hermes_cpu_samples WHERE run_id=? AND request_key=? AND sample_id=?", (access.run_id, access.request_key, sample_id)).fetchone()
            if old is not None:
                return old[0]
            if result["cpu_ns"] < row[2]:
                raise ValueError("CPU 累计读数已经减少")
            db.execute("INSERT INTO hermes_cpu_samples VALUES (?,?,?,?)", (access.run_id, access.request_key, sample_id, result["cpu_ns"]))
            db.execute("UPDATE hermes_cpu_reservations SET observed_ns=? WHERE run_id=? AND request_key=?", (result["cpu_ns"], access.run_id, access.request_key))
            return result["cpu_ns"]

    def record_unknown_exit(self, host):
        if not isinstance(host, HermesVMHostClient):
            raise ValueError("CPU 退出记录需要客体控制")
        access = host.access
        receipt = host.unknown_exit_receipt()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_transaction(db)
            access.require_final_in_transaction(db)
            migration = Path(__file__).parent / "migrations" / "hermes_cpu_budget_002.sql"
            expected_digest = hashlib.sha256(migration.read_bytes()).hexdigest()
            if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_002'").fetchone() != (expected_digest,):
                raise ValueError("CPU 退出记录迁移尚未完成")
            root = self.store.require_terminal_lineage(db, access.run_id)
            reservation = db.execute("SELECT root_run_id,lease_epoch FROM hermes_cpu_reservations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if reservation != (root, access.epoch):
                raise ValueError("CPU 退出记录没有有效预留")
            values = (access.run_id, access.request_key, access.epoch, access.vm_id, access.boot_id, receipt["unit"], "UNKNOWN", None)
            db.execute("INSERT INTO hermes_cpu_unknown_exits VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(run_id,request_key) DO NOTHING", values)
            if db.execute("SELECT run_id,request_key,lease_epoch,vm_id,boot_id,unit,state,cpu_ns FROM hermes_cpu_unknown_exits WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone() != values:
                raise ValueError("CPU 退出记录已经变化")
            return receipt

    def record_unknown_exit_observation(self, host):
        if not isinstance(host, HermesVMHostClient):
            raise ValueError("CPU 退出观察需要客体控制")
        access = host.access
        observation = host.unknown_exit_observation()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_transaction(db)
            access.require_final_in_transaction(db)
            migration = Path(__file__).parent / "migrations" / "hermes_cpu_budget_003.sql"
            if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_003'").fetchone() != (hashlib.sha256(migration.read_bytes()).hexdigest(),):
                raise ValueError("CPU 退出观察迁移尚未完成")
            expected = (access.epoch, access.vm_id, access.boot_id, observation["unit"], "UNKNOWN", None)
            saved = db.execute("SELECT lease_epoch,vm_id,boot_id,unit,state,cpu_ns FROM hermes_cpu_unknown_exits WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if saved != expected:
                raise ValueError("CPU 退出观察缺少未知记录")
            reservation = db.execute("SELECT lease_epoch,observed_ns FROM hermes_cpu_reservations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if reservation is None or reservation[0] != access.epoch:
                raise ValueError("CPU 退出观察没有有效预留")
            source = db.execute("SELECT source FROM hermes_cpu_sources WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if source not in {("UNIT_CPU_NSEC_LEGACY",), ("SLICE_CPU_NSEC_V1",)}:
                raise ValueError("CPU 预留来源不可核查")
            if source == ("UNIT_CPU_NSEC_LEGACY",) and observation["cpu_ns"] < reservation[1]:
                raise ValueError("CPU 退出观察低于已保存的累计用量")
            values = (access.run_id, access.request_key, access.epoch, access.vm_id, access.boot_id, observation["unit"], observation["invocation"], observation["unit_state"], observation["control_group"], observation["cpu_ns"], observation["kill_mode"], observation["result"], "UNKNOWN")
            db.execute("INSERT INTO hermes_cpu_exit_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,request_key) DO NOTHING", values)
            if db.execute("SELECT run_id,request_key,lease_epoch,vm_id,boot_id,unit,invocation,unit_state,control_group,cpu_ns,kill_mode,result,state FROM hermes_cpu_exit_observations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone() != values:
                raise ValueError("CPU 退出观察已经变化")
            return observation

    def settle_final_exit(self, host):
        if not isinstance(host, HermesVMHostClient):
            raise ValueError("CPU 最终结算需要客体控制")
        access = host.access
        receipt = host.final_exit_receipt()
        with self.store.connect() as db:
            db.execute("BEGIN")
            old = db.execute("SELECT f.lease_epoch,f.vm_id,f.boot_id,f.unit,f.invocation,f.slice,f.cpu_ns,f.source,c.lease_owner,c.state FROM hermes_cpu_final_exits f JOIN agent_concurrency_reservations c ON c.run_id=f.run_id AND c.request_key=f.request_key WHERE f.run_id=? AND f.request_key=?", (access.run_id, access.request_key)).fetchone()
        if old == (access.epoch, access.vm_id, access.boot_id, receipt["unit"], receipt["invocation"], receipt["slice"], receipt["cpu_ns"], receipt["source"], access.owner, "RELEASED"):
            return receipt
        tree = host.tree_exit_receipt()
        if any(tree[key] != receipt[key] for key in ("run_id", "epoch", "boot_id", "unit", "invocation", "slice", "cpu_ns")) or tree["source"] != "SYSTEMD_CGROUP_EXIT_V1":
            raise ValueError("进程范围退出与最终 CPU 回执不匹配")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_transaction(db)
            access.require_final_in_transaction(db)
            root = self.store.require_terminal_lineage(db, access.run_id)
            reservation = db.execute("SELECT root_run_id,lease_epoch,observed_ns FROM hermes_cpu_reservations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if reservation is None or reservation[:2] != (root, access.epoch) or receipt["cpu_ns"] < reservation[2]:
                raise ValueError("CPU 最终读数与预留不匹配")
            if db.execute("SELECT source FROM hermes_cpu_sources WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone() != (receipt["source"],):
                raise ValueError("CPU 最终读数来源不匹配")
            observation = db.execute("SELECT lease_epoch,vm_id,boot_id,unit,invocation FROM hermes_cpu_exit_observations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if observation != (access.epoch, access.vm_id, access.boot_id, receipt["unit"], receipt["invocation"]):
                raise ValueError("CPU 最终退出观察不匹配")
            values = (access.run_id, access.request_key, access.epoch, access.vm_id, access.boot_id, receipt["unit"], receipt["invocation"], receipt["slice"], receipt["cpu_ns"], receipt["source"])
            db.execute("INSERT INTO hermes_cpu_final_exits VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,request_key) DO NOTHING", values)
            if db.execute("SELECT run_id,request_key,lease_epoch,vm_id,boot_id,unit,invocation,slice,cpu_ns,source FROM hermes_cpu_final_exits WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone() != values:
                raise ValueError("CPU 最终结算已经变化")
            tree_values = (access.run_id, access.request_key, access.epoch, access.vm_id, access.boot_id, tree["unit"], tree["invocation"], tree["slice"], tree["cpu_ns"], tree["source"])
            db.execute("INSERT INTO hermes_vm_tree_exits VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,request_key) DO NOTHING", tree_values)
            if db.execute("SELECT run_id,request_key,lease_epoch,vm_id,boot_id,unit,invocation,slice,cpu_ns,source FROM hermes_vm_tree_exits WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone() != tree_values:
                raise ValueError("虚拟机进程范围退出记录已经变化")
            concurrency = db.execute("SELECT lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if concurrency not in {(access.owner, access.epoch, "ACTIVE"), (access.owner, access.epoch, "UNKNOWN"), (access.owner, access.epoch, "RELEASED")}:
                raise ValueError("最终退出并发预留不可核查")
            evidence = db.execute("SELECT lease_owner,lease_epoch FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
            if evidence != (access.owner, access.epoch):
                raise ValueError("最终退出进程记录不可核查")
            if concurrency[2] in {"ACTIVE", "UNKNOWN"}:
                db.execute("UPDATE agent_concurrency_reservations SET state='RELEASED',updated_at=? WHERE run_id=? AND request_key=?", (utc_now().isoformat(), access.run_id, access.request_key))
            return receipt

    def cleanup_settled_exit(self, host):
        if not isinstance(host, HermesVMHostClient):
            raise ValueError("CPU 结算清理需要客体控制")
        access = host.access
        receipt = host.final_exit_receipt()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_transaction(db)
            access.require_final_in_transaction(db)
            values = (access.run_id, access.request_key, access.epoch, access.vm_id, access.boot_id, receipt["unit"], receipt["invocation"], receipt["slice"], receipt["cpu_ns"], receipt["source"])
            if db.execute("SELECT run_id,request_key,lease_epoch,vm_id,boot_id,unit,invocation,slice,cpu_ns,source FROM hermes_cpu_final_exits WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone() != values:
                raise ValueError("CPU 清理缺少最终结算")
        return host.cleanup_final_exit(receipt)
