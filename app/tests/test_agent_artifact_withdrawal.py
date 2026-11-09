import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from agent_artifact_withdrawal import propagate_domain_source_withdrawal_in_transaction
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_run_store import RunStore
from boss_command_api import BossCommandAPI
from boss_supply_quality import IMPORT_ACTION, WITHDRAW_ACTION, SupplyQualityAPI
from controls import ControlStore
from test_agent_artifacts import series_prepared
from test_agent_run_result import setup_result


SOURCE = "simulation-meeting-material"


def test_control_entry_commits_series_revocation(series_prepared):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, [SOURCE], request_key="withdraw-v1", format_name="MARKDOWN")
    second = service.create_meeting_brief(run_id, ["simulation-business-directory"], request_key="withdraw-v2", format_name="MARKDOWN",
                                         previous_artifact_id=first["artifact_id"], expected_version=1)
    third = service.create_meeting_brief(run_id, ["simulation-business-directory"], request_key="withdraw-v3", format_name="MARKDOWN",
                                        previous_artifact_id=second["artifact_id"], expected_version=2)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", SOURCE)
    first_receipt = store.control("ui-check", "withdraw", {"source_id": SOURCE, "version": document["version"]})
    second_receipt = store.control("ui-check", "withdraw", {"source_id": SOURCE, "version": document["version"]})
    assert first_receipt["withdrawn"] is True and second_receipt == first_receipt
    with store.connect() as db:
        rows = dict(db.execute("SELECT artifact_id,status FROM agent_artifacts").fetchall())
        assert rows == {first["artifact_id"]: "REVOKED", second["artifact_id"]: "REVOKED", third["artifact_id"]: "REVOKED"}
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (3,)
        assert db.execute("SELECT count(*) FROM objects WHERE kind='source_withdrawal_event'").fetchone() == (1,)


def test_control_retry_after_brief_cleanup_migration(series_prepared):
    from agent_simulation_migration_install import install_simulation_migrations
    store, service, run_id = series_prepared
    artifact = service.create_meeting_brief(run_id, [SOURCE], request_key="cleanup-migration-original", format_name="MARKDOWN")
    original = store.control("ui-check", "withdraw", {"source_id": SOURCE, "version": "1"})
    with store.connect() as db:
        event = db.execute("SELECT id,body FROM objects WHERE kind='source_withdrawal_event'").fetchone()
    installed = install_simulation_migrations(store.path)
    assert "upgrade2_artifact_brief_cleanup_001" in installed["installed"]
    assert store.control("ui-check", "withdraw", {"source_id": SOURCE, "version": "1"}) == original
    with store.connect() as db:
        assert db.execute("SELECT id,body FROM objects WHERE kind='source_withdrawal_event'").fetchall() == [event]
        assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (artifact["artifact_id"],)).fetchone() == ("REVOKED",)
        assert db.execute("SELECT count(*) FROM agent_artifact_brief_cleanup").fetchone() == (0,)


def test_domain_withdrawal_without_event_is_rejected(series_prepared):
    store, service, run_id = series_prepared
    service.create_meeting_brief(run_id, [SOURCE], request_key="withdraw-no-event", format_name="MARKDOWN")
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", SOURCE)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": SOURCE, "version": document["version"]})
        with pytest.raises(ValueError, match="撤销事件不唯一"):
            propagate_domain_source_withdrawal_in_transaction(store, db, SOURCE)
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (0,)


def test_source_without_withdrawal_is_rejected(series_prepared):
    store, service, run_id = series_prepared
    service.create_meeting_brief(run_id, [SOURCE], request_key="withdraw-missing", format_name="MARKDOWN")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="尚未撤销"):
            propagate_domain_source_withdrawal_in_transaction(store, db, SOURCE)
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (0,)


def test_changed_withdrawal_event_blocks_propagation(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
    assert store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": document["version"]})["withdrawn"] is True
    with store.connect() as db:
        event_id, body = db.execute("SELECT id,body FROM objects WHERE namespace='ui-check' AND kind='source_withdrawal_event'").fetchone()
        event = json.loads(body)
    event["withdrawn_version"] = "999"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.put(db, "ui-check", "source_withdrawal_event", event_id, event)
        with pytest.raises(ValueError, match="撤销事件不可核查"):
            propagate_domain_source_withdrawal_in_transaction(store, db, "finance-note")
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (0,)


def test_control_entry_clears_pending_artifact_withdrawal(series_prepared):
    store, service, run_id = series_prepared
    service.create_meeting_brief(run_id, [SOURCE], request_key="pending-v1", format_name="MARKDOWN")
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", SOURCE)
    assert store.control("ui-check", "withdraw", {"source_id": SOURCE, "version": document["version"]})["withdrawn"] is True
    preflight = AgentRecoveryPreflight(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        state = preflight.current_state_in_transaction(db)
        assert state["artifact_withdrawal_pending_count"] == 0
        assert "ARTIFACT_WITHDRAWAL_PENDING" not in state["pending"]
        assert state["restore_state"] == "BLOCKED"


def test_preflight_reports_source_deleted_from_binding(series_prepared):
    store, _, _ = series_prepared
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM objects WHERE namespace='ui-check' AND kind='document' AND id='simulation-business-directory'")
        state = AgentRecoveryPreflight(store).current_state_in_transaction(db)
        assert "SOURCE_DELETED" in state["pending"]
        assert state["restore_state"] == "BLOCKED"
        db.rollback()


def test_preflight_reports_deleted_source_from_result_citation(tmp_path):
    store, _, results, sink = setup_result(tmp_path)
    results.record(sink, "answer-citation", 1, "技术结果", [{"source_id": "finance-note", "locator": "第一节"}])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM objects WHERE namespace='ui-check' AND kind='document' AND id='finance-note'")
        state = AgentRecoveryPreflight(store).current_state_in_transaction(db)
        assert "SOURCE_DELETED" in state["pending"]
        assert state["restore_state"] == "BLOCKED"
        db.rollback()


def test_old_database_without_artifact_tables_returns_not_installed(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
    assert store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": document["version"]})["withdrawn"] is True
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = propagate_domain_source_withdrawal_in_transaction(store, db, "finance-note")
        assert result["artifact_state"] == "NOT_INSTALLED"
        assert result["affected"] == []
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='agent_artifacts'").fetchone() == (0,)


def test_knowledge_and_supply_events_are_accepted_by_artifact_adapter(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    commands = BossCommandAPI(store)
    created = {"client_request_id": "adapter-knowledge-create", "source_id": "sim-doc-adapter-check", "title": "模拟资料",
               "author_contact_id": "finance-1", "published_at": "2026-10-22",
               "content": "这是用于核查来源撤销事件接入的模拟资料正文，包含足够长度的说明内容。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.create", created)[0] == 200
    withdrawal = {"client_request_id": "adapter-knowledge-withdraw", "source_id": created["source_id"], "expected_version": "1"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)[0] == 200
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        knowledge = propagate_domain_source_withdrawal_in_transaction(store, db, created["source_id"])
        assert knowledge["artifact_state"] == "PROPAGATED" and knowledge["affected"] == []
    supply = SupplyQualityAPI(store)
    data = yaml.safe_load((Path(__file__).resolve().parents[2] / "data/simulation/supply-quality-v1.yaml").read_text())
    assert supply.execute("MAINTAINER", IMPORT_ACTION, data["initial_request"])["state"] == "SUCCESS"
    supply_withdrawal = {"client_request_id": "adapter-supply-withdraw", "entity_type": "inventory_lot",
                         "record_id": "sim-stock-available-1", "expected_version": "1", "reason": "模拟来源撤销"}
    withdrawn = supply.execute("MAINTAINER", WITHDRAW_ACTION, supply_withdrawal)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        supply_result = propagate_domain_source_withdrawal_in_transaction(store, db, withdrawn["source_id"])
        assert supply_result["artifact_state"] == "PROPAGATED" and supply_result["affected"] == []


def test_other_artifact_table_without_base_schema_is_rejected(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
    assert store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": document["version"]})["withdrawn"] is True
    with store.connect() as db:
        db.execute("CREATE TABLE agent_artifact_versions (artifact_id TEXT)")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="成果升级表状态不可核查"):
            propagate_domain_source_withdrawal_in_transaction(store, db, "finance-note")


def test_extra_artifact_table_without_its_migration_is_rejected(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
    assert store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": document["version"]})["withdrawn"] is True
    with store.connect() as db:
        db.execute("CREATE TABLE agent_artifact_goals (artifact_id TEXT)")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="成果升级表状态不可核查"):
            propagate_domain_source_withdrawal_in_transaction(store, db, "finance-note")


def test_partial_artifact_schema_is_rejected(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
    assert store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": document["version"]})["withdrawn"] is True
    with store.connect() as db:
        db.execute("DELETE FROM agent_schema_migrations WHERE version='upgrade2_001'")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="成果升级表状态不可核查"):
            propagate_domain_source_withdrawal_in_transaction(store, db, "finance-note")


def test_withdrawal_propagation_requires_same_database_transaction(series_prepared, tmp_path):
    store, service, run_id = series_prepared
    service.create_meeting_brief(run_id, [SOURCE], request_key="withdraw-database", format_name="MARKDOWN")
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="同一业务数据库事务"):
            propagate_domain_source_withdrawal_in_transaction(store, db, SOURCE)
