import json
import hashlib
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from filelock import FileLock
from jsonschema import Draft202012Validator, FormatChecker
from hermes_source_invalidation import require_source_cleanup_complete


def utc_now():
    return datetime.now(timezone.utc)


TRANSITIONS = {
    "QUEUED": {"RUNNING", "CANCELED", "FAILED"},
    "RUNNING": {"WAITING_INPUT", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING", "SUCCEEDED", "FAILED", "INTERRUPTED"},
    "WAITING_INPUT": {"RUNNING", "CANCEL_REQUESTED", "FAILED", "INTERRUPTED"},
    "WAITING_CONFIRMATION": {"RUNNING", "CANCEL_REQUESTED", "FAILED", "INTERRUPTED"},
    "CANCEL_REQUESTED": {"RECONCILING", "CANCELED", "INTERRUPTED"},
    "RECONCILING": {"RUNNING", "WAITING_INPUT", "CANCELED", "FAILED", "INTERRUPTED"},
    "INTERRUPTED": {"RECONCILING", "QUEUED", "CANCELED"},
}
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED"}
EVENT_SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "specs/agent-events.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(EVENT_SCHEMA)
EVENT_VALIDATOR = Draft202012Validator({"$ref": "#/$defs/event", "$defs": EVENT_SCHEMA["$defs"]}, format_checker=FormatChecker())


class RunConnection(sqlite3.Connection):
    _closed = False
    _context_depth = 0

    @property
    def closed(self):
        return self._closed

    def close(self):
        super().close()
        self._closed = True

    def __enter__(self):
        result = super().__enter__()
        self._context_depth += 1
        return result

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self._context_depth -= 1
            if self._context_depth == 0:
                self.close()


class RunStore:
    def __init__(self, path, *, allow_migration=True):
        self.path = Path(path)
        if not allow_migration and not self.path.is_file():
            raise FileNotFoundError("运行数据库尚未建立")
        migration = Path(__file__).parent / "migrations/upgrade2_001.sql"
        script = migration.read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(self.path) + ".migration.lock", timeout=10):
            with self.connect() as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_schema_migrations'").fetchone()
                if exists:
                    row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_001'").fetchone()
                    if row is None or row[0] != digest:
                        raise ValueError("迁移版本摘要不符")
                    return
                existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('agent_runs','agent_run_events','agent_request_keys','agent_run_inputs','agent_run_operations','agent_api_requests')").fetchone()
                if existing:
                    raise ValueError("已有运行表缺少迁移版本")
                if not allow_migration:
                    raise ValueError("运行数据库尚未完成迁移")
                db.executescript("BEGIN IMMEDIATE;\n" + script + "\nINSERT INTO agent_schema_migrations VALUES ('upgrade2_001', '" + digest + "');\nCOMMIT;")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, factory=RunConnection)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def create_run(self, actor_id, space_id, request_key, request_digest):
        if any(not isinstance(value, str) or not value for value in (actor_id, space_id, request_key, request_digest)):
            raise ValueError("请求字段无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT request_digest, run_id FROM agent_request_keys WHERE actor_id=? AND space_id=? AND request_key=?", (actor_id, space_id, request_key)).fetchone()
            if row:
                if row[0] != request_digest:
                    raise ValueError("请求键内容冲突")
                return row[1]
            run_id = str(uuid4())
            db.execute("INSERT INTO agent_runs (run_id,actor_id,space_id,revision,status,goal_revision,applied_goal_revision,last_input_seq,lease_epoch,last_event_seq,created_at) VALUES (?, ?, ?, 0, 'QUEUED', 1, 1, 0, 0, 0, ?)", (run_id, actor_id, space_id, utc_now().isoformat()))
            db.execute("INSERT INTO agent_request_keys VALUES (?, ?, ?, ?, ?)", (actor_id, space_id, request_key, request_digest, run_id))
            return run_id

    def create_child_run(self, parent_run_id, owner, epoch, request_key, request_digest):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.create_child_run_in_transaction(db, parent_run_id, owner, epoch, request_key, request_digest)

    def create_child_run_in_transaction(self, db, parent_run_id, owner, epoch, request_key, request_digest):
        if any(not isinstance(value, str) or not value for value in (parent_run_id, owner, request_key, request_digest)):
            raise ValueError("子运行请求无效")
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.path.resolve():
            raise ValueError("子运行创建需要当前数据库事务")
        self._require_lease(db, parent_run_id, owner, epoch)
        self.require_active_lineage(db, parent_run_id)
        parent = db.execute("SELECT actor_id,space_id,conversation_id,goal,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (parent_run_id,)).fetchone()
        digest = hashlib.sha256(json.dumps([parent_run_id, request_digest], separators=(',', ':')).encode()).hexdigest()
        old = db.execute("SELECT request_digest,run_id FROM agent_request_keys WHERE actor_id=? AND space_id=? AND request_key=?", (parent[0], parent[1], request_key)).fetchone()
        if old:
            if old[0] != digest:
                raise ValueError("子运行请求编号冲突")
            return old[1]
        child = str(uuid4())
        db.execute("INSERT INTO agent_runs (run_id,parent_run_id,actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,revision,status,goal_revision,applied_goal_revision,last_input_seq,lease_epoch,last_event_seq,created_at) VALUES (?,?,?,?,?,?,?,?,0,'QUEUED',1,1,0,0,0,?)", (child, parent_run_id, *parent, utc_now().isoformat()))
        db.execute("INSERT INTO agent_request_keys VALUES (?,?,?,?,?)", (parent[0], parent[1], request_key, digest, child))
        return child

    @staticmethod
    def require_active_lineage(db, run_id):
        seen = set()
        current = run_id
        identity = None
        while current is not None:
            if current in seen:
                raise ValueError("运行关系存在循环")
            seen.add(current)
            row = db.execute("SELECT parent_run_id,actor_id,space_id,status,cancel_requested_at,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (current,)).fetchone()
            if row is None or row[3] not in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"} or row[4] is not None:
                raise ValueError("运行或父运行已经取消或不可执行")
            if identity is None:
                identity = row[1:3]
            if row[1:3] != identity:
                raise ValueError("父子运行主体或空间不一致")
            RunStore._require_lease(db, current, row[5], row[6])
            root = current
            current = row[0]
        return root

    @staticmethod
    def require_terminal_lineage(db, run_id):
        seen = set()
        current = run_id
        identity = None
        while current is not None:
            if current in seen:
                raise ValueError("运行关系存在循环")
            seen.add(current)
            row = db.execute("SELECT parent_run_id,actor_id,space_id FROM agent_runs WHERE run_id=?", (current,)).fetchone()
            if row is None:
                raise ValueError("运行或父运行不存在")
            if identity is None:
                identity = row[1:3]
            if row[1:3] != identity:
                raise ValueError("父子运行主体或空间不一致")
            root = current
            current = row[0]
        return root

    def configure_file_budget(self, root_run_id, owner, epoch, max_files, max_bytes):
        if type(max_files) is not int or max_files <= 0 or type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("文件预算无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_lease(db, root_run_id, owner, epoch)
            if self.require_active_lineage(db, root_run_id) != root_run_id:
                raise ValueError("文件预算仅可由根运行配置")
            row = db.execute("SELECT max_files,max_bytes FROM agent_file_budgets WHERE root_run_id=?", (root_run_id,)).fetchone()
            if row is not None:
                if row != (max_files, max_bytes):
                    raise ValueError("运行文件预算已经变化")
                return
            db.execute("INSERT INTO agent_file_budgets VALUES (?,?,?)", (root_run_id, max_files, max_bytes))

    def reserve_file_in_transaction(self, db, run_id, owner, epoch, request_key, digest, artifact_id, size_bytes, *, allow_reserved=False):
        if not db.in_transaction or any(not isinstance(value, str) or not value for value in (request_key, digest, artifact_id)) or type(size_bytes) is not int or size_bytes <= 0:
            raise ValueError("文件预留参数无效")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.path.resolve():
            raise ValueError("文件预留数据库不匹配")
        self._require_lease(db, run_id, owner, epoch)
        root = self.require_active_lineage(db, run_id)
        budget = db.execute("SELECT max_files,max_bytes FROM agent_file_budgets WHERE root_run_id=?", (root,)).fetchone()
        if budget is None:
            raise ValueError("运行文件预算尚未配置")
        old = db.execute("SELECT request_digest,artifact_id,status,root_run_id FROM agent_file_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if old is not None:
            if old[0] != digest or old[3] != root:
                raise ValueError("成果请求编号对应的内容已经变化")
            if old[2] == "RELEASED":
                raise ValueError("成果请求已经终止")
            if old[2] != "COMPLETED" and not allow_reserved:
                raise ValueError("成果请求结果尚待核查")
            return old[1]
        count, total = db.execute("SELECT count(*),coalesce(sum(size_bytes),0) FROM agent_file_reservations WHERE root_run_id=? AND status IN ('RESERVED','COMPLETED')", (root,)).fetchone()
        if count + 1 > budget[0] or total + size_bytes > budget[1]:
            raise ValueError("运行文件预算不足")
        db.execute("INSERT INTO agent_file_reservations VALUES (?,?,?,?,?,?,'RESERVED')", (artifact_id, root, run_id, request_key, digest, size_bytes))
        return None

    def acquire_lease(self, run_id, expected_revision, owner, ttl):
        if not isinstance(owner, str) or not owner or isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("租约参数无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision, lease_epoch, lease_expires_at, status, cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            now = utc_now()
            if row is None or row[0] != expected_revision or row[3] not in ('QUEUED', 'INTERRUPTED', 'RECONCILING') or row[4] is not None or row[2] is not None and datetime.fromisoformat(row[2]) > now:
                raise ValueError("租约不可取得")
            require_source_cleanup_complete(db, run_id)
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_process_evidence'").fetchone() is not None and db.execute("SELECT 1 FROM hermes_process_evidence WHERE run_id=? LIMIT 1", (run_id,)).fetchone() is not None:
                raise ValueError("进程状态记录已保存，不能重新取得租约")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_concurrency_reservations'").fetchone() is not None and db.execute("SELECT 1 FROM agent_concurrency_reservations WHERE run_id=? AND state IN ('ACTIVE','UNKNOWN') LIMIT 1", (run_id,)).fetchone() is not None:
                raise ValueError("并发预留尚未核查，不能重新取得租约")
            epoch = row[1] + 1
            expires = (now + timedelta(seconds=ttl)).isoformat()
            db.execute("UPDATE agent_runs SET lease_owner=?, lease_epoch=?, lease_expires_at=?, revision=revision+1 WHERE run_id=?", (owner, epoch, expires, run_id))
            return {"epoch": epoch, "expires_at": expires, "revision": row[0] + 1}

    def acquire_queued_for_execution(self, run_id, expected_revision, owner, ttl):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.acquire_queued_in_transaction(db, run_id, expected_revision, owner, ttl)

    def requeue_waiting_in_transaction(self, db, run_id, expected_revision, expected_goal_revision, request_key):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.path.resolve():
            raise ValueError("等待运行恢复需要同一数据库事务")
        if type(expected_revision) is not int or expected_revision < 0 or type(expected_goal_revision) is not int or expected_goal_revision < 1 or not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("等待运行恢复参数无效")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        key = "waiting-resume:" + request_key
        old = db.execute("SELECT operation,expected_revision,receipt FROM agent_run_operations WHERE run_id=? AND request_key=?", (run_id, key)).fetchone()
        if old is not None:
            receipt = json.loads(old[2])
            if not isinstance(receipt, dict) or set(receipt) != {"run_id", "status", "revision", "goal_revision"} or receipt["run_id"] != run_id or receipt["status"] != "QUEUED" or type(receipt["revision"]) is not int or receipt["revision"] != old[1] + 2 or type(receipt["goal_revision"]) is not int:
                raise ValueError("等待运行恢复回执不可核查")
            if old[0] != "waiting_resume" or old[1] != expected_revision or receipt["goal_revision"] != expected_goal_revision:
                raise ValueError("等待运行恢复请求冲突")
            return receipt
        row = db.execute("SELECT status,revision,goal_revision,applied_goal_revision,cancel_requested_at,lease_owner,lease_epoch,lease_expires_at,parent_run_id,last_input_seq FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[0] != "WAITING_INPUT" or row[1] != expected_revision or row[2] != expected_goal_revision or row[4] is not None or row[8] is not None:
            raise ValueError("等待运行状态或目标版本已经变化")
        if row[7] is not None and datetime.fromisoformat(row[7]) > utc_now():
            raise ValueError("原租约仍然有效")
        if (row[5] is None) != (row[7] is None):
            raise ValueError("原租约记录不可核查")
        require_source_cleanup_complete(db, run_id)
        from agent_run_requirements import RunRequirements
        requirements = RunRequirements.read_in_transaction(db, run_id, expected_goal_revision)
        if requirements["state"] != "CONFIRMED":
            raise ValueError("当前目标成果要求尚未确认")
        for version in ("upgrade2_concurrency_001", "hermes_process_evidence_001", "upgrade2_intents_001"):
            migration = Path(__file__).parent / "migrations" / (version + ".sql")
            expected = hashlib.sha256(migration.read_bytes()).hexdigest()
            saved = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (version,)).fetchone()
            if saved is None or saved[0] != expected:
                raise ValueError("运行恢复依赖迁移不可核查")
        waiting = db.execute("SELECT max(seq) FROM agent_run_events WHERE run_id=? AND type='STATUS_CHANGED' AND json_extract(payload,'$.to')='WAITING_INPUT'", (run_id,)).fetchone()[0]
        inputs = db.execute("SELECT input_id,input_seq,goal_revision,applied_event_id FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq", (run_id,)).fetchall()
        if len(inputs) != row[9] or row[2] != len(inputs) + 1 or any(item[1] != index or item[2] != index + 1 or (item[3] is not None) != (item[2] <= row[3]) for index, item in enumerate(inputs, 1)):
            raise ValueError("补充输入顺序不可核查")
        for item in inputs:
            if item[3] is not None:
                applied = db.execute("SELECT type,payload FROM agent_run_events WHERE run_id=? AND event_id=?", (run_id, item[3])).fetchone()
                if applied is None or applied[0] != "INPUT_APPLIED" or json.loads(applied[1]) != {"input_id": item[0], "input_seq": item[1], "goal_revision": item[2]}:
                    raise ValueError("补充输入采用记录不可核查")
        received = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND type='INPUT_RECEIVED' AND json_extract(payload,'$.input_id')=?", (run_id, inputs[-1][0])).fetchall() if inputs else []
        if waiting is None or len(received) != 1 or received[0][0] <= waiting or json.loads(received[0][1]) != {"input_id": inputs[-1][0], "input_seq": inputs[-1][1], "goal_revision": inputs[-1][2]} or row[2] <= 1 or not 1 <= row[3] <= row[2]:
            raise ValueError("等待后的补充输入不可核查")
        wait_payload = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND seq=?", (run_id, waiting)).fetchone()
        if wait_payload is None:
            raise ValueError("等待状态事件不可核查")
        if json.loads(wait_payload[0]).get("reason") == "INPUT_REQUIRED":
            from agent_run_broker import RunBroker
            original_factory = db.row_factory
            db.row_factory = sqlite3.Row
            current = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            db.row_factory = original_factory
            question = RunBroker._waiting_input_in_transaction(db, current, include_answered=True)
            if question is None or inputs[-1][2] <= question["goal_revision"]:
                raise ValueError("等待问题与补充目标不可核查")
            previous_seq = waiting
            for item in inputs:
                if item[2] <= question["goal_revision"]:
                    continue
                request = db.execute("SELECT request_key FROM agent_run_inputs WHERE run_id=? AND input_id=?", (run_id, item[0])).fetchone()
                run_identity = db.execute("SELECT actor_id,space_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                saved = db.execute("SELECT receipt FROM agent_api_requests WHERE actor_id=? AND space_id=? AND run_id=? AND request_key=? AND operation='inputs'", (*run_identity, run_id, request[0])).fetchone() if request is not None and run_identity is not None else None
                if saved is None:
                    raise ValueError("补充输入原请求不可核查")
                RunBroker.verify_input_receipt_in_transaction(db, run_id, request[0], json.loads(saved[0]))
                event = db.execute("SELECT seq FROM agent_run_events WHERE run_id=? AND type='INPUT_RECEIVED' AND json_extract(payload,'$.input_id')=?", (run_id, item[0])).fetchone()
                if event is None or event[0] <= previous_seq:
                    raise ValueError("等待后补充输入事件顺序不可核查")
                previous_seq = event[0]
        if db.execute("SELECT 1 FROM agent_concurrency_reservations WHERE root_run_id=? AND state IN ('ACTIVE','UNKNOWN') LIMIT 1", (run_id,)).fetchone() is not None:
            raise ValueError("原进程并发额度尚未释放")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_model_requests'").fetchone() is not None and db.execute("SELECT 1 FROM hermes_model_requests WHERE root_run_id=? AND state='UNKNOWN' LIMIT 1", (run_id,)).fetchone() is not None:
            raise ValueError("原模型请求结果尚未核查")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_dispatch_receipts'").fetchone() is not None and db.execute("SELECT 1 FROM agent_dispatch_receipts d WHERE d.state IN ('ACCEPTED','UNKNOWN') AND (d.run_id=? OR EXISTS (SELECT 1 FROM agent_concurrency_reservations c WHERE c.root_run_id=? AND c.run_id=d.run_id AND c.lease_epoch=d.lease_epoch)) LIMIT 1", (run_id, run_id)).fetchone() is not None:
            raise ValueError("原派发结果尚未核查")
        from agent_run_result import root_vm_tree_exits_verified
        if not root_vm_tree_exits_verified(db, run_id):
            raise ValueError("原进程范围尚未确认")
        if db.execute("SELECT 1 FROM agent_file_reservations WHERE root_run_id=? AND status='RESERVED' LIMIT 1", (run_id,)).fetchone() is not None or db.execute("SELECT 1 FROM agent_intents WHERE run_id=? AND status NOT IN ('SUCCEEDED','FAILED','REJECTED','EXPIRED') LIMIT 1", (run_id,)).fetchone() is not None:
            raise ValueError("原业务操作尚未核查")
        db.execute("UPDATE agent_runs SET status='INTERRUPTED',lease_owner=NULL,lease_expires_at=NULL,revision=revision+1 WHERE run_id=?", (run_id,))
        self._record_event(db, run_id, "STATUS_CHANGED", {"from": "WAITING_INPUT", "to": "INTERRUPTED"}, row[6])
        db.execute("UPDATE agent_runs SET status='QUEUED',revision=revision+1 WHERE run_id=?", (run_id,))
        self._record_event(db, run_id, "STATUS_CHANGED", {"from": "INTERRUPTED", "to": "QUEUED"}, row[6])
        receipt = {"run_id": run_id, "status": "QUEUED", "revision": row[1] + 2, "goal_revision": expected_goal_revision}
        db.execute("INSERT INTO agent_run_operations VALUES (?,?,'waiting_resume',?,?)", (run_id, key, expected_revision, json.dumps(receipt, sort_keys=True, separators=(",", ":"))))
        return receipt

    def acquire_queued_in_transaction(self, db, run_id, expected_revision, owner, ttl):
        if not isinstance(owner, str) or not owner or isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("租约参数无效")
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.path.resolve():
            raise ValueError("运行领取需要同一数据库事务")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        row = db.execute("SELECT revision,lease_epoch,lease_expires_at,status,cancel_requested_at,parent_run_id,actor_id,space_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        now = utc_now()
        if row is None or row[0] != expected_revision or row[3] != "QUEUED" or row[4] is not None or row[2] is not None and datetime.fromisoformat(row[2]) > now:
            raise ValueError("排队运行不可取得")
        require_source_cleanup_complete(db, run_id)
        if row[5] is not None:
            self.require_active_lineage(db, row[5])
            parent_identity = db.execute("SELECT actor_id,space_id FROM agent_runs WHERE run_id=?", (row[5],)).fetchone()
            if parent_identity != row[6:8]:
                raise ValueError("父子运行主体或空间不一致")
        epoch = row[1] + 1
        expires = (now + timedelta(seconds=ttl)).isoformat()
        db.execute("UPDATE agent_runs SET lease_owner=?,lease_epoch=?,lease_expires_at=?,status='RUNNING',revision=revision+1 WHERE run_id=?", (owner, epoch, expires, run_id))
        self._record_event(db, run_id, "STATUS_CHANGED", {"from": "QUEUED", "to": "RUNNING"}, epoch)
        return {"epoch": epoch, "expires_at": expires, "revision": row[0] + 1}

    def renew_lease(self, run_id, owner, epoch, ttl):
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("租约参数无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT lease_owner, lease_epoch, lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            now = utc_now()
            if row is None or row[0] != owner or row[1] != epoch or row[2] is None or datetime.fromisoformat(row[2]) <= now:
                raise ValueError("租约无效")
            require_source_cleanup_complete(db, run_id)
            expires = (now + timedelta(seconds=ttl)).isoformat()
            db.execute("UPDATE agent_runs SET lease_expires_at=?, revision=revision+1 WHERE run_id=?", (expires, run_id))
            return expires

    def release_lease(self, run_id, owner, epoch):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT lease_owner, lease_epoch, lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[0] != owner or row[1] != epoch or row[2] is None or datetime.fromisoformat(row[2]) <= utc_now():
                raise ValueError("租约无效")
            db.execute("UPDATE agent_runs SET lease_owner=NULL, lease_expires_at=NULL, revision=revision+1 WHERE run_id=?", (run_id,))

    @staticmethod
    def _require_lease_identity(db, run_id, owner, epoch):
        row = db.execute("SELECT lease_owner, lease_epoch, lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[0] != owner or row[1] != epoch or row[2] is None or datetime.fromisoformat(row[2]) <= utc_now():
            raise ValueError("租约无效")

    @staticmethod
    def _require_lease(db, run_id, owner, epoch):
        RunStore._require_lease_identity(db, run_id, owner, epoch)
        require_source_cleanup_complete(db, run_id)

    @staticmethod
    def _record_event(db, run_id, event_type, payload, epoch=0, origin_event_id=None):
        seq = db.execute("SELECT last_event_seq FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()[0] + 1
        event_id = str(uuid4())
        occurred = utc_now().isoformat()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        db.execute("INSERT INTO agent_run_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (event_id, run_id, seq, origin_event_id or event_id, epoch, event_type, occurred, str(uuid4()), 1, encoded))
        db.execute("UPDATE agent_runs SET last_event_seq=? WHERE run_id=?", (seq, run_id))
        return event_id

    def read_run(self, run_id):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("运行不存在")
            return dict(row)

    def transition(self, run_id, expected_revision, status, owner, epoch, *, verified=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if status in {"FAILED", "INTERRUPTED", "CANCELED", "RECONCILING"}:
                self._require_lease_identity(db, run_id, owner, epoch)
            else:
                self._require_lease(db, run_id, owner, epoch)
            row = db.execute("SELECT status, revision, cancel_requested_at, goal_revision, applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row[1] != expected_revision or status not in TRANSITIONS.get(row[0], set()):
                raise ValueError("运行状态转换无效")
            if status == "CANCEL_REQUESTED":
                raise ValueError("取消需要本人请求")
            if row[2] is not None and status in {"RUNNING", "QUEUED", "WAITING_INPUT", "WAITING_CONFIRMATION", "SUCCEEDED"}:
                raise ValueError("运行已经请求取消")
            if status == "SUCCEEDED":
                raise ValueError("运行完成条件核查服务尚未接入")
            if status == "CANCELED" and verified is not True:
                raise ValueError("结果尚未核查")
            db.execute("UPDATE agent_runs SET status=?, revision=revision+1 WHERE run_id=?", (status, run_id))
            self._record_event(db, run_id, "STATUS_CHANGED", {"from": row[0], "to": status}, epoch)

    def add_input(self, run_id, expected_goal_revision, request_key, content):
        if not isinstance(request_key, str) or not request_key or not isinstance(content, str) or not content.strip():
            raise ValueError("补充输入无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status, goal_revision, last_input_seq, cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("运行不存在")
            existing = db.execute("SELECT input_id, input_seq, goal_revision, content FROM agent_run_inputs WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
            if existing:
                if existing[3] != content or existing[2] != expected_goal_revision + 1:
                    raise ValueError("补充请求冲突")
                return {"input_id": existing[0], "input_seq": existing[1], "goal_revision": existing[2]}
            if row[0] not in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"} or row[3] is not None or row[1] != expected_goal_revision:
                raise ValueError("补充目标版本无效")
            input_id, seq, revision = str(uuid4()), row[2] + 1, row[1] + 1
            db.execute("INSERT INTO agent_run_inputs VALUES (?, ?, ?, ?, ?, ?, NULL)", (input_id, run_id, seq, revision, request_key, content))
            db.execute("UPDATE agent_runs SET last_input_seq=?, goal_revision=?, revision=revision+1 WHERE run_id=?", (seq, revision, run_id))
            self._record_event(db, run_id, "INPUT_RECEIVED", {"input_id": input_id, "input_seq": seq, "goal_revision": revision})
            return {"input_id": input_id, "input_seq": seq, "goal_revision": revision}

    def apply_input(self, run_id, input_seq, owner, epoch):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_lease(db, run_id, owner, epoch)
            row = db.execute("SELECT status, cancel_requested_at, applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            item = db.execute("SELECT input_id, goal_revision, applied_event_id FROM agent_run_inputs WHERE run_id=? AND input_seq=?", (run_id, input_seq)).fetchone()
            if row[0] not in {"RUNNING", "WAITING_INPUT"} or row[1] is not None or item is None:
                raise ValueError("输入不能采用")
            if item[2] is not None:
                return item[2]
            if item[1] != row[2] + 1:
                raise ValueError("输入顺序无效")
            event_id = self._record_event(db, run_id, "INPUT_APPLIED", {"input_id": item[0], "input_seq": input_seq, "goal_revision": item[1]}, epoch)
            db.execute("UPDATE agent_run_inputs SET applied_event_id=? WHERE input_id=?", (event_id, item[0]))
            db.execute("UPDATE agent_runs SET applied_goal_revision=?, revision=revision+1 WHERE run_id=?", (item[1], run_id))
            return event_id

    def interrupt_expired(self, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status, lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[0] not in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING"} or row[1] is None or datetime.fromisoformat(row[1]) > utc_now():
                raise ValueError("运行租约尚未失效")
            db.execute("UPDATE agent_runs SET status='INTERRUPTED', lease_owner=NULL, lease_expires_at=NULL, revision=revision+1 WHERE run_id=?", (run_id,))
            self._record_event(db, run_id, "STATUS_CHANGED", {"from": row[0], "to": "INTERRUPTED"})

    def cancel(self, run_id, expected_revision, *, request_key=None):
        if request_key is not None and (not isinstance(request_key, str) or not request_key):
            raise ValueError("取消请求键无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_key is not None:
                old = db.execute("SELECT operation, expected_revision, receipt FROM agent_run_operations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
                if old:
                    if old[0] != "cancel" or old[1] != expected_revision:
                        raise ValueError("取消请求键冲突")
                    return json.loads(old[2])
            row = db.execute("SELECT status, revision, cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[1] != expected_revision or row[2] is not None or row[0] not in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "RECONCILING", "INTERRUPTED"}:
                raise ValueError("运行不能取消")
            status = "CANCELED" if row[0] == "QUEUED" else row[0] if row[0] in {"RECONCILING", "INTERRUPTED"} else "CANCEL_REQUESTED"
            db.execute("UPDATE agent_runs SET status=?, cancel_requested_at=?, revision=revision+1 WHERE run_id=?", (status, utc_now().isoformat(), run_id))
            self._record_event(db, run_id, "STATUS_CHANGED", {"from": row[0], "to": status})
            receipt = {"run_id": run_id, "status": status, "revision": row[1] + 1}
            if request_key is not None:
                db.execute("INSERT INTO agent_run_operations VALUES (?, ?, 'cancel', ?, ?)", (run_id, request_key, expected_revision, json.dumps(receipt)))
            return receipt

    def append_event(self, run_id, owner, epoch, origin_event_id, event_type, payload, *, trace_id=None, payload_version=1):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.append_event_in_transaction(db, run_id, owner, epoch, origin_event_id, event_type, payload, trace_id=trace_id, payload_version=payload_version)

    def append_event_in_transaction(self, db, run_id, owner, epoch, origin_event_id, event_type, payload, *, trace_id=None, payload_version=1):
        if not db.in_transaction:
            raise ValueError("事件写入需要事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.path.resolve():
            raise ValueError("事件写入数据库不匹配")
        if not isinstance(origin_event_id, str) or not origin_event_id or not isinstance(event_type, str) or not event_type or not isinstance(payload, dict):
            raise ValueError("事件字段无效")
        if event_type == "ARTIFACT_CANDIDATE":
            raise ValueError("成果事件需要成果服务登记")
        if event_type == "RESULT_RECORDED":
            raise ValueError("运行结果需要结果服务登记")
        candidate = {"event_id": str(uuid4()), "run_id": run_id, "seq": 1, "type": event_type, "occurred_at": utc_now().isoformat(), "trace_id": trace_id if trace_id is not None else str(uuid4()), "payload_version": payload_version, "payload": payload}
        if not EVENT_VALIDATOR.is_valid(candidate) or type(payload_version) is not int:
            raise ValueError("事件类型或版本无效")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        row = db.execute("SELECT lease_owner, lease_epoch, lease_expires_at, last_event_seq, status, cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[0] != owner or row[1] != epoch or row[2] is None or datetime.fromisoformat(row[2]) <= utc_now():
            raise ValueError("租约无效")
        existing = db.execute("SELECT event_id, seq, type, occurred_at, trace_id, payload_version, payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=?", (run_id, epoch, origin_event_id)).fetchone()
        if existing:
            if existing[2] != event_type or existing[6] != encoded or trace_id is not None and trace_id != existing[4]:
                raise ValueError("事件内容冲突")
            return self._event(run_id, existing)
        if row[4] in TERMINAL or row[5] is not None and event_type in {"TOOL_STARTED", "INPUT_APPLIED"}:
            raise ValueError("运行状态禁止事件")
        seq = row[3] + 1
        if trace_id is not None and (not isinstance(trace_id, str) or not trace_id):
            raise ValueError("事件关联标识无效")
        event = (str(uuid4()), seq, event_type, utc_now().isoformat(), trace_id or str(uuid4()), 1, encoded)
        db.execute("INSERT INTO agent_run_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (event[0], run_id, seq, origin_event_id, epoch, event_type, event[3], event[4], 1, encoded))
        db.execute("UPDATE agent_runs SET last_event_seq=?, revision=revision+1 WHERE run_id=?", (seq, run_id))
        return self._event(run_id, event)

    @staticmethod
    def _event(run_id, row):
        event = {"event_id": row[0], "run_id": run_id, "seq": row[1], "type": row[2], "occurred_at": row[3], "trace_id": row[4], "payload_version": row[5], "payload": json.loads(row[6])}
        EVENT_VALIDATOR.validate(event)
        return event

    def event_page_in_transaction(self, db, run_id, after_seq):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.path.resolve():
            raise ValueError("事件续读需要同一数据库事务")
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError("事件游标无效")
        run = db.execute("SELECT last_event_seq FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("运行不存在")
        rows = db.execute("SELECT event_id,seq,type,occurred_at,trace_id,payload_version,payload FROM agent_run_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 101", (run_id, after_seq)).fetchall()
        remaining = max(0, run[0] - after_seq)
        if len(rows) != min(101, remaining) or any(row[1] != after_seq + index + 1 for index, row in enumerate(rows)):
            raise ValueError("运行事件序号不可核查")
        events = [self._event(run_id, row) for row in rows[:100]]
        return {"events": events, "next_seq": events[-1]["seq"] if events else after_seq, "has_more": len(rows) > 100}

    def result_in_transaction(self, db, run_id, goal_revision):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.path.resolve() or type(goal_revision) is not int or goal_revision < 1:
            raise ValueError("运行结果读取事务无效")
        rows = db.execute("SELECT event_id,seq,type,occurred_at,trace_id,payload_version,payload FROM agent_run_events WHERE run_id=? AND type='RESULT_RECORDED' AND json_extract(payload,'$.goal_revision')=? ORDER BY seq", (run_id, goal_revision)).fetchall()
        if len(rows) > 1:
            raise ValueError("运行结果版本不可核查")
        return self._event(run_id, rows[0]) if rows else None

    def events(self, run_id, after_seq):
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError("事件游标无效")
        with self.connect() as db:
            rows = db.execute("SELECT event_id, seq, type, occurred_at, trace_id, payload_version, payload FROM agent_run_events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after_seq)).fetchall()
            return [self._event(run_id, row) for row in rows]
