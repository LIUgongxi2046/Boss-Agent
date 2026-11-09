import multiprocessing
import hashlib
import os
from pathlib import Path
import signal
import sqlite3

import pytest

from agent_artifact_goal import AgentArtifactGoal
from agent_legacy_run_link import AgentLegacyRunLink
from agent_plan_handover import AgentPlanHandover
from agent_run_method_selection import AgentRunMethodSelection
from agent_run_object_scope import AgentRunObjectScope
from agent_migration_inventory import AgentMigrationInventory
from agent_run_broker import RunBroker
from agent_run_business_receipts import RunBusinessReceipts
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_requirements import RunRequirements
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from agent_simulation_migration_install import MIGRATIONS, _catalog, _prepare, install_simulation_migrations
from controls import ControlStore
from hermes_process_evidence import HermesProcessEvidence
from hermes_vm_identity import HermesVMRunBindings
from hermes_schedule_adapter import HermesScheduleAdapter
from test_agent_legacy_inventory import setup_inventory


def terminate_during_install(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    script, _ = _prepare(db)

    def terminate(statement):
        if statement.lstrip().startswith("CREATE TABLE agent_tool_budgets"):
            os.kill(os.getpid(), signal.SIGKILL)

    db.set_trace_callback(terminate)
    db.executescript(script)


def test_install_all_migrations_preserves_existing_records(tmp_path):
    store, sessions, scope, inventory = setup_inventory(tmp_path)
    sessions.save(sessions.get_or_create("websocket:migration-check"), fsync=True)
    session_before = sessions.read_session_snapshot("websocket:migration-check").messages
    links = AgentLegacyRunLink(inventory, RunBroker(RunStore(store.path, allow_migration=False), scope_service=scope), allow_migration=True)
    handover = AgentPlanHandover(store, allow_migration=True)
    run_id = links.broker.store.create_run("technical-owner", "ui-check", "technical-request", "technical-digest")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        initial = store.get(db, "ui-check", "initial", "snapshot")
        event = {"event_id": "technical-event", "version": "1", "owner_plan_id": "technical-plan", "state": "PENDING"}
        plan = {"plan_id": "technical-plan", "version": "1", "owner_id": initial["owner_id"], "source_type": "SIMULATED", "state": "PAUSED", "event_ids": ["technical-event"], "event_versions": {"technical-event": "1"}}
        store.put(db, "ui-check", "event", "technical-event", event)
        store.put(db, "ui-check", "owner_plan", "technical-plan", plan)
        item = inventory.session_in_transaction(db, "migration-check", [])
        db.execute("INSERT INTO agent_legacy_run_links VALUES (?,?,?,?,?,?)", (run_id, "ui-check", "SESSION", item["metadata"]["scope"]["session_id"], item["source_digest"], "2026-10-30T00:00:00+00:00"))
        handover.capture_in_transaction(db, "technical-handover")
    with store.connect() as db:
        before = {table: db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall() for table in ("objects", "spaces", "idempotency", "audit", "agent_runs", "agent_legacy_inventory", "agent_legacy_run_links", "agent_plan_handovers")}
    result = install_simulation_migrations(store.path)
    assert len(result["versions"]) == len(MIGRATIONS)
    assert result["installed"]
    assert install_simulation_migrations(store.path)["installed"] == []
    runs = RunStore(store.path, allow_migration=False)
    RunConcurrencyBudget(runs)
    RunToolBudget(runs)
    HermesProcessEvidence(runs)
    HermesVMRunBindings(runs)
    AgentMigrationInventory(store)
    HermesScheduleAdapter(store).install_schema()
    with store.connect() as db:
        db.execute("BEGIN")
        for table, rows in before.items():
            assert db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall() == rows
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert RunRequirements.read_in_transaction(db, run_id, 1) == {"goal_revision": 1, "state": "PENDING_CONFIRMATION", "required_outputs": None}
        assert db.execute("SELECT count(*) FROM agent_schema_migrations").fetchone() == (sum(ledger == "agent_schema_migrations" for _, ledger in MIGRATIONS),)
        assert db.execute("SELECT count(*) FROM hermes_schedule_migrations").fetchone() == (3,)
        assert db.execute("SELECT count(*) FROM hermes_usage_revisions").fetchone() == (0,)
        assert AgentArtifactGoal.schema_state(db) and AgentRunMethodSelection.schema_state(db)
        assert AgentRunMethodSelection.reselection_schema_state(db) and AgentRunObjectScope.schema_state(db)
        assert db.execute("SELECT count(*) FROM agent_artifact_briefs").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_run_method_selections").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_run_method_reselections").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_run_object_scopes").fetchone() == (0,)
    assert sessions.read_session_snapshot("websocket:migration-check").messages == session_before


def test_brief_cleanup_migration_checks_exact_trigger(tmp_path):
    store, _, _, _ = setup_inventory(tmp_path)
    original = (Path(__file__).resolve().parents[2] / "validation/migrations/upgrade2_artifact_brief_001.sql").read_bytes()
    result = install_simulation_migrations(store.path)
    assert "upgrade2_artifact_brief_cleanup_001" in result["installed"]
    with store.connect() as db:
        assert db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_artifact_brief_001'").fetchone() == (hashlib.sha256(original).hexdigest(),)
        assert db.execute("SELECT count(*) FROM agent_artifact_brief_cleanup").fetchone() == (0,)
        assert "artifact brief cleanup requires withdrawal" in db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='agent_artifact_briefs_no_delete'").fetchone()[0]
        db.execute("DROP TRIGGER agent_artifact_briefs_no_delete")
        db.execute("CREATE TRIGGER agent_artifact_briefs_no_delete BEFORE DELETE ON agent_artifact_briefs BEGIN SELECT 1; END")
    with pytest.raises(ValueError, match="迁移对象不可核查"):
        install_simulation_migrations(store.path)


def test_workspace_ownership_migration_upgrades_existing_database(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("technical-owner", "ui-check", "workspace-request", "workspace-digest")
    catalog = _catalog()
    with store.connect() as db:
        installed = {row[0] for row in db.execute("SELECT version FROM agent_schema_migrations")}
        script = ["BEGIN IMMEDIATE;"]
        for version, ledger, source, digest, _ in catalog:
            if version == "upgrade2_artifact_workspace_001" or version in installed:
                continue
            script.extend((source, f"INSERT INTO {ledger} VALUES ('{version}', '{digest}');"))
        script.append("COMMIT;")
        db.executescript("\n".join(script))
        before = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    assert install_simulation_migrations(store.path)["installed"] == ["upgrade2_artifact_workspace_001"]
    assert install_simulation_migrations(store.path)["installed"] == []
    with store.connect() as db:
        assert db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == before
        assert db.execute("SELECT count(*) FROM agent_artifact_workspaces").fetchone() == (0,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_workspace_ownership_migration_rejects_changed_digest(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    install_simulation_migrations(store.path)
    with store.connect() as db:
        db.execute("UPDATE agent_schema_migrations SET sha256='invalid' WHERE version='upgrade2_artifact_workspace_001'")
    with pytest.raises(ValueError, match="摘要不符"):
        install_simulation_migrations(store.path)


def test_install_rejects_conflict_and_unregistered_objects(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    with store.connect() as db:
        db.execute("UPDATE agent_schema_migrations SET sha256='invalid' WHERE version='upgrade2_001'")
    with pytest.raises(ValueError, match="摘要不符"):
        install_simulation_migrations(store.path)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_schema_migrations").fetchone() == (1,)


def test_install_rejects_unregistered_object(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        db.execute("CREATE TABLE agent_tool_budgets (root_run_id TEXT)")
    with pytest.raises(ValueError, match="缺少版本登记"):
        install_simulation_migrations(store.path)
    with store.connect() as db:
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='agent_tool_budgets'").fetchone() is not None
        assert db.execute("SELECT name FROM sqlite_master WHERE name='agent_schema_migrations'").fetchone() is None


def test_install_recovers_after_process_termination(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        before = db.execute("SELECT * FROM objects ORDER BY namespace,kind,id").fetchall()
    process = multiprocessing.get_context("spawn").Process(target=terminate_during_install, args=(store.path,))
    process.start()
    process.join(timeout=30)
    assert process.exitcode == -signal.SIGKILL
    with store.connect() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='agent_schema_migrations'").fetchone() is None
        assert db.execute("SELECT * FROM objects ORDER BY namespace,kind,id").fetchall() == before
    assert len(install_simulation_migrations(store.path)["installed"]) == len(MIGRATIONS)
    assert install_simulation_migrations(store.path)["installed"] == []


def test_install_rejects_outside_simulation_root():
    with pytest.raises(ValueError, match="独立模拟"):
        install_simulation_migrations("business.sqlite")


def test_existing_full_install_upgrades_requirements_without_changing_runs(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("technical-owner", "ui-check", "technical-request", "technical-digest")
    with store.connect() as db:
        script = ["BEGIN IMMEDIATE;"]
        for version, ledger, source, digest, _ in _catalog():
            if version in {"upgrade2_001", "upgrade2_run_requirements_001", "upgrade2_business_receipts_001"}:
                continue
            script.extend((source, f"INSERT INTO {ledger} VALUES ('{version}', '{digest}');"))
        script.append("COMMIT;")
        db.executescript("\n".join(script))
        db.execute("BEGIN")
        assert RunRequirements.read_in_transaction(db, run_id, 1)["state"] == "UNAVAILABLE"
        before = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        business = db.execute("SELECT * FROM objects ORDER BY namespace,kind,id").fetchall()
    assert install_simulation_migrations(store.path)["installed"] == ["upgrade2_run_requirements_001", "upgrade2_business_receipts_001"]
    assert install_simulation_migrations(store.path)["installed"] == []
    RunRequirements(RunStore(store.path, allow_migration=False))
    with store.connect() as db:
        db.execute("BEGIN")
        assert RunRequirements.read_in_transaction(db, run_id, 1) == {"goal_revision": 1, "state": "PENDING_CONFIRMATION", "required_outputs": None}
        assert db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == before
        assert db.execute("SELECT * FROM objects ORDER BY namespace,kind,id").fetchall() == business
        assert db.execute("SELECT count(*) FROM agent_run_requirements").fetchone() == (0,)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, run_id, 1, "technical-selection", ["TEXT", "PDF"])
    assert install_simulation_migrations(store.path)["installed"] == []
    with store.connect() as db:
        db.execute("BEGIN")
        assert RunRequirements.read_in_transaction(db, run_id, 1)["required_outputs"] == ["TEXT", "PDF"]


def test_install_rejects_requirements_digest_conflict(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    RunRequirements(runs, allow_migration=True)
    with store.connect() as db:
        db.execute("UPDATE agent_schema_migrations SET sha256='invalid' WHERE version='upgrade2_run_requirements_001'")
    with pytest.raises(ValueError, match="摘要不符"):
        install_simulation_migrations(store.path)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_schema_migrations").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM agent_run_requirements").fetchone() == (0,)


def terminate_during_requirements_install(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    script, _ = _prepare(db)

    def terminate(statement):
        if statement.lstrip().startswith("CREATE TABLE agent_run_requirements"):
            os.kill(os.getpid(), signal.SIGKILL)

    db.set_trace_callback(terminate)
    db.executescript(script)


def test_requirements_migration_interruption_and_retry(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("technical-owner", "ui-check", "technical-request", "technical-digest")
    before = runs.read_run(run_id)
    process = multiprocessing.get_context("spawn").Process(target=terminate_during_requirements_install, args=(store.path,))
    process.start()
    process.join(timeout=30)
    assert process.exitcode == -signal.SIGKILL
    with store.connect() as db:
        db.execute("BEGIN")
        assert RunRequirements.read_in_transaction(db, run_id, 1)["state"] == "UNAVAILABLE"
        assert db.execute("SELECT count(*) FROM agent_schema_migrations").fetchone() == (1,)
    assert runs.read_run(run_id) == before
    installed = install_simulation_migrations(store.path)
    assert len(installed["versions"]) == len(MIGRATIONS)
    assert "upgrade2_run_requirements_001" in installed["installed"]
    with store.connect() as db:
        db.execute("BEGIN")
        assert RunRequirements.read_in_transaction(db, run_id, 1)["state"] == "PENDING_CONFIRMATION"


def terminate_during_business_receipts_install(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    script, _ = _prepare(db)

    def terminate(statement):
        if statement.lstrip().startswith("CREATE TABLE agent_run_business_receipts"):
            os.kill(os.getpid(), signal.SIGKILL)

    db.set_trace_callback(terminate)
    db.executescript(script)


def test_business_receipts_migration_upgrades_existing_run_and_recovers(tmp_path):
    store, _, scope, _ = setup_inventory(tmp_path)
    runs = RunStore(store.path, allow_migration=False)
    run_id = runs.create_run("technical-owner", "ui-check", "technical-request", "technical-digest")
    lease = runs.acquire_queued_for_execution(run_id, 0, "technical-worker", 60)
    with store.connect() as db:
        script = ["BEGIN IMMEDIATE;"]
        installed = {row[0] for row in db.execute("SELECT version FROM agent_schema_migrations")}
        for version, ledger, source, digest, _ in _catalog():
            if version == "upgrade2_business_receipts_001" or version in installed:
                continue
            script.extend((source, f"INSERT INTO {ledger} VALUES ('{version}', '{digest}');"))
        script.append("COMMIT;")
        db.executescript("\n".join(script))
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, run_id, 1, "technical-selection", ["BUSINESS_RECEIPT"])
    with store.connect() as db:
        before = {table: db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall() for table in ("objects", "agent_runs", "agent_run_events", "agent_run_requirements", "agent_intents", "agent_intent_decisions")}
        assert db.execute("SELECT count(*) FROM agent_schema_migrations").fetchone() == (sum(ledger == "agent_schema_migrations" for _, ledger in MIGRATIONS) - 1,)
    process = multiprocessing.get_context("spawn").Process(target=terminate_during_business_receipts_install, args=(store.path,))
    process.start()
    process.join(timeout=30)
    assert process.exitcode == -signal.SIGKILL
    with store.connect() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='agent_run_business_receipts'").fetchone() is None
        assert db.execute("SELECT count(*) FROM agent_schema_migrations").fetchone() == (sum(ledger == "agent_schema_migrations" for _, ledger in MIGRATIONS) - 1,)
        for table, rows in before.items():
            assert db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall() == rows
    result = install_simulation_migrations(store.path)
    assert result["installed"] == ["upgrade2_business_receipts_001"]
    assert len(result["versions"]) == len(MIGRATIONS)
    assert install_simulation_migrations(store.path)["installed"] == []
    service = RunBusinessReceipts(runs, scope)
    with store.connect() as db:
        db.execute("BEGIN")
        for table, rows in before.items():
            assert db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall() == rows
        expected = hashlib.sha256((Path(__file__).resolve().parents[2] / "validation/migrations/upgrade2_business_receipts_001.sql").read_bytes()).hexdigest()
        assert db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_business_receipts_001'").fetchone() == (expected,)
        assert db.execute("SELECT count(*) FROM agent_run_business_receipts").fetchone() == (0,)
        assert service.inspect_in_transaction(db, run_id, 1) == {"state": "NOT_VERIFIED", "count": 0}
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert runs.read_run(run_id)["lease_epoch"] == lease["epoch"]


@pytest.mark.parametrize("missing", ["upgrade2_intents_001", "upgrade2_run_requirements_001"])
def test_business_receipts_migration_rejects_digest_and_missing_dependency(tmp_path, missing):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    install_simulation_migrations(store.path)
    with store.connect() as db:
        original = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_business_receipts_001'").fetchone()[0]
        db.execute("UPDATE agent_schema_migrations SET sha256='invalid' WHERE version='upgrade2_business_receipts_001'")
    with pytest.raises(ValueError, match="摘要不符"):
        install_simulation_migrations(store.path)
    with store.connect() as db:
        db.execute("UPDATE agent_schema_migrations SET sha256=? WHERE version='upgrade2_business_receipts_001'", (original,))
        if missing == "upgrade2_intents_001":
            db.execute("DROP TABLE agent_intent_decisions")
            db.execute("DROP TABLE agent_intents")
        else:
            db.execute("DROP TABLE agent_run_requirements")
        db.execute("DELETE FROM agent_schema_migrations WHERE version=?", (missing,))
    with pytest.raises(ValueError, match="缺少依赖"):
        install_simulation_migrations(store.path)
