import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from filelock import FileLock

from agent_run_store import RunConnection, RunStore


class HermesVMRunBindings:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, RunStore):
            raise ValueError("需要运行存储")
        self.store = store
        script = (Path(__file__).parent / "migrations/hermes_vm_binding_001.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("hermes_vm_binding_001",)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("虚拟机运行绑定迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_process_evidence'").fetchone() is None:
                raise ValueError("虚拟机运行绑定迁移尚未完成")
            db.executescript("BEGIN IMMEDIATE;\n" + script)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_vm_binding_001", digest))

    def register_in_transaction(self, db, run_id, request_key, owner, epoch, vm_id, boot_id, workspace):
        if not isinstance(db, RunConnection) or not db.in_transaction:
            raise ValueError("虚拟机绑定需要运行事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("虚拟机绑定数据库不匹配")
        for value in (run_id, vm_id, boot_id):
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError("虚拟机或运行身份无效")
        if not isinstance(request_key, str) or not request_key or not isinstance(owner, str) or not owner or type(epoch) is not int or epoch <= 0:
            raise ValueError("虚拟机运行租约无效")
        directory = Path(workspace)
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir() or directory.name != run_id or directory.resolve(strict=True) != directory:
            raise ValueError("虚拟机工作区无效")
        stat = directory.stat()
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        self.store._require_lease(db, run_id, owner, epoch)
        self.store.require_active_lineage(db, run_id)
        row = db.execute("SELECT p.lease_owner,p.lease_epoch,p.state,r.status,r.cancel_requested_at FROM hermes_process_evidence p JOIN agent_runs r ON r.run_id=p.run_id WHERE p.run_id=? AND p.request_key=?", (run_id, request_key)).fetchone()
        if row != (owner, epoch, "STARTING", "RUNNING", None):
            raise ValueError("虚拟机进程启动状态不可核查")
        expected = (owner, epoch, vm_id, boot_id, unit, stat.st_dev, stat.st_ino)
        existing = db.execute("SELECT lease_owner,lease_epoch,vm_id,boot_id,unit_name,workspace_device,workspace_inode FROM hermes_vm_run_bindings WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if existing is not None:
            if existing != expected:
                raise ValueError("虚拟机运行绑定已经变化")
            return unit
        ownership = db.execute("SELECT run_id FROM hermes_vm_workspace_ownership WHERE workspace_device=? AND workspace_inode=?", (stat.st_dev, stat.st_ino)).fetchone()
        if ownership is None:
            db.execute("INSERT INTO hermes_vm_workspace_ownership VALUES (?,?,?)", (stat.st_dev, stat.st_ino, run_id))
        elif ownership != (run_id,):
            raise ValueError("虚拟机工作区属于其他运行")
        db.execute("INSERT INTO hermes_vm_run_bindings VALUES (?,?,?,?,?,?,?,?,?)", (run_id, request_key, *expected))
        return unit

    def require_current_in_transaction(self, db, run_id, request_key, owner, epoch, vm_id, boot_id, workspace):
        if not isinstance(db, RunConnection) or not db.in_transaction:
            raise ValueError("虚拟机通信核查需要运行事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("虚拟机通信数据库不匹配")
        for value in (run_id, vm_id, boot_id):
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError("虚拟机或运行身份无效")
        if not isinstance(request_key, str) or not request_key or not isinstance(owner, str) or not owner or type(epoch) is not int or epoch <= 0:
            raise ValueError("虚拟机运行租约无效")
        directory = Path(workspace)
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir() or directory.name != run_id or directory.resolve(strict=True) != directory:
            raise ValueError("虚拟机工作区无效")
        identity = directory.stat()
        self.store._require_lease(db, run_id, owner, epoch)
        self.store.require_active_lineage(db, run_id)
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        row = db.execute("SELECT b.lease_owner,b.lease_epoch,b.vm_id,b.boot_id,b.unit_name,b.workspace_device,b.workspace_inode,p.state,r.status,r.cancel_requested_at FROM hermes_vm_run_bindings b JOIN hermes_process_evidence p ON p.run_id=b.run_id AND p.request_key=b.request_key JOIN agent_runs r ON r.run_id=b.run_id WHERE b.run_id=? AND b.request_key=?", (run_id, request_key)).fetchone()
        expected = (owner, epoch, vm_id, boot_id, unit, identity.st_dev, identity.st_ino)
        if row is None or row[:7] != expected or row[7] not in {"STARTING", "RUNNING"} or row[8:] != ("RUNNING", None):
            raise ValueError("虚拟机通信绑定不可核查")
        return unit

    def require_final_in_transaction(self, db, run_id, request_key, owner, epoch, vm_id, boot_id, workspace):
        if not isinstance(db, RunConnection) or not db.in_transaction:
            raise ValueError("虚拟机收尾核查需要运行事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("虚拟机收尾数据库不匹配")
        for value in (run_id, vm_id, boot_id):
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError("虚拟机收尾身份无效")
        if not isinstance(request_key, str) or not request_key or not isinstance(owner, str) or not owner or type(epoch) is not int or epoch <= 0:
            raise ValueError("虚拟机收尾租约无效")
        directory = Path(workspace)
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir() or directory.name != run_id or directory.resolve(strict=True) != directory:
            raise ValueError("虚拟机收尾工作区无效")
        identity = directory.stat()
        self.store._require_lease_identity(db, run_id, owner, epoch)
        self.store.require_terminal_lineage(db, run_id)
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        row = db.execute("SELECT b.lease_owner,b.lease_epoch,b.vm_id,b.boot_id,b.unit_name,b.workspace_device,b.workspace_inode,p.state,r.status FROM hermes_vm_run_bindings b JOIN hermes_process_evidence p ON p.run_id=b.run_id AND p.request_key=b.request_key JOIN agent_runs r ON r.run_id=b.run_id WHERE b.run_id=? AND b.request_key=?", (run_id, request_key)).fetchone()
        expected = (owner, epoch, vm_id, boot_id, unit, identity.st_dev, identity.st_ino)
        if row is None or row[:7] != expected or row[7] not in {"STARTING", "RUNNING", "UNKNOWN"} or row[8] not in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING", "INTERRUPTED"}:
            raise ValueError("虚拟机收尾绑定不可核查")
        return unit


@dataclass(frozen=True)
class HermesVMRunAccess:
    bindings: HermesVMRunBindings
    run_id: str
    request_key: str
    owner: str
    epoch: int
    vm_id: str
    boot_id: str
    workspace: Path

    def __post_init__(self):
        if not isinstance(self.bindings, HermesVMRunBindings) or not isinstance(self.workspace, Path):
            raise ValueError("虚拟机通信需要运行绑定")

    def require_in_transaction(self, db):
        return self.bindings.require_current_in_transaction(db, self.run_id, self.request_key, self.owner, self.epoch,
                                                            self.vm_id, self.boot_id, self.workspace)

    def require(self):
        with self.bindings.store.connect() as db:
            db.execute("BEGIN")
            return self.require_in_transaction(db)

    def require_workspace_context(self):
        with self.bindings.store.connect() as db:
            db.execute("BEGIN")
            unit = self.require_in_transaction(db)
            root = self.bindings.store.require_active_lineage(db, self.run_id)
            budget = db.execute("SELECT max_files,max_bytes FROM agent_file_budgets WHERE root_run_id=?", (root,)).fetchone()
            root_row = db.execute("SELECT lease_epoch FROM agent_runs WHERE run_id=?", (root,)).fetchone()
            if budget is None or root_row is None or any(type(value) is not int or value <= 0 for value in (*budget, root_row[0])):
                raise ValueError("根运行工作区额度或版本不可核查")
            return {"unit": unit, "root_run_id": root, "root_epoch": root_row[0],
                    "max_files": budget[0], "max_bytes": budget[1]}

    def require_final_in_transaction(self, db):
        return self.bindings.require_final_in_transaction(db, self.run_id, self.request_key, self.owner, self.epoch,
                                                          self.vm_id, self.boot_id, self.workspace)

    def require_final(self):
        with self.bindings.store.connect() as db:
            db.execute("BEGIN")
            return self.require_final_in_transaction(db)


@dataclass(frozen=True)
class HermesVMRecoveryAccess(HermesVMRunAccess):
    recovery: object
    request: object

    def __post_init__(self):
        from aiohttp import web
        from hermes_run_recovery import HermesRunRecovery
        super().__post_init__()
        if not isinstance(self.recovery, HermesRunRecovery) or not isinstance(self.request, web.Request) or self.recovery.store.path.resolve() != self.bindings.store.path.resolve():
            raise ValueError("虚拟机恢复需要本人请求和运行恢复服务")

    def require_final_in_transaction(self, db):
        if not isinstance(db, RunConnection) or not db.in_transaction:
            raise ValueError("虚拟机恢复需要运行事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.bindings.store.path.resolve():
            raise ValueError("虚拟机恢复数据库不匹配")
        self.recovery.recover_expired_authenticated_in_transaction(db, self.request, self.run_id)
        directory = self.workspace
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir() or directory.name != self.run_id or directory.resolve(strict=True) != directory:
            raise ValueError("虚拟机恢复工作区无效")
        info = directory.stat()
        unit = "boss-" + self.run_id + "-" + str(self.epoch) + ".service"
        saved = db.execute("SELECT b.lease_owner,b.lease_epoch,b.vm_id,b.boot_id,b.unit_name,b.workspace_device,b.workspace_inode,p.lease_owner,p.lease_epoch,p.state,r.lease_epoch,r.status,r.lease_owner,r.lease_expires_at FROM hermes_vm_run_bindings b JOIN hermes_process_evidence p ON p.run_id=b.run_id AND p.request_key=b.request_key JOIN agent_runs r ON r.run_id=b.run_id WHERE b.run_id=? AND b.request_key=?", (self.run_id, self.request_key)).fetchone()
        expected = (self.owner, self.epoch, self.vm_id, self.boot_id, unit, info.st_dev, info.st_ino, self.owner, self.epoch, "UNKNOWN", self.epoch, "INTERRUPTED", None, None)
        if saved != expected:
            raise ValueError("虚拟机恢复绑定不可核查")
        return unit

    def require_final(self):
        with self.bindings.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.require_final_in_transaction(db)
