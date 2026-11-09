import json
import shutil
import sqlite3
import subprocess
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from boss_meetings import MeetingAPI
from boss_workspace_api import BossWorkspaceAPI
from business import checksum
from controls import ControlStore
from hermes_domain_intents import preview_domain_intent


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/upgrade2/u2-03/domain-preview-tests-006/test_assignment_preview_uses_c0/business.sqlite"


def test_domain_content_uses_actual_technical_previews(tmp_path):
    database = tmp_path / "business.sqlite"
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
    shutil.copytree(SOURCE.parent / "workspace", tmp_path / "workspace")
    store = ControlStore(database)
    runs = RunStore(database, allow_migration=False)
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    for session_file in (SOURCE.parent / "sessions").glob("*/*.jsonl"):
        shutil.copy2(session_file, sessions.sessions_dir / session_file.name)
    scope = RunScopeService(store, sessions, "ui-check")
    with runs.connect() as db:
        run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
    runs.interrupt_expired(run_id)
    lease = runs.acquire_lease(run_id, runs.read_run(run_id)["revision"], "u2-07-domain-check", 120)
    runs.transition(run_id, lease["revision"], "RECONCILING", "u2-07-domain-check", lease["epoch"])
    runs.transition(run_id, runs.read_run(run_id)["revision"], "RUNNING", "u2-07-domain-check", lease["epoch"])
    with store.connect() as db:
        data = MeetingAPI(store)._data(db)
        selected = [value for value in data["meeting"]["material_ids"] if value != data["event"]["event_id"]]
        documents = [store.get(db, "ui-check", "document", value) for value in selected]
        run_record = runs.read_run(run_id)
        session_key = "websocket:" + run_record["conversation_id"]
        binding = store.get(db, "ui-check", "conversation_source_binding", session_key)
        binding["source_refs"] = [{"source_id":item["source_id"],"version":item["version"]} for item in documents]
        binding["source_pins"] = [{"source_id":item["source_id"],"version":item["version"],"content_sha256":checksum(item)} for item in documents]
        store.put(db, "ui-check", "conversation_source_binding", session_key, binding)
    proof = scope.prove(run_record["conversation_id"], selected)
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", (json.dumps(selected),json.dumps(asdict(proof)),run_id))
    with runs.connect() as db:
        db.execute("BEGIN")
        data = MeetingAPI(store)._data(db)
        meeting = data["meeting"]
        draft = store.get(db, "ui-check", "meeting_draft", meeting["meeting_id"])
        minute = store.get(db, "ui-check", "minutes", meeting["meeting_id"])
        clock = store.get(db, "ui-check", "clock", "current")["at"]
        tasks = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='task'", ("ui-check",))]
        task = next(item for item in tasks if item["coordinator_id"] == "coordinator-1" and datetime.fromisoformat(item["due_at"]) > datetime.fromisoformat(clock))
        params = [
            ("boss.meeting.confirm", {"meeting_id":meeting["meeting_id"],"meeting_version":meeting["version"],"draft_version":draft["version"],"review_sha256":draft["review_sha256"]}),
            ("boss.meeting.cancel", {"meeting_id":meeting["meeting_id"],"expected_version":meeting["version"],"reason":meeting["title"]}),
            ("boss.minutes.confirm", {"meeting_id":meeting["meeting_id"],"expected_version":minute["version"],"source_id":minute["source_id"],"source_version":minute["source_version"]}),
            ("boss.assignment.create", {"purpose":task["purpose"],"coordinator_id":task["coordinator_id"],"due_at":task["due_at"],"timezone":task["timezone"],"evidence_requirements":task["evidence_requirements"],"related_meeting_id":meeting["meeting_id"],"related_event_ids":[data["event"]["event_id"]],"source_refs":["finance-note"],"content_version":"1"}),
        ]
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        previews = [preview_domain_intent(db, store, scope, run, action, fields) for action, fields in params]
    status, projection = BossWorkspaceAPI(store, "ui-check").serve("BOSS", "/api/boss/ui/workspace/minutes")
    assert status == 200
    with store.connect() as db:
        source = store.get(db, "ui-check", "document", projection["minute"]["source_id"])
    assert store.control("ui-check", "withdraw", {"source_id":source["source_id"], "version":source["version"]})["withdrawn"]
    status, withdrawn = BossWorkspaceAPI(store, "ui-check").serve("BOSS", "/api/boss/ui/workspace/minutes")
    assert status == 200 and withdrawn["minute"]["source_reference_state"] == "NEEDS_REVIEW"
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_07_domain_check.cjs")], cwd=ROOT,
                            input=json.dumps({"previews":previews,"task":task,"minutes":projection,"withdrawn":withdrawn,"source":source,"run":dict(run)}, ensure_ascii=False), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    (tmp_path / "domain-check.json").write_text(result.stdout, encoding="utf-8")
    assert json.loads(result.stdout)["preview_count"] == len(previews)
