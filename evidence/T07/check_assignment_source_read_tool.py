import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
W1 = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent")
COMMIT = "f854b07a66a153fc4a92c95c86cce788d009cffe"
received = {}
for relative in ("validation/business.py", "validation/controls.py", "validation/boss_assignment_sources.py",
                 "validation/boss_command_api.py", "validation/boss_source_access.py", "validation/boss_source_policy.py",
                 "specs/assignment-source-review.schema.json", "specs/selection-probe.json"):
    data = subprocess.check_output(["git", "show", COMMIT + ":" + relative], cwd=W1)
    assert (W1 / relative).read_bytes() == data
    received[relative] = hashlib.sha256(data).hexdigest()
sys.path.insert(0, str(W1 / "validation"))

from business import checksum
from controls import ControlStore

sys.path.insert(0, str(ROOT / "validation"))
from runtime_assignment_source_tool import BossAssignmentSourcesReadTool

schema = json.loads((W1 / "specs/assignment-source-review.schema.json").read_text())
work = ROOT / ".work/w2-checks/assignment-source-read"
work.mkdir(parents=True, exist_ok=True)
store = ControlStore(work / (str(uuid4()) + ".sqlite"))
store.initialize("ui-check")
events = json.loads((ROOT / "evidence/T16/deepseek-0-52111f59-8dc7-43cb-8582-cbdc7c4c36d0/events.json").read_text())
creation = next(event["input"] for event in events if event["type"] == "tool" and event["name"] == "create_assignment")
payload = {key: value for key, value in creation.items() if key not in {"envelope", "authorization_id", "idempotency_key"}}
authorization = store.authorize("ui-check", "create_assignment", payload)
created = store.invoke("create_assignment", {
    **payload, "authorization_id": authorization, "idempotency_key": str(uuid4()),
    "envelope": {**creation["envelope"], "execution_namespace": "ui-check", "session_id": "source-read", "request_id": str(uuid4())},
})
task_id = created["task_id"]
registry = ToolRegistry()
tool = BossAssignmentSourcesReadTool(store, "BOSS")
registry.register(tool)
for parameters in ({}, {"task_id": ""}, {"task_id": task_id, "namespace": "ui-check"},
                   {"task_id": task_id, "role": "BOSS"}):
    _, _, error = registry.prepare_call(tool.name, parameters)
    assert error
role_rejections = []
for role, status in ((None, 401), ("MAINTAINER", 403), ("CONTACT", 403)):
    with pytest.raises(web.HTTPException) as failure:
        BossAssignmentSourcesReadTool(store, role)
    assert failure.value.status == status
    role_rejections.append({"role": role, "http_status": status})
observations = []
for stage in ("current", "revised", "RECEIVED", "INCOMPLETE", "CONFLICTED", "SUPERSEDED", "WITHDRAWN", "EXPIRED", "forbidden"):
    with store.connect() as db:
        if stage == "revised":
            document = store.get(db, "ui-check", "document", "finance-note")
            store.put(db, "ui-check", "document", "finance-note", {**document, "version": "2"})
        elif stage == "forbidden":
            document = store.get(db, "ui-check", "document", "finance-note")
            contact = store.get(db, "ui-check", "initial", "snapshot")["contacts"][0]["contact_id"]
            store.put(db, "ui-check", "document", "finance-note", {**document, "access_scope": contact})
        elif stage != "current":
            document = store.get(db, "ui-check", "document", "finance-note")
            store.put(db, "ui-check", "document", "finance-note", {**document, "validity_state": stage})
    with store.connect() as db:
        before = tuple(db.iterdump())
    result = json.loads(asyncio.run(registry.execute(tool.name, {"task_id": task_id})))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    source = next(row for row in result["sources"] if row["source_id"] == "finance-note")
    assert result["task"]["task_id"] == task_id and result["task"]["status"] == "OPEN" and result["task"]["version"] == "1"
    assert source["pinned_version"] == "1"
    assert result["binding_state"] == ("CURRENT" if stage == "current" else "NEEDS_REVIEW")
    assert result["can_confirm"] is (stage == "revised")
    assert source["current_version"] == (None if stage == "forbidden" else "1" if stage == "current" else "2")
    assert (source["excerpt"] is not None) is (stage in {"current", "revised"})
    assert source["source_status"] == ("VALID" if stage in {"current", "revised"} else "FORBIDDEN" if stage == "forbidden" else stage)
    with store.connect() as db:
        assert tuple(db.iterdump()) == before
        assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind='outbox'").fetchone()[0] == 0
    observations.append({"stage": stage, "binding_state": result["binding_state"], "can_confirm": result["can_confirm"],
                         "pinned_version": source["pinned_version"], "current_version": source["current_version"],
                         "source_status": source["source_status"],
                         "excerpt_available": source["excerpt"] is not None, "result_sha256": checksum(result)})
for relative, digest in received.items():
    assert hashlib.sha256((W1 / relative).read_bytes()).hexdigest() == digest
loaded = {}
for name in ("business", "controls", "boss_assignment_sources", "boss_command_api", "boss_source_access", "boss_source_policy"):
    path = Path(sys.modules[name].__file__).resolve()
    expected = subprocess.check_output(["git", "show", COMMIT + ":validation/" + name + ".py"], cwd=W1)
    assert path.read_bytes() == expected
    loaded[name] = {"path": str(path), "sha256": hashlib.sha256(expected).hexdigest()}
report = {"status": "PASS_ASSIGNMENT_SOURCE_READ_ADAPTER", "received_commit": COMMIT,
          "task_id": task_id, "task_count": 1, "outbox_count": 0, "role_rejections": role_rejections,
          "observations": observations, "read_actions_changed_database": False, "source_confirmation_performed": False,
          "new_external_requests": 0, "business_payload_sha256": checksum(payload), "received_source_sha256": received,
          "actual_loaded_modules": loaded,
          "adapter_sha256": hashlib.sha256((ROOT / "validation/runtime_assignment_source_tool.py").read_bytes()).hexdigest(),
          "public_registration": "NOT_RUN", "model_adoption": "NOT_RUN", "full_A07_accepted": False}
(ROOT / "evidence/T07/w2-20261023-assignment-source-read.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "observation_count": len(observations),
                  "task_count": 1, "outbox_count": 0, "new_external_requests": 0}, ensure_ascii=False))
