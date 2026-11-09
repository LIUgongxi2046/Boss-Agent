from contextlib import contextmanager

from agent_run_store import RunStore


class RunLaunchTransaction:
    def __init__(self, store):
        if not isinstance(store, RunStore):
            raise ValueError("需要运行数据库")
        self.store = store

    @contextmanager
    def hold(self, run_id, owner, epoch):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store._require_lease(db, run_id, owner, epoch)
            self.store.require_active_lineage(db, run_id)
            current = db.execute("SELECT status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if current != ("RUNNING", None):
                raise ValueError("运行状态或取消检查未通过")
            yield db
