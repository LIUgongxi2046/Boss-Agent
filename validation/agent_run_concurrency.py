import hashlib
from datetime import datetime
from pathlib import Path

from filelock import FileLock

from agent_run_store import RunStore, utc_now


class RunConcurrencyBudget:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, RunStore):
            raise ValueError("需要运行存储")
        self.store = store
        script = (Path(__file__).parent / "migrations" / "upgrade2_concurrency_001.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("upgrade2_concurrency_001",)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("并发额度迁移摘要不符")
                return
            existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('agent_concurrency_budgets','agent_concurrency_reservations')").fetchone()
            if existing is not None or not allow_migration:
                raise ValueError("并发额度迁移尚未完成")
            db.executescript("BEGIN IMMEDIATE;\n" + script)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("upgrade2_concurrency_001", digest))

    def _require_transaction(self, db):
        if not db.in_transaction:
            raise ValueError("并发额度需要数据库事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("并发额度数据库不匹配")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")

    def configure(self, root_run_id, owner, epoch, max_concurrency):
        if type(max_concurrency) is not int or max_concurrency <= 0:
            raise ValueError("并发额度无效")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store._require_lease(db, root_run_id, owner, epoch)
            if self.store.require_active_lineage(db, root_run_id) != root_run_id:
                raise ValueError("并发额度仅可由根运行配置")
            existing = db.execute("SELECT max_concurrency FROM agent_concurrency_budgets WHERE root_run_id=?", (root_run_id,)).fetchone()
            if existing is not None:
                if existing[0] != max_concurrency:
                    raise ValueError("并发额度已经变化")
                return
            db.execute("INSERT INTO agent_concurrency_budgets VALUES (?,?)", (root_run_id, max_concurrency))

    def reserve_in_transaction(self, db, run_id, owner, epoch, request_key, request_digest):
        self._require_transaction(db)
        if any(not isinstance(value, str) or not value for value in (run_id, owner, request_key, request_digest)):
            raise ValueError("并发预留参数无效")
        self.store._require_lease(db, run_id, owner, epoch)
        root = self.store.require_active_lineage(db, run_id)
        status = db.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if status is None or status[0] != "RUNNING":
            raise ValueError("运行状态不能预留并发额度")
        budget = db.execute("SELECT max_concurrency FROM agent_concurrency_budgets WHERE root_run_id=?", (root,)).fetchone()
        if budget is None:
            raise ValueError("根运行尚未配置并发额度")
        old = db.execute("SELECT root_run_id,request_digest,lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if old is not None:
            if old[:4] != (root, request_digest, owner, epoch):
                raise ValueError("并发预留请求冲突")
            return {"state": old[4], "created": False}
        occupied = db.execute("SELECT count(*) FROM agent_concurrency_reservations WHERE root_run_id=? AND state IN ('ACTIVE','UNKNOWN')", (root,)).fetchone()[0]
        if occupied >= budget[0]:
            raise ValueError("并发额度不足")
        timestamp = utc_now().isoformat()
        db.execute("INSERT INTO agent_concurrency_reservations VALUES (?,?,?,?,?,?,'ACTIVE',?,?)", (run_id, request_key, root, request_digest, owner, epoch, timestamp, timestamp))
        return {"state": "ACTIVE", "created": True}

    def release_in_transaction(self, db, run_id, owner, epoch, request_key, request_digest):
        self._require_transaction(db)
        self.store._require_lease(db, run_id, owner, epoch)
        row = db.execute("SELECT request_digest,lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if row is None or row[:3] != (request_digest, owner, epoch):
            raise ValueError("并发预留不可核查")
        if row[3] == "RELEASED":
            return "RELEASED"
        if row[3] != "ACTIVE":
            raise ValueError("并发预留需要核查原执行")
        evidence_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_process_evidence'").fetchone()
        if evidence_table is not None and db.execute("SELECT 1 FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone() is not None:
            raise ValueError("进程范围尚未确认，不能释放并发额度")
        db.execute("UPDATE agent_concurrency_reservations SET state='RELEASED',updated_at=? WHERE run_id=? AND request_key=?", (utc_now().isoformat(), run_id, request_key))
        return "RELEASED"

    def recover_in_transaction(self, db, run_id, request_key):
        self._require_transaction(db)
        reservation = db.execute("SELECT c.request_digest,c.lease_owner,c.lease_epoch,c.state,r.actor_id,r.space_id,r.lease_owner,r.lease_epoch,r.lease_expires_at FROM agent_concurrency_reservations c JOIN agent_runs r ON r.run_id=c.run_id WHERE c.run_id=? AND c.request_key=?", (run_id, request_key)).fetchone()
        if reservation is None:
            raise ValueError("并发预留不存在")
        evidence = db.execute("SELECT request_digest,lease_owner,lease_epoch,actor_id,space_id,state,exit_scope FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if evidence is not None and evidence[:5] != (reservation[0], reservation[1], reservation[2], reservation[4], reservation[5]):
            raise ValueError("进程记录与并发预留不一致")
        state = reservation[3]
        lease_valid = reservation[1:3] == reservation[6:8] and reservation[8] is not None and datetime.fromisoformat(reservation[8]) > utc_now()
        if state == "ACTIVE" and evidence is not None and evidence[5] in {"UNKNOWN", "EXITED"}:
            db.execute("UPDATE agent_concurrency_reservations SET state='UNKNOWN',updated_at=? WHERE run_id=? AND request_key=?", (utc_now().isoformat(), run_id, request_key))
            state = "UNKNOWN"
        elif state == "ACTIVE" and not lease_valid:
            state = self.mark_unknown_in_transaction(db, run_id, request_key)
        return {"state": state, "process_state": evidence[5] if evidence else None, "exit_scope": evidence[6] if evidence else None}

    def mark_unknown_in_transaction(self, db, run_id, request_key):
        self._require_transaction(db)
        row = db.execute("SELECT c.lease_owner,c.lease_epoch,c.state,r.lease_owner,r.lease_epoch,r.lease_expires_at FROM agent_concurrency_reservations c JOIN agent_runs r ON r.run_id=c.run_id WHERE c.run_id=? AND c.request_key=?", (run_id, request_key)).fetchone()
        if row is None:
            raise ValueError("并发预留不存在")
        if row[2] != "ACTIVE":
            return row[2]
        if row[3] == row[0] and row[4] == row[1] and row[5] is not None and datetime.fromisoformat(row[5]) > utc_now():
            raise ValueError("原租约仍然有效")
        db.execute("UPDATE agent_concurrency_reservations SET state='UNKNOWN',updated_at=? WHERE run_id=? AND request_key=?", (utc_now().isoformat(), run_id, request_key))
        return "UNKNOWN"
