import json
import subprocess
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]


def test_resume_timeout_unmount_switch_token_and_401():
    server = subprocess.Popen([str(ROOT / ".work/upgrade2-u2-04/locked-env/bin/python"),
                               str(ROOT / "app/tests/resume_status_late_server.py")],
                              cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port = int(server.stdout.readline().strip())
        origin = "http://127.0.0.1:" + str(port)
        runs = {"timeout": "00000000-0000-4000-8000-000000000010",
                "unmount": "00000000-0000-4000-8000-000000000011",
                "a": "00000000-0000-4000-8000-000000000012",
                "b": "00000000-0000-4000-8000-000000000013",
                "unauthorized": "00000000-0000-4000-8000-000000000014"}
        result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_resume_late_check.cjs")],
                                input=json.dumps({"origin": origin, "runs": runs}), text=True, capture_output=True,
                                cwd=ROOT, timeout=120)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"timeout_visible": True, "unmount_late_response_ignored": True,
                                             "run_switch_late_response_ignored": True, "token_change_late_response_ignored": True,
                                             "unauthorized_cleanup": True}
        with urlopen(origin + "/test-state", timeout=5) as response:
            state = json.loads(response.read().decode("utf-8"))
        assert state["counts"].get(runs["timeout"], 0) >= 1
        assert state["counts"].get(runs["unmount"], 0) >= 1
        assert state["counts"].get(runs["a"], 0) >= 2
        assert state["counts"].get(runs["unauthorized"], 0) >= 1
    finally:
        server.terminate()
        server.wait(timeout=20)
