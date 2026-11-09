import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from filelock import FileLock

from agent_run_store import RunConnection, RunStore, utc_now
from hermes_process_launch import process_launch_options


class HermesProcessEvidence:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, RunStore):
            raise ValueError("需要运行存储")
        self.store = store
        self.processes = {}
        self._prepared = {}
        self._prepared_lock = threading.Lock()
        script = (Path(__file__).parent / "migrations/hermes_process_evidence_001.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("hermes_process_evidence_001",)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("进程记录迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_concurrency_reservations'").fetchone() is None:
                raise ValueError("进程记录迁移尚未完成")
            db.executescript("BEGIN IMMEDIATE;\n" + script)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("hermes_process_evidence_001", digest))

    def _require_start_in_transaction(self, db, run_id, request_key, request_digest, owner, epoch, actor_id, space_id):
        if not isinstance(db, RunConnection):
            raise ValueError("进程启动登记需要运行存储连接")
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("进程启动登记需要当前数据库事务")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        self.store._require_lease(db, run_id, owner, epoch)
        self.store.require_active_lineage(db, run_id)
        run = db.execute("SELECT actor_id,space_id,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        reservation = db.execute("SELECT request_digest,lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if run != (actor_id, space_id, "RUNNING", None) or reservation != (request_digest, owner, epoch, "ACTIVE"):
            raise ValueError("运行身份或并发预留不可核查")

    def record_start_in_transaction(self, db, run_id, request_key, request_digest, owner, epoch, actor_id, space_id):
        self._require_start_in_transaction(db, run_id, request_key, request_digest, owner, epoch, actor_id, space_id)
        db.execute("INSERT INTO hermes_process_evidence VALUES (?,?,?,?,?,?,?,'STARTING',NULL,?,NULL,NULL,?)", (run_id, request_key, request_digest, owner, epoch, actor_id, space_id, os.getpid(), utc_now().isoformat()))
        ticket = object()
        with self._prepared_lock:
            self._prepared[ticket] = (db, run_id, request_key, request_digest, owner, epoch, actor_id, space_id)
        return ticket

    def record_vm_start_in_transaction(self, db, bindings, run_id, request_key, request_digest, owner, epoch,
                                       actor_id, space_id, vm_id, boot_id, workspace):
        from hermes_vm_identity import HermesVMRunBindings
        if not isinstance(bindings, HermesVMRunBindings) or bindings.store.path.resolve() != self.store.path.resolve():
            raise ValueError("虚拟机绑定与运行存储不一致")
        self._require_start_in_transaction(db, run_id, request_key, request_digest, owner, epoch, actor_id, space_id)
        db.execute("SAVEPOINT hermes_vm_start")
        ticket = None
        success = False
        try:
            previous = db.execute("SELECT request_digest,lease_owner,lease_epoch,actor_id,space_id,state FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
            if previous is None:
                ticket = self.record_start_in_transaction(db, run_id, request_key, request_digest, owner, epoch, actor_id, space_id)
            else:
                if previous != (request_digest, owner, epoch, actor_id, space_id, "STARTING") or db.execute("SELECT 1 FROM hermes_vm_run_bindings WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone() is None:
                    raise ValueError("已有进程记录与虚拟机启动不一致")
            unit = bindings.register_in_transaction(db, run_id, request_key, owner, epoch, vm_id, boot_id, workspace)
            success = True
            return unit
        finally:
            if ticket is not None:
                with self._prepared_lock:
                    del self._prepared[ticket]
            if not success:
                db.execute("ROLLBACK TO hermes_vm_start")
            db.execute("RELEASE hermes_vm_start")

    def _launch_options(self, run_id, epoch, command, cwd, bootstrap):
        if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("进程命令无效")
        if not Path(command[0]).is_absolute() or not Path(cwd).is_dir():
            raise ValueError("进程执行文件或工作目录无效")
        launch_options = process_launch_options(cwd)
        encoded = None
        if bootstrap is not None:
            fields = {"endpoint", "capability", "run_id", "engine_commit"}
            if not isinstance(bootstrap, dict) or set(bootstrap) not in (fields, fields | {"provider_capability"}) or bootstrap.get("run_id") != run_id or any(not isinstance(value, str) or not value for value in bootstrap.values()):
                raise ValueError("进程通信启动参数无效")
            from hermes_bridge import EngineRunConfig
            EngineRunConfig(run_id, epoch, bootstrap["engine_commit"], bootstrap["endpoint"], 1).validate()
            if len(bootstrap["capability"]) < 32 or not bootstrap["capability"].isascii():
                raise ValueError("进程通信凭据无效")
            if "provider_capability" in bootstrap and (len(bootstrap["provider_capability"]) < 32 or not bootstrap["provider_capability"].isascii() or bootstrap["provider_capability"] == bootstrap["capability"]):
                raise ValueError("模型网关凭据无效")
            encoded = json.dumps(bootstrap, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            if len(encoded) > 4096:
                raise ValueError("进程通信启动参数过长")
            launch_options["stdin"] = subprocess.PIPE
        return launch_options, encoded

    def start(self, run_id, request_key, request_digest, owner, epoch, actor_id, space_id, command, *, cwd, bootstrap=None):
        self._launch_options(run_id, epoch, command, cwd, bootstrap)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ticket = self.record_start_in_transaction(db, run_id, request_key, request_digest, owner, epoch, actor_id, space_id)
        return self.start_prepared(ticket, command, cwd=cwd, bootstrap=bootstrap)

    def prepared_identity(self, ticket):
        with self._prepared_lock:
            prepared = self._prepared.get(ticket)
            if prepared is None:
                raise ValueError("进程启动登记不可使用")
            return prepared[1], prepared[2]

    def bind_prepared_anchor(self, ticket, anchor):
        from hermes_process_anchor import AnchorProcessGroup, _require_engine_owned_by_anchor
        if not isinstance(anchor, AnchorProcessGroup) or not anchor._deferred or anchor.guardian_pid is None or anchor.gate_status is not None:
            raise ValueError("锚点启动状态不可核查")
        with self._prepared_lock:
            prepared = self._prepared.get(ticket)
            if prepared is None:
                raise ValueError("进程启动登记不可使用")
            transaction, run_id, request_key, request_digest, owner, epoch, actor_id, space_id = prepared
            if not transaction.closed and transaction.in_transaction:
                raise ValueError("进程启动事务尚未结束")
            del self._prepared[ticket]
        claimed = False
        bound = False
        try:
            with anchor._read_lock, anchor._reclaim_lock:
                if not anchor._deferred or anchor._reclaim_attempted or anchor.control_write is None or getattr(anchor, "_prepared_binding", None) is not None:
                    raise ValueError("锚点启动状态不可核查")
                anchor._prepared_binding = (run_id, request_key)
                claimed = True
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    self.store._require_lease(db, run_id, owner, epoch)
                    self.store.require_active_lineage(db, run_id)
                    row = db.execute("SELECT r.actor_id,r.space_id,r.status,r.cancel_requested_at,c.request_digest,c.lease_owner,c.lease_epoch,c.state,p.request_digest,p.lease_owner,p.lease_epoch,p.actor_id,p.space_id,p.state,p.pid,p.supervisor_pid FROM agent_runs r JOIN agent_concurrency_reservations c ON c.run_id=r.run_id JOIN hermes_process_evidence p ON p.run_id=c.run_id AND p.request_key=c.request_key WHERE r.run_id=? AND c.request_key=?", (run_id, request_key)).fetchone()
                    expected = (actor_id, space_id, "RUNNING", None, request_digest, owner, epoch, "ACTIVE", request_digest, owner, epoch, actor_id, space_id, "STARTING", None, os.getpid())
                    if row != expected or anchor.process.pid != anchor.anchor_pid or anchor.process.poll() is not None:
                        raise ValueError("锚点启动登记状态不可核查")
                    _require_engine_owned_by_anchor(anchor.anchor_pid, anchor.engine_pid)
                    _require_engine_owned_by_anchor(anchor.anchor_pid, anchor.guardian_pid)
                    db.execute("INSERT INTO hermes_anchor_evidence VALUES (?,?,?,?,?,?,?,?)", (run_id, request_key, anchor.anchor_pid, anchor.engine_pid, os.getpid(), owner, epoch, utc_now().isoformat()))
                bound = True
        finally:
            if claimed and not bound:
                from hermes_anchor_evidence import reclaim_uncertain_anchor
                reclaim_uncertain_anchor(anchor)
        return {"run_id": run_id, "request_key": request_key}

    def start_prepared(self, ticket, command, *, cwd, bootstrap=None):
        with self._prepared_lock:
            prepared = self._prepared.get(ticket)
            if prepared is None:
                raise ValueError("进程启动登记不可使用")
            transaction, run_id, request_key, request_digest, owner, epoch, actor_id, space_id = prepared
            if not transaction.closed and transaction.in_transaction:
                raise ValueError("进程启动事务尚未结束")
            launch_options, encoded = self._launch_options(run_id, epoch, command, cwd, bootstrap)
            del self._prepared[ticket]
        process = None
        recorded = False
        try:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.store._require_lease(db, run_id, owner, epoch)
                self.store.require_active_lineage(db, run_id)
                run = db.execute("SELECT actor_id,space_id,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                reservation = db.execute("SELECT request_digest,lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
                evidence = db.execute("SELECT request_digest,lease_owner,lease_epoch,actor_id,space_id,state,pid,supervisor_pid FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
                if run != (actor_id, space_id, "RUNNING", None) or reservation != (request_digest, owner, epoch, "ACTIVE") or evidence != (request_digest, owner, epoch, actor_id, space_id, "STARTING", None, os.getpid()):
                    raise ValueError("已登记的进程启动状态不可核查")
            process = subprocess.Popen(command, **launch_options)
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.store._require_lease(db, run_id, owner, epoch)
                self.store.require_active_lineage(db, run_id)
                run = db.execute("SELECT actor_id,space_id,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                reservation = db.execute("SELECT request_digest,lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
                if run != (actor_id, space_id, "RUNNING", None) or reservation != (request_digest, owner, epoch, "ACTIVE") or process.poll() is not None or os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
                    raise ValueError("进程启动期间运行状态已经变化")
                changed = db.execute("UPDATE hermes_process_evidence SET state='RUNNING',pid=?,updated_at=? WHERE run_id=? AND request_key=? AND state='STARTING'", (process.pid, utc_now().isoformat(), run_id, request_key))
                if changed.rowcount != 1:
                    raise ValueError("进程启动记录已经变化")
            if encoded is not None:
                process.stdin.write(encoded)
                process.stdin.close()
            self.processes[(run_id, request_key)] = process
            recorded = True
            return process.pid
        finally:
            if not recorded:
                try:
                    if process is not None:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                finally:
                    with self.store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        db.execute("UPDATE hermes_process_evidence SET state='UNKNOWN',updated_at=? WHERE run_id=? AND request_key=? AND state IN ('STARTING','RUNNING')", (utc_now().isoformat(), run_id, request_key))

    def cancel(self, run_id, request_key):
        process = self.processes[(run_id, request_key)]
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT p.pid,p.state,r.cancel_requested_at FROM hermes_process_evidence p JOIN agent_runs r ON r.run_id=p.run_id WHERE p.run_id=? AND p.request_key=?", (run_id, request_key)).fetchone()
            if row is None or row[0] != process.pid or row[1] != "RUNNING":
                raise ValueError("取消状态不可核查")
            if row[2] is None:
                raise ValueError("运行尚未请求取消")
            if process.poll() is not None or os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
                raise ValueError("进程组已经失效")
            os.killpg(process.pid, signal.SIGKILL)

    def observe_exit(self, run_id, request_key):
        process = self.processes[(run_id, request_key)]
        exit_code = process.poll()
        if exit_code is None:
            raise ValueError("进程仍在运行")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT pid,supervisor_pid,state,exit_code,exit_scope FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
            if row is None or row[:2] != (process.pid, os.getpid()):
                raise ValueError("进程身份不可核查")
            if row[2] == "EXITED":
                if row[3:] != (exit_code, "LEADER_ONLY"):
                    raise ValueError("进程退出记录不一致")
                return {"state": "EXITED", "exit_code": exit_code, "exit_scope": "LEADER_ONLY"}
            if row[2] not in {"RUNNING", "UNKNOWN"}:
                raise ValueError("进程退出状态不可核查")
            db.execute("UPDATE hermes_process_evidence SET state='EXITED',exit_code=?,exit_scope='LEADER_ONLY',updated_at=? WHERE run_id=? AND request_key=?", (exit_code, utc_now().isoformat(), run_id, request_key))
        return {"state": "EXITED", "exit_code": exit_code, "exit_scope": "LEADER_ONLY"}

    def mark_unknown(self, run_id, request_key):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT p.state,p.lease_owner,p.lease_epoch,r.lease_owner,r.lease_epoch,r.lease_expires_at FROM hermes_process_evidence p JOIN agent_runs r ON r.run_id=p.run_id WHERE p.run_id=? AND p.request_key=?", (run_id, request_key)).fetchone()
            if row is None:
                raise ValueError("进程记录不存在")
            if row[0] in {"UNKNOWN", "EXITED"}:
                return row[0]
            if row[1:3] == row[3:5] and row[5] is not None and datetime.fromisoformat(row[5]) > utc_now():
                raise ValueError("原租约仍然有效")
            db.execute("UPDATE hermes_process_evidence SET state='UNKNOWN',updated_at=? WHERE run_id=? AND request_key=?", (utc_now().isoformat(), run_id, request_key))
            return "UNKNOWN"

    def read(self, run_id, request_key):
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
            if row is None:
                raise ValueError("进程记录不存在")
            return dict(row)
