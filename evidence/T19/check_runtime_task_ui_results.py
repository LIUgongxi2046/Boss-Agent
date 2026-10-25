import hashlib
import json
import sqlite3
from pathlib import Path

from lxml import etree
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[2]
directory = Path(__file__).parent
checks = []
for suffix, check_id in (
    ("", "A15-REAL-TASK-REFERENCE"),
    ("-cancel", "A15-TASK-CANCEL-PENDING-READ"),
    ("-errors", "A15-TASK-READ-ERRORS"),
):
    path = directory / ("w2-20261023-runtime-task-ui" + suffix + ".txt")
    tokens = MarkdownIt().parse(path.read_text())
    headings = [index for index, token in enumerate(tokens) if token.type == "inline" and token.content == "Result"
                and index > 0 and tokens[index - 1].type == "heading_open"]
    assert len(headings) == 1
    result = json.loads(next(token.content for token in tokens[headings[0] + 1:] if token.type == "inline"))
    assert result["status"] == "PASS" and result["check_id"] == check_id
    assert "提交当前会议关联的毛利变化解释" not in result["dom"]
    checks.append({"check_id": check_id, "status": result["status"], "source": str(path.relative_to(ROOT)),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

original = json.loads((ROOT / "evidence/T16/runtime-record-faults/w2-written-client-closed/runtime-records.json").read_text())
run = original["runs"][0]
source = ROOT / "validation/.work" / run["namespace"] / "business.sqlite"
copy = ROOT / ".work/w2-checks/runtime-task-ui/business.sqlite"
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as first:
    with sqlite3.connect(copy.as_uri() + "?mode=ro", uri=True) as second:
        assert tuple(first.iterdump()) == tuple(second.iterdump())
        observed = json.loads(second.execute("SELECT body FROM objects WHERE namespace=? AND kind='runtime_run' AND id=?",
                                            (run["namespace"], run["run_id"])).fetchone()[0])
        assert observed == run
        tasks = [json.loads(row[0]) for row in second.execute("SELECT body FROM objects WHERE namespace=? AND kind='task'",
                                                            (run["namespace"],))]
        assert len(tasks) == 1 and tasks[0]["status"] == "OPEN"
        assert tasks[0]["task_id"] == run["tool_results"][0]["task_id"]
        assert second.execute("SELECT COUNT(*) FROM objects WHERE namespace=? AND kind='outbox'",
                              (run["namespace"],)).fetchone()[0] == 0

test_reports = {}
for name in ("runtime-task-reference", "runtime-task-complete"):
    path = directory / ("w2-20261023-" + name + ".xml")
    suite = etree.parse(str(path)).getroot().find("testsuite")
    assert suite is not None and suite.get("failures") == "0" and suite.get("errors") == "0"
    test_reports[name] = {key: suite.get(key) for key in ("tests", "failures", "errors", "skipped", "time")}

sources = ["validation/runtime_records_query.py", "app/webui/MaintainerRuntimeRecords.tsx",
           "app/tests/test_boss_runtime_task_reference.py", "evidence/T19/check_runtime_ui_server.py",
           "evidence/T19/check_runtime_task_ui_results.py", "evidence/T19/runtime_ui_cli.sh"]
sources.extend(str(path.relative_to(ROOT)) for path in sorted(directory.glob("check_runtime_task_ui*.js")))
sources.append("evidence/T19/check_runtime_task_ui_cancel.sh")
report = {"status": "PASS_TASK_REFERENCE_COMPONENT_SCOPE", "checks": checks, "test_reports": test_reports,
          "run_id": run["run_id"], "task_id": tasks[0]["task_id"], "task_status": "OPEN", "task_count": 1,
          "outbox_count": 0, "source_database_unchanged": True, "copy_database_unchanged": True,
          "actual_database_reopened": True, "new_model_requests": 0, "screenshots_taken": False,
          "public_rolechannel_acceptance": "NOT_RUN", "visual_acceptance": "NOT_RUN", "full_A19_accepted": False,
          "source_code_sha256_at_collection": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}}
(directory / "w2-20261023-runtime-task-ui.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "check_count": len(checks), "source_database_unchanged": True,
                  "copy_database_unchanged": True, "task_count": 1, "outbox_count": 0}, ensure_ascii=False))
