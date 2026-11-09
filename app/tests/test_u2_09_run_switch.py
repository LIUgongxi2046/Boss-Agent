import json
import sqlite3
import subprocess
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = [
    ROOT / ".work/upgrade2-u2-04/pytest-run-result-verified/test_result_persists_idempoten0/business.sqlite",
    ROOT / ".work/upgrade2-u2-04/pytest-result-citation-checks/test_result_citation_checks_us0/business.sqlite",
]


def test_run_switch_ignores_late_previous_response(tmp_path):
    run_ids = []
    for path in FIXTURES:
        with sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True) as db:
            run_ids.append(db.execute("SELECT run_id FROM agent_runs").fetchone()[0])
    server = subprocess.Popen([str(ROOT / ".work/upgrade2-u2-04/locked-env/bin/python"),
                               str(ROOT / "app/tests/upgrade2_run_switch_server.py")],
                              cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port = int(server.stdout.readline().strip())
        origin = "http://127.0.0.1:" + str(port)
        result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_run_switch_check.cjs")],
                                input=json.dumps({"origin": origin, "a": run_ids[0], "b": run_ids[1], "conversation_id": "result-check"}),
                                text=True, capture_output=True, cwd=ROOT, timeout=120)
        assert result.returncode == 0, result.stderr
        actual = json.loads(result.stdout)
        assert actual["final_run"] == run_ids[1]
        assert actual["final_text"] == "技术结果"
        assert actual["old_text_hidden"] is True
        assert actual["error"] == ""
        with urlopen(origin + "/test-state", timeout=5) as response:
            state = json.loads(response.read().decode("utf-8"))
        assert state["delayed_run"] == run_ids[0]
        (tmp_path / "result.json").write_text(json.dumps({"node": actual, "server": state}, ensure_ascii=False), encoding="utf-8")
    finally:
        server.terminate()
        server.wait(timeout=20)
