import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[2]
directory = Path(__file__).parent
checks = []
for name, check_id in (
    ("initial", "A12-CURRENT-AND-HISTORICAL-OBSERVATIONS"),
    ("revoked", "A12-REVOCATION-AND-HISTORY"),
    ("excluded", "A12-ACTUAL-NEW-RUNTIME-EXCLUSION"),
    ("deleted", "A12-DELETION-SCOPE-AND-REOPEN"),
    ("deleted-runtime", "A12-DELETED-NEW-RUNTIME"),
    ("errors", "A12-READ-FAILURE-AUTH-AND-RECOVERY"),
    ("cancel", "A12-CANCEL-PENDING-READ"),
):
    path = directory / f"w2-20261023-memory-ui-{name}.txt"
    tokens = MarkdownIt().parse(path.read_text())
    headings = [index for index, token in enumerate(tokens) if token.type == "inline" and token.content == "Result"
                and index > 0 and tokens[index - 1].type == "heading_open"]
    assert len(headings) == 1
    result = json.loads(next(token.content for token in tokens[headings[0] + 1:] if token.type == "inline"))
    assert result["status"] == "PASS" and result["check_id"] == check_id
    assert "简报优先展示现金" not in result["dom"]
    checks.append({"check_id": check_id, "status": "PASS", "source": str(path.relative_to(ROOT)),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

evidence = directory / "memory-ui-results"
evidence.mkdir(exist_ok=True)
runtime_checks = []
for name in ("excluded", "deleted"):
    path = directory / f"w2-20261023-memory-ui-{name}-runtime.json"
    result = json.loads(path.read_text())
    assert result["status"] == "PASS" and result["external_request_sent"] is True
    selection = result["projection"]["latest_context_selection"]
    assert selection["eligible"] is False and selection["run_status"] == "SUCCEEDED"
    transport_path = ROOT / result["receipt"]["transport_evidence"]
    assert transport_path.resolve().is_relative_to(ROOT / ".work")
    events = json.loads(transport_path.read_text())
    requests = [event for event in events if event["type"] == "request"]
    assert len(requests) == result["receipt"]["model_request_count"] == 1
    assert urlsplit(requests[0]["url"]).hostname == "api.deepseek.com"
    assert all(event["run_id"] == selection["run_id"] for event in events)
    destination = evidence / f"{name}-transport.json"
    shutil.copy2(transport_path, destination)
    runtime_checks.append({"stage": name, "run_id": selection["run_id"], "memory_version": selection["memory_version"],
                           "eligible": False, "model_request_count": 1, "model_completion_observed": True,
                           "answer_sha256": result["receipt"]["answer_sha256"],
                           "transport_evidence": str(destination.relative_to(ROOT))})

database = ROOT / ".work/w2-checks/memory-ui/memory.sqlite"
source = ROOT / ".work/w2-checks/live-memory-confirmation/test_live_revoked_memory_confi0/memory-confirmation.sqlite"
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
    current = json.loads(db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='memory' AND id='current'").fetchone()[0])
    assert current["version"] == "5" and current["confirmation_state"] == "DELETED" and current["text"] == ""
    assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind='runtime_run'").fetchone()[0] == 5
    assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind IN ('task','outbox')").fetchone()[0] == 0
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
    current = json.loads(db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='memory' AND id='current'").fetchone()[0])
    assert current["version"] == "3" and current["confirmation_state"] == "CONFIRMED"
    records = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run'")]
original = json.loads((directory / "w2-20261023-memory-confirmation/memory-confirmation-adoption.json").read_text())
assert sorted(records, key=lambda row: row["run_id"]) == sorted([stage["runtime_record"] for stage in original["stages"]], key=lambda row: row["run_id"])
sources = ["validation/boss_admin_config.py", "validation/boss_memory_runtime.py", "validation/boss_runtime_records.py",
           "app/webui/MaintainerMemoryStatus.tsx", "app/webui/MaintainerRuntimeRecords.tsx", "app/webui/boss-v6.css",
           "evidence/T19/check_memory_ui_server.py", "evidence/T19/check_memory_ui_state.py"]
sources.extend(str(path.relative_to(ROOT)) for path in sorted((directory / "memory-ui").iterdir()))
sources.extend(str(path.relative_to(ROOT)) for path in sorted(directory.glob("check_memory_ui_*.js")))
report = {"status": "PASS_COMPONENT_DOMAIN_AND_DOM_SCOPE", "checks": checks, "actual_runtime_checks": runtime_checks,
          "source_database_unchanged": True, "isolated_copy_version": "5", "task_count": 0, "outbox_count": 0,
          "new_model_request_count": 2, "private_body_recorded": False,
          "physical_secure_erasure_verified": False, "screenshots_taken": False,
          "visual_acceptance": "NOT_RUN", "public_rolechannel_acceptance": "NOT_RUN", "full_A19_accepted": False,
          "source_code_sha256_at_collection": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}}
(directory / "w2-20261023-memory-ui.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "dom_check_count": len(checks), "new_model_request_count": 2,
                  "source_database_unchanged": True, "full_A19_accepted": False}, ensure_ascii=False))
