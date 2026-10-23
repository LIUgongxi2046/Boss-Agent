import hashlib
import json
import sqlite3
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[2]
directory = Path(__file__).parent
checks = []
for name, check_id in (
    ("query", "A15-QUERY-REAL-METADATA"),
    ("details", "A15-PAGINATION-DETAILS-COST"),
    ("edges", "A15-TIME-ID-EMPTY-AUTH"),
    ("cancel", "A15-CANCEL-PENDING-READ"),
    ("network", "A15-OFFLINE-AND-RECOVERY"),
):
    path = directory / f"w2-20261023-runtime-ui-{name}.txt"
    tokens = MarkdownIt().parse(path.read_text())
    headings = [index for index, token in enumerate(tokens)
                if token.type == "inline" and token.content == "Result"
                and index > 0 and tokens[index - 1].type == "heading_open"]
    assert len(headings) == 1
    result = json.loads(next(token.content for token in tokens[headings[0] + 1:] if token.type == "inline"))
    assert result["status"] == "PASS" and result["check_id"] == check_id
    assert "dom" in result and "合成水产饲料外销明细" not in result["dom"]
    checks.append({"check_id": check_id, "status": result["status"], "source": str(path.relative_to(ROOT)),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

database = ROOT / ".work/w2-checks/live-runtime-ui-data/test_live_next_turn_adopts_cur0/runtime.sqlite"
expected = json.loads((ROOT / "evidence/T16/runtime-version-ui/runtime-version-adoption.json").read_text())
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
    records = [json.loads(row[0]) for row in db.execute(
        "SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run' ORDER BY id")]
    assert sorted(records, key=lambda row: row["run_id"]) == sorted(
        [stage["runtime_record"] for stage in expected["stages"]], key=lambda row: row["run_id"])
    for kind in ("task", "outbox"):
        assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind=?", (kind,)).fetchone()[0] == 0

sources = ["app/webui/MaintainerRuntimeRecords.tsx", "app/webui/boss-v6.css",
           "validation/boss_runtime_records.py", "validation/runtime_records_query.py",
           "evidence/T19/check_runtime_ui_server.py", "evidence/T19/runtime_ui_cli.sh",
           "evidence/T19/check_runtime_ui_cancel.sh"]
sources.extend(str(path.relative_to(ROOT)) for path in sorted((directory / "runtime-ui").iterdir()))
sources.extend(str(path.relative_to(ROOT)) for path in sorted(directory.glob("check_runtime_ui_*.js")))
report = {"status": "PASS_COMPONENT_DOM_SCOPE", "checks": checks,
          "record_ids": [record["run_id"] for record in records],
          "existing_runtime_records_unchanged": True, "task_count": 0, "outbox_count": 0,
          "actual_database_reopened": True, "model_requests_for_ui_check": 0,
          "private_body_recorded": False, "screenshots_taken": False, "visual_acceptance": "NOT_RUN",
          "public_rolechannel_acceptance": "NOT_RUN", "linked_task_action_acceptance": "NOT_RUN",
          "source_code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}}
(directory / "w2-20261023-runtime-ui.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "check_count": len(checks),
                  "actual_database_reopened": True, "task_count": 0, "outbox_count": 0}, ensure_ascii=False))
