import json
import subprocess
from pathlib import Path

from agent_source_history import AgentSourceHistory
from business import checksum
from test_agent_source_history import prepare_history


ROOT = Path(__file__).resolve().parents[2]


def test_history_result_and_ui_use_same_recorded_version(tmp_path):
    store, runs, results, sink, commands, create, result, session_id = prepare_history(tmp_path)
    revision = {**create, "client_request_id": "ui-history-revision", "expected_version": "1", "content": "模拟会议资料已经更新，包含新的讨论事项、负责人以及当前版本的完整原文。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.revise", revision)[0] == 200
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = store.get(db, "ui-check", "document", create["source_id"])
        binding = store.get(db, "ui-check", "conversation_source_binding", session_id)
        binding["source_refs"] = [{"source_id": current["source_id"], "version": current["version"]}]
        binding["source_pins"] = [{**binding["source_refs"][0], "content_sha256": checksum(current)}]
        store.put(db, "ui-check", "conversation_source_binding", session_id, binding)
    history = AgentSourceHistory(runs, results.scope)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        value = history.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1")
    assert value["content"] == create["content"] and value["historical"]
    reference = {"run_id": value["run_id"], "event_id": value["event_id"], "source_id": value["source_id"], "version": value["version"], "sha256": value["sha256"], "locator": value["citations"][0]["locator"]}
    checked = subprocess.run(["node", str(ROOT / "app/tests/u2_09_source_history_ui_check.cjs")], input=json.dumps({"history": value, "reference": reference}, ensure_ascii=False), text=True, capture_output=True, check=True, cwd=ROOT)
    assert json.loads(checked.stdout)["historical"] is True
    permission = subprocess.run(["node", str(ROOT / "app/tests/u2_04_source_history_permission_check.cjs")], input=json.dumps(reference, ensure_ascii=False), text=True, capture_output=True, check=True, cwd=ROOT, timeout=40)
    assert json.loads(permission.stdout) == {"status": 401, "expired": 1}
