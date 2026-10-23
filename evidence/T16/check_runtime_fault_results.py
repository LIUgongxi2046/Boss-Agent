import gzip
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / ".work/w2-checks/live-runtime-record-faults"
report_path = ROOT / "evidence/T16/w2-20261023-live-runtime-record-faults-initial.xml.gz"
with gzip.open(report_path, "rb") as original_report:
    suite = etree.parse(original_report).getroot().find("testsuite")
passed = [item.get("name") for item in suite.findall("testcase") if item.find("failure") is None and item.find("error") is None]
assert set(passed) == {"test_live_written_state_survives_model_transport_failure",
                      "test_live_explicit_cancellation_stops_pending_runtime",
                      "test_live_iteration_budget_stops_further_model_turns"}
timeout_path = ROOT / "evidence/T16/w2-20261023-live-runtime-record-timeout.xml"
timeout_suite = etree.parse(str(timeout_path)).getroot().find("testsuite")
assert timeout_suite.get("failures") == timeout_suite.get("errors") == "0" and timeout_suite.get("tests") == "1"
inputs = [path for path in sorted({item.resolve() for item in source.glob("test_*/runtime/*/runtime-records.json")})
          if not path.parent.name.startswith("w2-request-timeout-")]
inputs.extend(sorted({item.resolve() for item in (ROOT / ".work/w2-checks/live-runtime-record-timeout").glob("test_*/runtime/*/runtime-records.json")}))
assert len(inputs) == 4
checks = []
for path in inputs:
    projection = json.loads(path.read_text())
    assert projection["private_body_available_here"] is False and len(projection["runs"]) == 1
    row = projection["runs"][0]
    expected = {
        "w2-written-client-closed": ("FAILED", "error"),
        "w2-explicit-cancel": ("CANCELED", "cancelled"),
        "w2-request-timeout": ("TIMED_OUT", "cancelled"),
        "w2-iteration-budget": ("FAILED", "max_iterations"),
    }
    matches = [key for key in expected if row["namespace"].startswith(key + "-")]
    assert len(matches) == 1
    case = matches[0]
    assert row["status"] == expected[case][0]
    if case in {"w2-written-client-closed", "w2-iteration-budget"}:
        assert row["stop_reason"] == expected[case][1]
    if case == "w2-request-timeout":
        assert row["termination_source"] == "CALLER_DEADLINE_EXPIRED"
    assert row["finished_at"] and row["model_requests"] and row["cost_total"] is None
    database = ROOT / "validation/.work" / row["namespace"] / "business.sqlite"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        current = json.loads(db.execute("SELECT body FROM objects WHERE namespace=? AND kind='runtime_run' AND id=?",
                                       (row["namespace"], row["run_id"])).fetchone()[0])
        assert current == row
        tasks = [json.loads(item[0]) for item in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='task'", (row["namespace"],))]
        outbox_count = db.execute("SELECT COUNT(*) FROM objects WHERE namespace=? AND kind='outbox'", (row["namespace"],)).fetchone()[0]
    assert outbox_count == 0
    if case == "w2-written-client-closed":
        assert len(tasks) == 1 and tasks[0]["status"] == "OPEN"
        assert any(result.get("task_id") == tasks[0]["task_id"] for result in row["tool_results"])
    else:
        assert tasks == []
    destination = ROOT / "evidence/T16/runtime-record-faults" / case
    destination.mkdir(parents=True, exist_ok=True)
    filenames = ["runtime-records.json", "http-requests.json"]
    event_trace_present = (path.parent / "events.json").is_file()
    if event_trace_present:
        filenames.append("events.json")
    for filename in filenames:
        shutil.copy2(path.parent / filename, destination / filename)
    checks.append({"check_id": case, "run_id": row["run_id"], "status": row["status"],
                   "stop_reason": row["stop_reason"], "model_request_count": len(row["model_requests"]),
                   "task_count": len(tasks), "outbox_count": outbox_count,
                   "usage_coverage": row["usage_coverage"], "cost_total": None,
                   "event_trace_present": event_trace_present,
                   "database_reopen_verified": True, "evidence": str(destination.relative_to(ROOT))})
report = {"status": "PASS", "checks": checks, "source_type": "RUNTIME_RECORD",
          "test_reports": [str(report_path.relative_to(ROOT)), str(timeout_path.relative_to(ROOT))],
          "private_body_recorded": False, "public_application_accepted": False,
          "source_code_sha256_at_collection": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
              "validation/boss_runtime_records.py", "validation/connection.py", "validation/model_probe.py",
              "validation/fault_probe.py", "app/tests/test_boss_runtime.py")}}
(ROOT / "evidence/T16/w2-20261023-runtime-record-faults.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "checks": checks}, ensure_ascii=False))
