import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore
from test_boss_command_api import create_input, send_input, feedback_input
from test_boss_assignment_nudge import nudge_input


@pytest.mark.parametrize("state,status", [
    ("EXPIRED", 410), ("WITHDRAWN", 410), ("CONFLICTED", 409),
    ("SUPERSEDED", 409), ("INCOMPLETE", 409), ("RECEIVED", 409),
])
def test_public_sources_apply_current_validity_to_body_search_and_new_writes(tmp_path, state, status):
    store = ControlStore(tmp_path / "public-source.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["validity_state"] = state
        store.put(db, "ui-check", "document", "finance-note", document)
        authorizations = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    reads = BossPageAPI(store)
    assert reads.serve("BOSS", "/api/boss/ui/evidence", "source=finance-note")[0] == status
    code, knowledge = reads.serve("BOSS", "/api/boss/ui/workspace/knowledge")
    assert code == 200
    assert all(item["source_id"] != "finance-note" for item in knowledge["results"])
    assert document["content"] not in json.dumps(knowledge, ensure_ascii=False)
    code, index = reads.serve("MAINTAINER", "/api/boss/ui/workspace/source-index")
    assert code == 200
    assert next(item for item in index["sources"] if item["source_id"] == "finance-note")["validity_state"] == state
    assert document["content"] not in json.dumps(index, ensure_ascii=False)
    assert BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input())[0] == status
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == authorizations


def test_canceled_task_feedback_keeps_expired_source_as_historical_reference(tmp_path):
    store = ControlStore(tmp_path / "historical-source.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    status, created = commands.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = commands.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    status, canceled = commands.execute("BOSS", "boss.assignment.cancel", {
        "client_request_id": "historical-source-cancel", "task_id": created["task_id"],
        "task_version": sent["task_version"], "reason": create_input()["purpose"],
    })
    assert status == 200
    with store.connect() as db:
        source = store.get(db, "ui-check", "document", "finance-note")
        source["validity_state"] = "EXPIRED"
        store.put(db, "ui-check", "document", "finance-note", source)
    status, feedback = commands.execute("MAINTAINER", "boss.simulation.feedback", feedback_input({
        "task_id": created["task_id"], "version": canceled["version"],
    }))
    assert status == 200 and feedback["historical_only"] is True
    assert feedback["task"]["status"] == "CANCELED"
    assert BossPageAPI(ControlStore(store.path)).serve("BOSS", "/api/boss/ui/evidence", "source=finance-note")[0] == 410


def test_public_nudge_requires_the_original_complete_source_binding(tmp_path):
    store = ControlStore(tmp_path / "nudge-binding.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    status, created = commands.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = commands.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    with store.connect() as db:
        source = store.get(db, "ui-check", "document", "finance-note")
        source["published_at"] = store.get(db, "ui-check", "document", "meeting-minutes")["published_at"]
        store.put(db, "ui-check", "document", "finance-note", source)
        count = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    status, _ = commands.execute("BOSS", "boss.assignment.nudge", {
        "client_request_id": "public-nudge-source-binding", **nudge_input(created, sent["task_version"]),
    })
    assert status == 409
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='assignment_nudge'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == count
