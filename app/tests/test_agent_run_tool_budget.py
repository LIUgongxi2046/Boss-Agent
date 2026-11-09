from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget


def test_parent_child_share_durable_tool_budget(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunToolBudget(store, allow_migration=True)
    RunToolBudget(store, allow_migration=True)
    root = store.create_run("boss-1", "ui-check", "root-request", "root-digest")
    root_lease = store.acquire_lease(root, 0, "root-worker", 60)
    store.transition(root, root_lease["revision"], "RUNNING", "root-worker", root_lease["epoch"])
    budget.configure(root, "root-worker", root_lease["epoch"], 1)
    child = store.create_child_run(root, "root-worker", root_lease["epoch"], "child-request", "child-digest")
    child_lease = store.acquire_lease(child, 0, "child-worker", 60)
    store.transition(child, child_lease["revision"], "RUNNING", "child-worker", child_lease["epoch"])

    def reserve(run_id, owner, epoch):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return budget.reserve_in_transaction(db, run_id, owner, epoch, "tool-request", "tool-digest", "read_source")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, *args) for args in [(root, "root-worker", root_lease["epoch"]), (child, "child-worker", child_lease["epoch"])]]
    errors = [future.exception() for future in futures]
    assert sum(error is None for error in errors) == 1
    assert [str(error) for error in errors if error is not None] == ["工具预算不足"]
    with store.connect() as db:
        row = db.execute("SELECT run_id FROM agent_tool_reservations").fetchone()
    winner = (root, "root-worker", root_lease["epoch"]) if row[0] == root else (child, "child-worker", child_lease["epoch"])
    assert reserve(*winner) is False
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_tool_reservations").fetchone()[0] == 1
        with pytest.raises(ValueError, match="租约"):
            db.execute("BEGIN IMMEDIATE")
            budget.reserve_in_transaction(db, winner[0], winner[1], winner[2] + 1, "other-request", "digest", "read_source")
