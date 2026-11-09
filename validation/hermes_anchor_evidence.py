import hashlib
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock

from agent_run_store import RunStore, utc_now
from hermes_process_anchor import AnchorProcessGroup, _require_engine_owned_by_anchor


def require_lease_window(expires_at, timeout):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("锚点许可时限无效")
    if not isinstance(expires_at, str):
        raise ValueError("锚点租约到期时间无效")
    expiration = datetime.fromisoformat(expires_at)
    if expiration.tzinfo is None or expiration.utcoffset() != timedelta(0):
        raise ValueError("锚点租约到期时间无效")
    if expiration <= datetime.now(timezone.utc) + timedelta(seconds=timeout):
        raise ValueError("锚点租约剩余时间不足")


def reclaim_uncertain_anchor(anchor):
    if not isinstance(anchor, AnchorProcessGroup):
        raise ValueError("锚点进程不可核查")
    if anchor.process.poll() is None:
        anchor.reclaim()
    anchor.close_control()


class HermesAnchorEvidence:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, RunStore):
            raise ValueError("需要运行存储")
        self.store = store
        script = (Path(__file__).parent / "migrations/hermes_anchor_evidence_001.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("hermes_anchor_evidence_001",)).fetchone()
            if previous is not None:
                if previous[0] != digest:
                    raise ValueError("锚点记录迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM agent_schema_migrations WHERE version=?", ("hermes_process_evidence_001",)).fetchone() is None:
                raise ValueError("锚点记录迁移条件不足")
            db.execute("ROLLBACK")
            db.executescript("BEGIN IMMEDIATE;\n" + script)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_anchor_evidence_001", digest))

    def record(self, run_id, request_key, owner, epoch, anchor):
        if not isinstance(anchor, AnchorProcessGroup) or anchor.process.pid != anchor.anchor_pid or anchor.process.poll() is not None:
            raise ValueError("锚点进程不可核查")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store._require_lease(db, run_id, owner, epoch)
            self.store.require_active_lineage(db, run_id)
            row = db.execute("SELECT p.state,p.lease_owner,p.lease_epoch,p.supervisor_pid,r.status,r.cancel_requested_at,c.state FROM hermes_process_evidence p JOIN agent_runs r ON r.run_id=p.run_id JOIN agent_concurrency_reservations c ON c.run_id=p.run_id AND c.request_key=p.request_key WHERE p.run_id=? AND p.request_key=?", (run_id, request_key)).fetchone()
            if row != ("STARTING", owner, epoch, os.getpid(), "RUNNING", None, "ACTIVE"):
                raise ValueError("锚点登记状态不可核查")
            if anchor.process.poll() is not None:
                raise ValueError("锚点进程已经退出")
            _require_engine_owned_by_anchor(anchor.anchor_pid, anchor.engine_pid)
            db.execute("INSERT INTO hermes_anchor_evidence VALUES (?,?,?,?,?,?,?,?)", (run_id, request_key, anchor.anchor_pid, anchor.engine_pid, os.getpid(), owner, epoch, utc_now().isoformat()))

    def mark_uncertain(self, run_id, request_key, owner, epoch, anchor, *, allow_released=False):
        if not isinstance(anchor, AnchorProcessGroup) or anchor.process.pid != anchor.anchor_pid or anchor.process.poll() is None:
            raise ValueError("锚点退出不可核查")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT p.state,p.request_digest,p.lease_owner,p.lease_epoch,p.actor_id,p.space_id,p.supervisor_pid,"
                             "c.state,c.request_digest,c.lease_owner,c.lease_epoch,r.actor_id,r.space_id,r.lease_owner,r.lease_epoch,"
                             "a.anchor_pid,a.engine_pid,a.supervisor_pid,a.lease_owner,a.lease_epoch,r.status "
                             "FROM hermes_process_evidence p JOIN agent_concurrency_reservations c ON c.run_id=p.run_id AND c.request_key=p.request_key "
                             "JOIN agent_runs r ON r.run_id=p.run_id JOIN hermes_anchor_evidence a ON a.run_id=p.run_id AND a.request_key=p.request_key "
                             "WHERE p.run_id=? AND p.request_key=?", (run_id, request_key)).fetchone()
            if row is None or row[0] not in {"STARTING", "RUNNING", "UNKNOWN"} or row[7] not in {"ACTIVE", "UNKNOWN"}:
                raise ValueError("锚点保守状态不可核查")
            if row[1:7] != (row[8], owner, epoch, row[11], row[12], os.getpid()) or row[9:11] != (owner, epoch) or row[15:20] != (anchor.anchor_pid, anchor.engine_pid, os.getpid(), owner, epoch):
                raise ValueError("锚点记录或租约代次不一致")
            current_owner, current_epoch = row[13:15]
            same_run = current_epoch == epoch and (current_owner == owner or allow_released and current_owner is None)
            if not same_run and not allow_released:
                raise ValueError("锚点记录或租约代次不一致")
            timestamp = utc_now().isoformat()
            if row[0] != "UNKNOWN":
                db.execute("UPDATE hermes_process_evidence SET state='UNKNOWN',updated_at=? WHERE run_id=? AND request_key=?", (timestamp, run_id, request_key))
            if row[7] != "UNKNOWN":
                db.execute("UPDATE agent_concurrency_reservations SET state='UNKNOWN',updated_at=? WHERE run_id=? AND request_key=?", (timestamp, run_id, request_key))
            run_state = row[20]
            if same_run and run_state in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING"}:
                db.execute("UPDATE agent_runs SET status='INTERRUPTED',revision=revision+1 WHERE run_id=?", (run_id,))
                self.store._record_event(db, run_id, "STATUS_CHANGED", {"from": run_state, "to": "INTERRUPTED"}, epoch)
                run_state = "INTERRUPTED"
            return {"process_state": "UNKNOWN", "reservation_state": "UNKNOWN", "run_state": run_state}

    def release(self, run_id, request_key, owner, epoch, anchor, *, timeout=10):
        if not isinstance(anchor, AnchorProcessGroup) or anchor.process.pid != anchor.anchor_pid or anchor.process.poll() is not None:
            raise ValueError("锚点进程不可核查")
        attempted = False
        confirmed = False
        try:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.store._require_lease(db, run_id, owner, epoch)
                self.store.require_active_lineage(db, run_id)
                row = db.execute("SELECT p.state,p.lease_owner,p.lease_epoch,p.supervisor_pid,r.status,r.cancel_requested_at,c.state,a.anchor_pid,a.engine_pid,a.supervisor_pid,a.lease_owner,a.lease_epoch FROM hermes_process_evidence p JOIN agent_runs r ON r.run_id=p.run_id JOIN agent_concurrency_reservations c ON c.run_id=p.run_id AND c.request_key=p.request_key JOIN hermes_anchor_evidence a ON a.run_id=p.run_id AND a.request_key=p.request_key WHERE p.run_id=? AND p.request_key=?", (run_id, request_key)).fetchone()
                if row != ("STARTING", owner, epoch, os.getpid(), "RUNNING", None, "ACTIVE", anchor.anchor_pid, anchor.engine_pid, os.getpid(), owner, epoch):
                    raise ValueError("锚点许可状态不可核查")
                expires_at = db.execute("SELECT lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()[0]
                require_lease_window(expires_at, timeout)
                if anchor.process.poll() is not None:
                    raise ValueError("锚点进程已经退出")
                _require_engine_owned_by_anchor(anchor.anchor_pid, anchor.engine_pid)
                attempted = True
                anchor.release_engine(timeout=timeout)
                self.store._require_lease(db, run_id, owner, epoch)
            confirmed = True
        finally:
            if attempted and not confirmed:
                reclaim_uncertain_anchor(anchor)
