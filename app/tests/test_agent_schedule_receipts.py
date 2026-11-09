import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from agent_schedule_receipts import list_suppressed_receipts_in_transaction, read_suppressed_receipt_in_transaction, recovery_decision_in_transaction, require_prior_notification_in_transaction
from business import checksum
from controls import ControlStore


PLAN_ID = "technical-suppressed-plan"
EVENT_ID = "technical-suppressed-event"


def suppressed_store(path):
    store = ControlStore(path)
    store.initialize("ui-check")
    store.control("ui-check", "rules", {"version": "1", "cooldown_seconds": 0, "quiet_start": 22, "quiet_end": 7,
                                        "timezone": "Asia/Shanghai", "important_escalation": True})
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        store.put(db, "ui-check", "owner_plan", PLAN_ID, {
            "plan_id": PLAN_ID, "version": "1", "owner_id": initial["owner_id"], "purpose": "技术复查",
            "source_type": "SIMULATED", "state": "PAUSED", "event_ids": [EVENT_ID],
            "event_versions": {EVENT_ID: "1"}, "timezone": "Asia/Shanghai",
        })
        store.put(db, "ui-check", "event", EVENT_ID, {
            "event_id": EVENT_ID, "version": "1", "owner_plan_id": PLAN_ID, "state": "OPEN",
            "due_at": "2026-10-31T08:00:00+08:00", "impact": "NORMAL",
        })
        clock = store.get(db, "ui-check", "clock", "current")
        clock["at"] = "2026-10-31T10:00:00+08:00"
        store.put(db, "ui-check", "clock", "current", clock)
    return store


def dispatch_suppressed(store):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        results = store.dispatch_due_in_transaction(db, "ui-check", only_event_id=EVENT_ID)
    matches = [result for result in results if result.get("event_id") == EVENT_ID and result.get("state") == "SUPPRESSED"]
    assert len(matches) == 1
    return matches[0]


def test_actual_dispatch_keeps_notification_and_duplicate_suppression(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    store.control("ui-check", "rules", {"version": "1", "cooldown_seconds": 0, "quiet_start": 22, "quiet_end": 7,
                                        "timezone": "Asia/Shanghai", "important_escalation": True})
    store.control("ui-check", "clock", {"at": "2026-10-25T10:00:00+08:00"})
    store.control("ui-check", "event", {"event_id": "technical-duplicate", "version": "1", "state": "OPEN", "impact": "NORMAL", "due_at": "2026-10-25T09:00:00+08:00"})
    first = store.dispatch_due("ui-check")
    second = store.dispatch_due("ui-check")
    delivered = next(item for item in first if item.get("event_id") == "technical-duplicate")
    suppressed = next(item for item in second if item.get("event_id") == "technical-duplicate")
    assert delivered["state"] == "DELIVERED"
    assert suppressed["state"] == "SUPPRESSED" and suppressed["reason"] == "DUPLICATE_EVENT"
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind='notification' AND id=?", ("technical-duplicate:" + delivered["event_version"],)).fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind='dispatch_history' AND id=?", (checksum(suppressed),)).fetchone() == (1,)
        saved = json.loads(db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='dispatch_history' AND id=?", (checksum(suppressed),)).fetchone()[0])
        db.execute("BEGIN")
        require_prior_notification_in_transaction(store, db, "technical-duplicate", delivered["event_version"], None, saved)
        with pytest.raises(ValueError, match="通知记录不可核查"):
            require_prior_notification_in_transaction(store, db, "technical-duplicate", delivered["event_version"], "other-plan", saved)
    repeated = store.dispatch_due("ui-check")
    assert next(item for item in repeated if item.get("event_id") == "technical-duplicate") == suppressed
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        db.execute("BEGIN")
        require_prior_notification_in_transaction(reopened, db, "technical-duplicate", delivered["event_version"], None, saved)
        require_prior_notification_in_transaction(reopened, db, "technical-duplicate", delivered["event_version"], None, saved)


def test_suppressed_receipt_repeats_after_reopen_and_repeated_dispatch(tmp_path):
    store = suppressed_store(tmp_path / "business.sqlite")
    first_dispatch = dispatch_suppressed(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        first = read_suppressed_receipt_in_transaction(store, db, PLAN_ID, EVENT_ID)
        assert first["status"] == "SUPPRESSED"
        assert first["reason"] == "OWNER_PLAN_PAUSED"
        assert first["dispatch_id"] == checksum(first_dispatch)
        assert first["occurrence_binding"] == "UNVERIFIED"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert read_suppressed_receipt_in_transaction(store, db, PLAN_ID, EVENT_ID) == first
    repeated = dispatch_suppressed(store)
    assert repeated == first_dispatch
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert read_suppressed_receipt_in_transaction(reopened, db, PLAN_ID, EVENT_ID) == first
        decision = recovery_decision_in_transaction(reopened, db, PLAN_ID, EVENT_ID)
        assert decision["recovery_state"] == "BLOCKED"
        assert decision["reason"] == "PLAN_INACTIVE"
        assert decision["redispatch_same_occurrence"] is False


def test_canceled_plan_suppresses_and_receipt_is_retrievable_by_dispatch(tmp_path):
    store = suppressed_store(tmp_path / "business.sqlite")
    dispatch_suppressed(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan = store.get(db, "ui-check", "owner_plan", PLAN_ID)
        plan["state"] = "CANCELED"
        store.put(db, "ui-check", "owner_plan", PLAN_ID, plan)
    withdrawal = dispatch_suppressed(store)
    assert withdrawal["reason"] == "OWNER_PLAN_CANCELED"
    dispatch_id = checksum(withdrawal)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        receipt = read_suppressed_receipt_in_transaction(store, db, PLAN_ID, EVENT_ID, dispatch_id=dispatch_id)
        assert receipt["reason"] == "OWNER_PLAN_CANCELED"
        decision = recovery_decision_in_transaction(store, db, PLAN_ID, EVENT_ID, dispatch_id=dispatch_id)
        assert decision["recovery_state"] == "BLOCKED" and decision["reason"] == "PLAN_INACTIVE"
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert read_suppressed_receipt_in_transaction(reopened, db, PLAN_ID, EVENT_ID, dispatch_id=dispatch_id)["reason"] == "OWNER_PLAN_CANCELED"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="不可唯一核查"):
            read_suppressed_receipt_in_transaction(store, db, PLAN_ID, EVENT_ID)


def test_active_plan_requires_new_occurrence_not_same_receipt_reuse(tmp_path):
    store = suppressed_store(tmp_path / "business.sqlite")
    dispatch_suppressed(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan = store.get(db, "ui-check", "owner_plan", PLAN_ID)
        plan["state"] = "ACTIVE"
        store.put(db, "ui-check", "owner_plan", PLAN_ID, plan)
        decision = recovery_decision_in_transaction(store, db, PLAN_ID, EVENT_ID)
        assert decision["recovery_state"] == "READY_FOR_NEW_OCCURRENCE"
        assert decision["required_action"] == "NEW_OCCURRENCE"
        assert decision["redispatch_same_occurrence"] is False


def test_history_lists_actual_suppressed_dispatches_without_inventing_links(tmp_path):
    store = suppressed_store(tmp_path / "business.sqlite")
    first = dispatch_suppressed(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan = store.get(db, "ui-check", "owner_plan", PLAN_ID)
        plan["state"] = "CANCELED"
        store.put(db, "ui-check", "owner_plan", PLAN_ID, plan)
    second = dispatch_suppressed(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        history = list_suppressed_receipts_in_transaction(store, db, PLAN_ID, EVENT_ID)
        schema = json.loads((Path(__file__).resolve().parents[2] / "validation/agent_schedule_history_schema.json").read_text())
        Draft202012Validator(schema).validate(history)
        assert {item["dispatch_id"] for item in history["receipts"]} == {checksum(first), checksum(second)}
        assert all(item["occurrence_binding"] == "UNVERIFIED" and item["occurrence_id"] is None and item["run_id"] is None for item in history["receipts"])


def test_canceled_event_version_prevents_recovery_decision(tmp_path):
    store = suppressed_store(tmp_path / "business.sqlite")
    dispatch_suppressed(store)
    store.control("ui-check", "event", {"event_id": EVENT_ID, "version": "2", "state": "CANCELED", "impact": "NORMAL", "due_at": "2026-10-31T08:00:00+08:00"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="事件已经变化"):
            recovery_decision_in_transaction(store, db, PLAN_ID, EVENT_ID)
