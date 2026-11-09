import sqlite3

import pytest

from agent_migration_inventory import AgentMigrationInventory
from agent_run_store import RunStore
from controls import ControlStore


def test_inventory_preserves_business_objects_and_rejects_changed_input(tmp_path):
    path = tmp_path / "business.sqlite"
    store = ControlStore(path)
    store.initialize("ui-check")
    with store.connect() as db:
        baseline = db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()
    RunStore(path)
    inventory = AgentMigrationInventory(store, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        first = inventory.record_in_transaction(db, "business-to-hermes-1")
        assert first["created"] is True
        assert sum(group["count"] for group in first["inventory"] if group["table"] == "objects") == len(baseline)
        assert any(group["table"] == "spaces" for group in first["inventory"])
        assert {group["kind"] for group in first["inventory"]}.issuperset({"document", "schedule", "initial"})
        assert inventory.record_in_transaction(db, "business-to-hermes-1")["created"] is False
    reopened = AgentMigrationInventory(ControlStore(path))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert reopened.record_in_transaction(db, "business-to-hermes-1")["input_digest"] == first["input_digest"]
        assert db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall() == baseline
        document = store.get(db, "ui-check", "document", "finance-note")
        document["withdrawn"] = True
        store.put(db, "ui-check", "document", "finance-note", document)
        with pytest.raises(ValueError, match="业务资料已经变化"):
            reopened.record_in_transaction(db, "business-to-hermes-1")
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert reopened.record_in_transaction(db, "business-to-hermes-1")["created"] is False
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_inventory_rolls_back_with_caller_transaction(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    inventory = AgentMigrationInventory(store, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        inventory.record_in_transaction(db, "interrupted")
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT count(*) FROM agent_migration_inventory").fetchone() == (0,)
        assert inventory.record_in_transaction(db, "interrupted")["created"] is True
    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM agent_migration_inventory")


def test_inventory_requires_installed_matching_schema(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with pytest.raises(ValueError, match="尚未完成迁移"):
        AgentMigrationInventory(store, allow_migration=True)
    RunStore(store.path)
    with pytest.raises(ValueError, match="尚未安装"):
        AgentMigrationInventory(store)
    AgentMigrationInventory(store, allow_migration=True)
    with store.connect() as db:
        db.execute("UPDATE agent_schema_migrations SET sha256=? WHERE version=?", ("invalid", "upgrade2_inventory_001"))
    with pytest.raises(ValueError, match="版本摘要不符"):
        AgentMigrationInventory(store)


def test_empty_business_database_has_empty_inventory(tmp_path):
    store = ControlStore(tmp_path / "empty.sqlite")
    RunStore(store.path)
    inventory = AgentMigrationInventory(store, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert inventory.record_in_transaction(db, "empty")["inventory"] == []
