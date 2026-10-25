import argparse
from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_assignment_sources import AssignmentSourcesAPI
from boss_command_api import BossCommandAPI
from business import checksum
from controls import ControlStore

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--source-report", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
assert all(path.resolve().is_relative_to(ROOT / ".work") for path in (args.source, args.source_report, args.output_dir))
assert args.source.is_file() and args.source_report.is_file() and not args.output_dir.exists()
suite = ET.parse(args.source_report).getroot().find("testsuite")
assert suite is not None and suite.get("tests") == "577" and suite.get("failures") == suite.get("errors") == "0"
start = datetime.fromisoformat(suite.get("timestamp"))
end = start + timedelta(seconds=float(suite.get("time")))
args.output_dir.mkdir(mode=0o700)
target = args.output_dir / "legacy-task.sqlite"
tables = {"objects": "namespace,kind,id,body", "spaces": "namespace,active,snapshot", "idempotency": "namespace,operation,key,digest,result", "audit": "id,namespace,operation,input,output,created_at", "knowledge": "namespace,source_id,content"}


def manifest(db):
    return {name: checksum(db.execute("SELECT " + columns + " FROM " + name + " ORDER BY " + columns).fetchall()) for name, columns in tables.items()}


with closing(sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True)) as source:
    source_manifest = manifest(source)
    times = [datetime.fromisoformat(row[0]) for row in source.execute("SELECT created_at FROM audit")]
    assert times and all(start <= value <= end for value in times)
    with closing(sqlite3.connect(target)) as destination:
        source.backup(destination)
        assert manifest(destination) == source_manifest
target.chmod(0o600)
store = ControlStore(target)
with store.connect() as db:
    tasks = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='task'")]
    assert len(tasks) == 1 and tasks[0]["status"] == "OPEN" and "source_versions" not in tasks[0]
    task = tasks[0]
    original_receipts = db.execute("SELECT operation,key,digest,result FROM idempotency WHERE namespace='ui-check' AND operation='create_assignment'").fetchall()
    assert len(original_receipts) == 1
    binding = store.get(db, "ui-check", "assignment_source_binding", task["task_id"])
    assert binding["source_versions"] == {"finance-note": "1"}
reviewer = AssignmentSourcesAPI(store)
view = reviewer.read("BOSS", task["task_id"])
assert view["binding_state"] == "NEEDS_REVIEW" and view["can_confirm"] is True
request = {"client_request_id": "legacy-tool-source-confirm", "task_id": task["task_id"], "task_version": task["version"], "review_sha256": view["review_sha256"], "reason": "本人核查当前已知来源，确认用于后续交办。"}
confirmed = reviewer.execute("BOSS", request)
assert confirmed["sources_reconfirmed"] is True and confirmed["version"] == "2"
status, sent = BossCommandAPI(store).execute("BOSS", "boss.assignment.send", {"client_request_id": "legacy-tool-source-send", "task_id": task["task_id"], "task_version": confirmed["version"], "recipient_id": task["coordinator_id"], "body": "请核查当前经营资料并反馈证据。", "content_version": "1"})
assert status == 200 and sent["task_status"] == "WAITING_FEEDBACK"
assert reviewer.execute("BOSS", request) == confirmed
with store.connect() as db:
    current = store.get(db, "ui-check", "task", task["task_id"])
    assert current["source_versions"] == {"finance-note": "1"} and current["version"] == "3"
    assert current["status"] == "WAITING_FEEDBACK"
    assert db.execute("SELECT operation,key,digest,result FROM idempotency WHERE namespace='ui-check' AND operation='create_assignment'").fetchall() == original_receipts
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
with closing(sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True)) as source:
    assert manifest(source) == source_manifest
result = {"source": str(args.source), "source_report": str(args.source_report), "source_report_tests": 577, "source_manifest": source_manifest,
          "producer_commit_in_database": None, "target": str(target), "result": "PASS", "source_unchanged": True,
          "checks": ["实际既有Tool交办缺少来源版本", "已知创建绑定保持", "本人显式核查", "后续公共发送", "原创建回执保持", "原确认请求不重复执行", "源数据库保持"],
          "source_type": "SIMULATED", "external_services_invoked": False}
(args.output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False))
