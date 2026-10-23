import asyncio
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[2]
W1 = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent")
COMMIT = "f854b07a66a153fc4a92c95c86cce788d009cffe"
inputs = {}
for relative in ("specs/openapi.yaml", "specs/data-dictionary.json", "specs/runtime-events.schema.json",
                 "validation/business.py", "validation/controls.py", "validation/boss_meetings.py",
                 "validation/boss_command_api.py", "validation/boss_memory.py", "specs/selection-probe.json",
                 "validation/boss_source_access.py", "validation/boss_source_policy.py"):
    committed = subprocess.check_output(["git", "show", COMMIT + ":" + relative], cwd=W1)
    if relative.startswith("validation/") or relative == "specs/selection-probe.json":
        assert (W1 / relative).read_bytes() == committed
    inputs[relative] = hashlib.sha256(committed).hexdigest()
sys.path.insert(0, str(ROOT / "validation"))
sys.path.insert(0, str(W1 / "validation"))

from business import checksum
from controls import ControlStore
from boss_meetings import MeetingAPI
from runtime_meeting_tool import BossCurrentMeetingTool

backend = yaml.safe_load(subprocess.check_output(["git", "show", COMMIT + ":specs/openapi.yaml"], cwd=W1))
validated = []


def schema_check(action, payload, result):
    operation = next(row for row in backend["x-websocket-operations"] if row["action"] == "boss.meeting." + action)
    for name, value in (("input", payload), ("output", result)):
        Draft202012Validator({**backend, "$ref": operation[name]}, format_checker=FormatChecker()).validate(value)
    validated.append(operation["operationId"])


work = ROOT / ".work/w2-checks/received-v13"
work.mkdir(parents=True, exist_ok=True)
store = ControlStore(work / (str(uuid4()) + ".sqlite"))
baseline = store.initialize("ui-check")
assert baseline["snapshot_sha256"] == "75e5c19645f0e7cd1f5036a0a441de0a1a59c8eb1b9d1be5137ef0414eb2f345"
api = MeetingAPI(store)
tool = BossCurrentMeetingTool(store, "BOSS")
before = json.loads(asyncio.run(tool.execute()))
initial = before["meeting"]
details = {
    "client_request_id": str(uuid4()), "meeting_id": initial["meeting_id"], "meeting_version": initial["version"],
    "expected_version": "0", "purpose": "核查现有获准会议材料", "starts_at": initial["starts_at"],
    "ends_at": (datetime.fromisoformat(initial["starts_at"]) + timedelta(hours=1)).isoformat(),
    "timezone": initial["timezone"], "preparation_due_at": None,
    "participant_ids": initial["participant_ids"], "source_refs": [{"source_id": "finance-note", "version": "1"}],
}
draft = api.execute("BOSS", "draft.save", details)
schema_check("draft.save", details, draft)
pending = json.loads(asyncio.run(tool.execute()))
assert pending["meeting"] == before["meeting"]
assert pending["draft"]["version"] == draft["version"]
confirmation = {
    "client_request_id": str(uuid4()), "meeting_id": initial["meeting_id"], "meeting_version": initial["version"],
    "draft_version": draft["version"], "review_sha256": draft["review_sha256"], "acknowledge_conflict": True,
}
confirmed = api.execute("BOSS", "confirm", confirmation)
schema_check("confirm", confirmation, confirmed)
scheduled = json.loads(asyncio.run(tool.execute()))
assert scheduled["meeting"]["version"] == confirmed["version"] == "2"
assert scheduled["meeting"]["state"] == "SCHEDULED"
assert scheduled["meeting"]["ends_at"] == details["ends_at"]
assert scheduled["draft"]["state"] == "CONFIRMED"
with store.connect() as db:
    assert store.get(db, "ui-check", "initial", "snapshot")["meeting"]["version"] == "1"
cancel_input = {
    "client_request_id": str(uuid4()), "meeting_id": initial["meeting_id"],
    "expected_version": "2", "reason": "本人取消本次安排核查",
}
canceled = api.execute("BOSS", "cancel", cancel_input)
schema_check("cancel", cancel_input, canceled)
reopened = json.loads(asyncio.run(BossCurrentMeetingTool(ControlStore(store.path), "BOSS").execute()))
assert reopened["meeting"]["version"] == canceled["version"] == "3"
assert reopened["meeting"]["state"] == "CANCELED"
for role, exception in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden), ("contact-1", web.HTTPForbidden)):
    with pytest.raises(exception):
        BossCurrentMeetingTool(store, role)

held_store = ControlStore(work / (str(uuid4()) + ".sqlite"))
held_store.initialize("ui-check")
held_api = MeetingAPI(held_store)
held_draft = held_api.execute("BOSS", "draft.save", details)
held_confirm = held_api.execute("BOSS", "confirm", {**confirmation, "draft_version": held_draft["version"], "review_sha256": held_draft["review_sha256"]})
held_store.control("ui-check", "clock", {"at": initial["starts_at"]})
held_input = {"client_request_id": str(uuid4()), "meeting_id": initial["meeting_id"], "expected_version": held_confirm["version"], "reason": "本人确认本次会议已经举行"}
held_result = held_api.execute("BOSS", "held", held_input)
schema_check("held", held_input, held_result)
held_read = json.loads(asyncio.run(BossCurrentMeetingTool(ControlStore(held_store.path), "BOSS").execute()))
assert held_read["meeting"]["state"] == "HELD" and held_read["meeting"]["version"] == "3"

path = next((ROOT / "evidence/T16").glob("deepseek-*/events.json"))
query = copy.deepcopy(next(row["input"] for row in json.loads(path.read_text()) if row["type"] == "tool" and row["name"] == "query_metrics"))
query["envelope"].update(execution_namespace="ui-check", request_id=str(uuid4()))
queried = store.invoke("query_metrics", query)
with store.connect() as db:
    source = store.get(db, "ui-check", "document", "finance-note")
    store.put(db, "ui-check", "document", "finance-note", {**source, "version": "2"})
with pytest.raises(web.HTTPConflict):
    store.invoke("read_evidence", {
        "envelope": query["envelope"], "query_id": queried["query_id"], "source_ids": ["finance-note"],
        "detail_refs": queried["detail_refs"],
    })
fresh_query = store.invoke("query_metrics", query)
readback = store.invoke("read_evidence", {
    "envelope": query["envelope"], "query_id": fresh_query["query_id"], "source_ids": ["finance-note"],
    "detail_refs": fresh_query["detail_refs"],
})
source_version = next(item["content"]["version"] for item in readback["original_records"] if item["record_id"] == "finance-note")
assert next(item["content"]["content"] for item in readback["original_records"] if item["record_id"] == "finance-note") == source["content"]
dictionary = json.loads(subprocess.check_output(["git", "show", COMMIT + ":specs/data-dictionary.json"], cwd=W1))
assert backend["info"]["version"] == dictionary["version"] == "1.5.0"
assert fresh_query["query_id"] != queried["query_id"]
assert readback["sources"][0]["version"] == source_version == "2"
assert backend["paths"]["/api/boss/ui/meeting-arrangement"]["get"]["operationId"] == tool.name
Draft202012Validator(tool.parameters).validate({})
read_schema = backend["paths"]["/api/boss/ui/meeting-arrangement"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
for projection in (before, pending, scheduled, reopened, held_read):
    Draft202012Validator(read_schema, format_checker=FormatChecker()).validate(projection)
report = {
    "status": "PASS_CURRENT_MEETING_AND_SOURCE_VERSION_BINDING", "received_commit": COMMIT,
    "backend_version": backend["info"]["version"], "input_sha256": inputs,
    "runtime_meeting_tool_sha256": hashlib.sha256((ROOT / "validation/runtime_meeting_tool.py").read_bytes()).hexdigest(),
    "meeting_read": {"initial_version": "1", "draft_does_not_replace_current": True,
                     "confirmed_version": scheduled["meeting"]["version"], "canceled_version": reopened["meeting"]["version"],
                     "terminal_state_reread": reopened["meeting"]["state"], "initial_snapshot_unchanged": True,
                     "held_state_reread": held_read["meeting"]["state"], "action_schema_checks": validated,
                     "actual_read_projections_validated": 5,
                     "authentication_rejection": True, "maintainer_rejection": True, "contact_rejection": True},
    "source_revision_check": {"current_document_version": source_version, "reported_source_version": readback["sources"][0]["version"],
                              "source_version_matches": readback["sources"][0]["version"] == source_version,
                              "body_changed": False, "earlier_query_status": 409, "fresh_query_created": True},
    "source_validity_fields_declared": all(field in dictionary["entities"]["document"]["fields"]
                                          for field in ("valid_until", "validity_state")),
    "external_request_sent": False, "public_runtime_registered": False, "full_A07_accepted": False,
}
for relative, expected in inputs.items():
    if relative.startswith("validation/") or relative == "specs/selection-probe.json":
        assert hashlib.sha256((W1 / relative).read_bytes()).hexdigest() == expected
output = Path(__file__).parent / "w2-20261023-received-v13.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
