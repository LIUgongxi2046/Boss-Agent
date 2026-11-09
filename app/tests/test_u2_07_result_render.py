import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from agent_run_broker import RunBroker
from agent_run_store import RunStore


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/upgrade2-u2-04/pytest-run-result-verified/test_result_persists_idempoten0/business.sqlite"


def test_saved_technical_result_renders_with_source_version(tmp_path):
    source_digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    database = tmp_path / "business.sqlite"
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
    store = RunStore(database, allow_migration=False)
    with store.connect() as db:
        db.execute("BEGIN")
        row = db.execute("SELECT run_id FROM agent_runs").fetchone()
        run_id = row[0]
        run = store.read_run(run_id)
        event = store.result_in_transaction(db, run_id, run["goal_revision"])
        events = store.event_page_in_transaction(db, run_id, 0)["events"]
        citation_checks = RunBroker.result_citation_checks_in_transaction(db, run["space_id"], run_id, event)
    assert event is not None and event["payload"]["citations"]
    data = {"run": run, "actions": RunBroker.allowed_actions(run), "event": event, "events": events, "citation_checks": citation_checks, "source_sha256": source_digest}
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_07_result_render_check.cjs")],
        input=json.dumps(data, ensure_ascii=False), text=True, capture_output=True, check=True, cwd=ROOT)
    (tmp_path / "result.json").write_text(result.stdout, encoding="utf-8")
    assert json.loads(result.stdout)["source_version"] == event["payload"]["source_pins"][0]["version"]
