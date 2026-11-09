import json
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path

from agent_artifacts import ArtifactPreparation
from agent_artifact_api import artifact_goal_revision_in_transaction
from agent_source_history import AgentSourceHistory
from boss_command_api import BossCommandAPI
from test_agent_artifact_source_history import set_binding
from test_agent_run_result import setup_result


ROOT = Path(__file__).resolve().parents[2]


def test_actual_artifact_reference_and_history_reach_component(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    commands = BossCommandAPI(store)
    source = {"client_request_id": "ui-history-create", "source_id": "sim-doc-ui-history", "title": "模拟会议资料", "author_contact_id": "finance-1", "published_at": "2020-01-01", "content": "模拟会议资料记录会议议题、负责人和需要确认的讨论事项，以及会议准备材料。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.create", source)[0] == 200
    with store.connect() as db:
        original = store.get(db, "ui-check", "document", source["source_id"])
    set_binding(store, results, original)
    proof = results.scope.prove("result-check", [source["source_id"]])
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", (json.dumps([source["source_id"]]), json.dumps(asdict(proof)), sink.config.run_id))
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 2, 200000)
    service = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=2, max_bytes=200000)
    artifact = service.create_meeting_brief(sink.config.run_id, [source["source_id"]], request_key="ui-history-artifact", format_name="MARKDOWN")
    revised = {**source, "client_request_id": "ui-history-revise", "expected_version": "1", "content": "模拟会议资料更新了会议议题、负责人和需要确认的讨论事项，以及会议准备材料。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.revise", revised)[0] == 200
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", source["source_id"])
    set_binding(store, results, document)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        history = AgentSourceHistory(runs, results.scope).read_artifact_in_transaction(db, sink.config.run_id, artifact["artifact_id"], artifact["version"], source["source_id"], "1")
    ref = artifact["source_refs"][0]
    reference = {"run_id":artifact["run_id"], "artifact_id":artifact["artifact_id"], "artifact_version":artifact["version"], "artifact_sha256":artifact["sha256"], "source_id":ref["source_id"], "version":ref["revision"], "sha256":ref["sha256"], "locator":ref["locator"]}
    assert history["content"] == source["content"] and history["historical"]
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact["artifact_id"],)).fetchone()
        db.row_factory = None
        artifact["goal_revision"] = artifact_goal_revision_in_transaction(db, record)
    before = runs.read_run(sink.config.run_id)["goal_revision"]
    receipt = runs.add_input(sink.config.run_id, before, "ui-history-goal-input", source["content"])
    assert artifact["goal_revision"] is None and receipt["goal_revision"] == before + 1
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_artifact_history_ui_check.cjs")], input=json.dumps({"history":history,"reference":reference,"artifact":artifact,"goal_before":before,"goal_after":receipt["goal_revision"]}, ensure_ascii=False), text=True, capture_output=True, check=True, cwd=ROOT)
    assert json.loads(result.stdout)["historical"]
    permission = subprocess.run(["node", str(ROOT / "app/tests/u2_09_artifact_history_permission_check.cjs")], input=json.dumps(reference, ensure_ascii=False), text=True, capture_output=True, check=True, cwd=ROOT, timeout=40)
    assert json.loads(permission.stdout) == {"status": 401, "expired": 1}
