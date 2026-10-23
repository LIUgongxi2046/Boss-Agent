import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from business import initial_materials
from boss_command_api import BossCommandAPI, _data_envelope
from controls import ControlStore
from test_boss_command_api import create_input, feedback_input, send_input


def test_fts_search_audit_keeps_source_references_without_query_or_body(tmp_path):
    store = ControlStore(tmp_path / "search-audit.sqlite")
    store.initialize("ui-check")
    document = initial_materials()["documents"][0]
    query = '"' + document["content"] + '"'
    result = store.control("ui-check", "search", {"query": query})
    assert result["results"][0]["content"] == document["content"]
    with store.connect() as db:
        audit_input, audit_output = db.execute("SELECT input,output FROM audit WHERE operation='search'").fetchone()
    assert document["content"] not in audit_input + audit_output
    metadata = json.loads(audit_output)
    assert metadata["source_ids"] == [document["source_id"]]
    assert metadata["result_count"] == 1
    assert "query_sha256" in json.loads(audit_input)


def test_owner_completion_control_audit_excludes_task_purpose(tmp_path):
    store = ControlStore(tmp_path / "decision-audit.sqlite")
    store.initialize("ui-check")
    api = BossCommandAPI(store)
    status, created = api.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = api.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    status, feedback = api.execute("MAINTAINER", "boss.simulation.feedback", feedback_input({
        "task_id": created["task_id"], "version": sent["task_version"],
    }))
    assert status == 200
    decision = {"task_id": created["task_id"], "task_version": feedback["task"]["version"], "feedback_id": feedback["feedback_id"]}
    authorization_id = store.authorize("ui-check", "complete_assignment", decision)
    result = store.control("ui-check", "decide", {"authorization_id": authorization_id, **decision})
    assert result["status"] == "COMPLETED_CONFIRMED"
    with store.connect() as db:
        audit_input, audit_output = db.execute("SELECT input,output FROM audit WHERE operation='decide'").fetchone()
    assert result["purpose"] not in audit_input + audit_output
    assert json.loads(audit_output)["task_id"] == created["task_id"]
    assert json.loads(audit_output)["status"] == "COMPLETED_CONFIRMED"


def test_committed_tool_request_can_be_read_after_its_authorization_is_revoked(tmp_path):
    store = ControlStore(tmp_path / "tool-receipt.sqlite")
    store.initialize("ui-check")
    content = {key: value for key, value in create_input().items() if key != "client_request_id"}
    authorization_id = store.authorize("ui-check", "create_assignment", content)
    payload = {**content, "authorization_id": authorization_id, "idempotency_key": "tool-receipt-original",
               "envelope": _data_envelope(initial_materials(), "tool-receipt-original")}
    original = store.invoke("create_assignment", payload)
    store.control("ui-check", "revoke", {"authorization_id": authorization_id})
    assert store.invoke("create_assignment", payload) == original
    with pytest.raises(web.HTTPForbidden):
        store.invoke("create_assignment", {**payload, "idempotency_key": "tool-receipt-new-action"})
    with pytest.raises(web.HTTPConflict):
        store.invoke("create_assignment", {**payload, "content_version": "2"})
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation='create_assignment'").fetchone()[0] == 1
