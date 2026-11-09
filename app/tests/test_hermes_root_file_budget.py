import pytest

from hermes_product import require_root_file_budget_in_transaction
from test_agent_run_concurrency import running_family


def test_root_and_child_share_the_configured_file_budget(tmp_path):
    store, _, root, lease, child, _ = running_family(tmp_path)
    store.configure_file_budget(root, "root-worker", lease["epoch"], 5, 1024)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert require_root_file_budget_in_transaction(store, db, root, {"files": 5, "file_bytes": 1024}) == root
        assert require_root_file_budget_in_transaction(store, db, child, {"files": 4, "file_bytes": 512}) == root
        with pytest.raises(ValueError, match="根运行不一致"):
            require_root_file_budget_in_transaction(store, db, child, {"files": 6, "file_bytes": 512})
        with pytest.raises(ValueError, match="根运行不一致"):
            require_root_file_budget_in_transaction(store, db, child, {"files": 4, "file_bytes": 1025})
