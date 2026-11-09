import hashlib
from pathlib import Path

from filelock import FileLock

from agent_run_store import RunStore, utc_now


class RunToolBudget:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, RunStore):
            raise ValueError("需要运行存储")
        self.store = store
        script = (Path(__file__).parent / "migrations" / "upgrade2_tool_budget_001.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("upgrade2_tool_budget_001",)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("工具预算迁移摘要不符")
                return
            existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('agent_tool_budgets','agent_tool_reservations')").fetchone()
            if existing is not None or not allow_migration:
                raise ValueError("工具预算迁移尚未完成")
            db.executescript("BEGIN IMMEDIATE;\n" + script)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("upgrade2_tool_budget_001", digest))

    def configure(self, root_run_id, owner, epoch, max_tools):
        if type(max_tools) is not int or max_tools <= 0:
            raise ValueError("工具预算无效")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store._require_lease(db, root_run_id, owner, epoch)
            if self.store.require_active_lineage(db, root_run_id) != root_run_id:
                raise ValueError("工具预算仅可由根运行配置")
            row = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root_run_id,)).fetchone()
            if row is not None:
                if row[0] != max_tools:
                    raise ValueError("工具预算已经变化")
                return
            db.execute("INSERT INTO agent_tool_budgets VALUES (?,?)", (root_run_id, max_tools))

    def reserve_in_transaction(self, db, run_id, owner, epoch, request_key, request_digest, tool_name):
        if not db.in_transaction or any(not isinstance(item, str) or not item for item in (run_id, owner, request_key, request_digest, tool_name)):
            raise ValueError("工具预留参数无效")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("工具预留数据库不匹配")
        self.store._require_lease(db, run_id, owner, epoch)
        root = self.store.require_active_lineage(db, run_id)
        status = db.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if status is None or status[0] != "RUNNING":
            raise ValueError("当前运行状态不能调用工具")
        budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
        if budget is None:
            raise ValueError("根运行尚未配置工具预算")
        old = db.execute("SELECT root_run_id,request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if old is not None:
            if old != (root, request_digest, tool_name, epoch):
                raise ValueError("工具请求编号内容冲突")
            return False
        used = db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0]
        if used >= budget[0]:
            raise ValueError("工具预算不足")
        db.execute("INSERT INTO agent_tool_reservations VALUES (?,?,?,?,?,?,?)", (run_id, request_key, root, request_digest, tool_name, epoch, utc_now().isoformat()))
        return True
