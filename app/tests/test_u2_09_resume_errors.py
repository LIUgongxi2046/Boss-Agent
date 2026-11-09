import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_resume_schema_and_http_errors_reach_component():
    server = subprocess.Popen([str(ROOT / ".work/upgrade2-u2-04/locked-env/bin/python"),
                               str(ROOT / "app/tests/resume_status_error_server.py")],
                              cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port = int(server.stdout.readline().strip())
        origin = "http://127.0.0.1:" + str(port)
        result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_resume_errors_check.cjs")],
                                input=json.dumps({"origin": origin}), text=True, capture_output=True, cwd=ROOT, timeout=120)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"schema_error_visible": True, "http_error_visible": True,
                                             "valid_state_visible": True, "retry_visible": True}
    finally:
        server.terminate()
        server.wait(timeout=20)
