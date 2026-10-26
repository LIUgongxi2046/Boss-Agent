import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from controls import ControlStore
from business import now
from boss_v7_owner import OwnerWorkspaceAPI


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "library.sqlite")
    result.initialize("ui-check")
    return result


def read(store, role="BOSS"):
    return OwnerWorkspaceAPI(store).read(role, "/api/boss/ui/owner/meeting-library", "")


def test_library_projects_current_meeting_documents_and_gaps(store):
    projection = read(store)
    assert projection["projection"] == "meeting-library"
    assert projection["namespace"] == "ui-check"
    kinds = {record["kind"] for record in projection["records"]}
    assert kinds == {"meeting", "document"}
    meeting = next(record for record in projection["records"] if record["kind"] == "meeting")
    assert meeting["id"] == "meeting-1"
    assert meeting["local_date"] == "2026-10-23"
    assert meeting["timezone"] == "Asia/Shanghai"
    assert meeting["material_gaps"] == []
    assert meeting["material_state"] == "READY"
    minutes = next(action for action in meeting["actions"] if action["id"] == "minutes")
    assert minutes["enabled"] is False and minutes["disabled_reason"]
    source = next(action for action in meeting["actions"] if action["id"] == "source")
    assert source["enabled"] is True and source["source_id"] == "finance-note"
    document = next(record for record in projection["records"] if record["id"] == "finance-note")
    assert document["material_state"] == "VALID"
    assert next(action for action in document["actions"] if action["id"] == "source")["enabled"] is True
    coverage = {item["kind"]: item for item in projection["coverage"]}
    assert coverage["meeting"]["state"] == "COMPLETE"
    assert coverage["document"]["state"] == "COMPLETE"
    assert coverage["approval"]["state"] == "NOT_PROVIDED"
    assert coverage["research"]["state"] == "NOT_PROVIDED"
    assert coverage["people"]["state"] == "NOT_PROVIDED"


def test_library_reads_minutes_and_application_states_without_writing(store):
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        store.put(db, "ui-check", "minutes", "meeting-1",
                  {"minute_id": "minute-1", "meeting_id": "meeting-1", "version": "1",
                   "state": "DRAFT", "source_version": "1", "entries": [], "source_type": "SIMULATED"})
        store.put(db, "ui-check", "application", "application-1",
                  {"application_id": "application-1", "title": "模拟申请", "description": "模拟申请说明",
                   "applicant_contact_id": "coordinator-1", "amount": "1000.00", "currency": "CNY",
                   "version": "1", "source_id": "application-1-attachment", "source_version": "1",
                   "state": "PENDING_DECISION", "source_type": "SIMULATED",
                   "seeded_by_role": "MAINTAINER", "created_at": now(), "decision_id": None,
                   "funds_transferred": False, "professional_release_issued": False})
    projection = read(store)
    meeting = next(record for record in projection["records"] if record["kind"] == "meeting")
    assert meeting["minute_state"] == "DRAFT"
    assert next(action for action in meeting["actions"] if action["id"] == "minutes")["enabled"] is True
    approval = next(record for record in projection["records"] if record["kind"] == "approval")
    assert approval["material_state"] == "PENDING_DECISION"
    assert next(action for action in approval["actions"] if action["id"] == "open")["enabled"] is True
    source = next(action for action in approval["actions"] if action["id"] == "source")
    assert source["enabled"] is False and source["disabled_reason"]
    with store.connect() as db:
        after = db.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        assert after == before + 2
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0


def test_library_rejects_non_owner_roles(store):
    with pytest.raises(web.HTTPForbidden):
        read(store, "MAINTAINER")
    with pytest.raises(web.HTTPUnauthorized):
        read(store, None)
