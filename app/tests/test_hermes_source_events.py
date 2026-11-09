import json
from pathlib import Path

import pytest
import yaml

from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_run_store import RunStore
from boss_command_api import BossCommandAPI
from boss_supply_quality import IMPORT_ACTION, WITHDRAW_ACTION, SupplyQualityAPI
from controls import ControlStore
from hermes_source_invalidation import verify_source_withdrawals_in_transaction


def test_withdrawal_events_and_recovery_checkpoint(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        original = store.get(db, "ui-check", "document", "finance-note")
        before = checkpoint.capture_in_transaction(db, "before")

    source = {"source_id": "finance-note", "version": "1"}
    store.control("ui-check", "withdraw", source)
    with store.connect() as db:
        withdrawn_at = store.get(db, "ui-check", "document", "finance-note")["withdrawn_at"]
    store.control("ui-check", "withdraw", source)

    commands = BossCommandAPI(store)
    payload = {"client_request_id": "knowledge-create", "source_id": "sim-doc-event-check", "title": "模拟财务资料",
               "author_contact_id": original["author_contact_id"], "published_at": original["published_at"][:10], "content": original["content"]}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.create", payload)[0] == 200
    withdrawal = {"client_request_id": "knowledge-withdraw", "source_id": payload["source_id"], "expected_version": "1"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)[0] == 200
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)[0] == 200

    supply = SupplyQualityAPI(store)
    source_file = Path(__file__).resolve().parents[2] / "data/simulation/supply-quality-v1.yaml"
    data = yaml.safe_load(source_file.read_text())
    assert supply.execute("MAINTAINER", IMPORT_ACTION, data["initial_request"])["state"] == "SUCCESS"
    supply_withdrawal = {"client_request_id": "supply-withdraw", "entity_type": "inventory_lot", "record_id": "sim-stock-available-1", "expected_version": "1", "reason": "模拟来源撤销"}
    first = supply.execute("MAINTAINER", WITHDRAW_ACTION, supply_withdrawal)
    assert supply.execute("MAINTAINER", WITHDRAW_ACTION, supply_withdrawal) == first

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert store.get(db, "ui-check", "document", "finance-note")["withdrawn_at"] == withdrawn_at
        events = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", ("ui-check",))]
        assert sorted(event["sequence"] for event in events) == [1, 2, 3]
        assert verify_source_withdrawals_in_transaction(store, db, "ui-check") == {"event_count": 3, "missing_source_ids": [], "history_complete": False}
        with pytest.raises(ValueError, match="当前状态已经变化"):
            checkpoint.verify_in_transaction(db, "before", before["checkpoint_id"])
        state = preflight.current_state_in_transaction(db)
        assert "SOURCE_WITHDRAWAL_HISTORY_UNVERIFIED" in state["pending"]
        assert "SOURCE_WITHDRAWAL_HISTORY_MISSING" not in state["pending"]
        assert state["source_event_count"] == 3
        assert state["source_missing_count"] == 0
        assert state["source_history_complete"] is False
        assert state["restore_state"] == "BLOCKED"
        after = checkpoint.capture_in_transaction(db, "after")
        assert checkpoint.verify_in_transaction(db, "after", after["checkpoint_id"])["restore_state"] == "BLOCKED"


def test_missing_event_history_is_marked_and_invalid_sequence_is_rejected(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        state = AgentRecoveryPreflight(store).current_state_in_transaction(db)
        assert "SOURCE_WITHDRAWAL_HISTORY_MISSING" in state["pending"]
        assert "SOURCE_WITHDRAWAL_HISTORY_UNVERIFIED" not in state["pending"]
        assert state["source_event_count"] == 0
        assert state["source_missing_count"] == 1
        assert state["source_history_complete"] is False
        assert state["restore_state"] == "BLOCKED"
        result = verify_source_withdrawals_in_transaction(store, db, "ui-check")
        assert result == {"event_count": 0, "missing_source_ids": ["finance-note"], "history_complete": False}
    store.control("ui-check", "withdraw", {"source_id": "meeting-minutes", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        identifier, body = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", ("ui-check",)).fetchone()
        event = json.loads(body)
        event["sequence"] = 2
        store.put(db, "ui-check", "source_withdrawal_event", identifier, event)
        with pytest.raises(ValueError, match="序号不连续"):
            verify_source_withdrawals_in_transaction(store, db, "ui-check")


def test_deleted_source_is_reported_as_missing_event_history(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    assert store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})["withdrawn"] is True
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='document' AND id=?", ("ui-check", "finance-note"))
        assert verify_source_withdrawals_in_transaction(store, db, "ui-check") == {"event_count": 1, "missing_source_ids": ["finance-note"], "history_complete": False}
        db.rollback()
    with store.connect() as db:
        assert store.get(db, "ui-check", "document", "finance-note")["withdrawn"] is True
