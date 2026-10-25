from pathlib import Path
import sys

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from controls import ControlStore
from test_boss_command_api import create_input, send_input, feedback_input
from test_boss_self_commitments import create as create_commitment


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "fc07.sqlite")
    store.initialize("ui-check")
    return store, BossCommandAPI(store)


def sent_task(commands):
    code, created = commands.execute("BOSS", "boss.assignment.create", create_input())
    assert code == 200, created
    code, sent = commands.execute("BOSS", "boss.assignment.send", send_input(created))
    assert code == 200, sent
    return {"task_id": created["task_id"], "version": sent["task_version"]}


def proposal(commands, task, **changes):
    fields = feedback_input(task, "EXTENSION_REQUEST")
    fields.update({"proposed_due_at": "2026-10-26T17:00:00+08:00", **changes})
    return commands.execute("MAINTAINER", "boss.simulation.feedback", fields)


def test_new_commitment_requires_actual_nonempty_sources(services):
    store, commands = services
    code, result = create_commitment(commands, source_refs=[])
    assert code == 400, result
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('self_commitment','authorization','event')").fetchone()[0] == 0


@pytest.mark.parametrize("due", ["2026-10-23T08:00:00+08:00", "2026-10-26T17:00:00"])
def test_extension_proposal_requires_later_aware_deadline_without_writes(services, due):
    store, commands = services
    task = sent_task(commands)
    fields = feedback_input(task, "EXTENSION_REQUEST")
    fields["proposed_due_at"] = due
    code, result = commands.execute("MAINTAINER", "boss.simulation.feedback", fields)
    assert code == 400, result
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", task["task_id"])["version"] == task["version"]
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='feedback'").fetchone()[0] == 0


def decision(task, feedback, choice="APPROVE", key="fc07-owner-extension-decision"):
    return {"client_request_id": key, "task_id": task["task_id"], "task_version": feedback["task"]["version"],
            "feedback_id": feedback["feedback_id"], "decision": choice,
            "due_at": "2026-10-26T17:00:00+08:00" if choice == "APPROVE" else None, "reason": "本人核查当前进展和期限后决定"}


@pytest.mark.parametrize("choice", ["APPROVE", "REJECT"])
def test_extension_decision_is_single_durable_owner_choice_with_history(services, choice):
    from boss_assignment_extensions import AssignmentExtensionAPI
    store, commands = services
    task = sent_task(commands)
    code, requested = proposal(commands, task)
    assert code == 200, requested
    with store.connect() as db:
        original = store.get(db, "ui-check", "task", task["task_id"])
        event = store.get(db, "ui-check", "event", "task-due:" + task["task_id"])
    api, payload = AssignmentExtensionAPI(store), decision(task, requested, choice)
    assert original["due_at"] != payload["due_at"]
    result = api.execute("BOSS", payload)
    assert api.execute("BOSS", payload) == result
    assert result["status"] == original["status"]
    expected_due = payload["due_at"] if choice == "APPROVE" else original["due_at"]
    assert result["due_at"] == expected_due
    assert result["old_due_at"] == original["due_at"]
    history = AssignmentExtensionAPI(ControlStore(store.path)).read("BOSS", task["task_id"])
    assert AssignmentExtensionAPI(ControlStore(store.path)).receipt("BOSS", payload["client_request_id"])["result"] == result
    assert api.receipt("BOSS", "fc07-unknown-request")["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    assert len(history["decisions"]) == 1
    assert history["decisions"][0]["reason"] == payload["reason"]
    assert history["decisions"][0]["old_due_at"] == original["due_at"]
    assert history["decisions"][0]["new_due_at"] == expected_due
    with store.connect() as db:
        actual_event = store.get(db, "ui-check", "event", "task-due:" + task["task_id"])
        assert actual_event["due_at"] == expected_due
        if choice == "REJECT":
            assert actual_event == event
        assert store.get(db, "ui-check", "task_revision", task["task_id"] + ":v" + original["version"])["due_at"] == original["due_at"]
        audits = str(db.execute("SELECT input,output FROM audit").fetchall())
        assert payload["reason"] not in audits
        count = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", {**payload, "client_request_id": "fc07-second-decision", "task_version": result["version"]})
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", {**payload, "reason": "另一份决定内容"})
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == count


def test_legacy_extension_records_actual_reason_and_cannot_follow_rejection(services):
    from boss_assignment_extensions import AssignmentExtensionAPI
    store, commands = services
    task = sent_task(commands)
    code, requested = proposal(commands, task)
    assert code == 200
    rejected = AssignmentExtensionAPI(store).execute("BOSS", decision(task, requested, "REJECT"))
    code, result = commands.execute("BOSS", "boss.assignment.extend", {
        "client_request_id": "fc07-legacy-cannot-reverse", "task_id": task["task_id"], "task_version": rejected["version"],
        "feedback_id": requested["feedback_id"], "due_at": "2026-10-26T17:00:00+08:00"})
    assert code == 409, result


@pytest.mark.parametrize("role,error", [(None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden), ("boss-1", web.HTTPUnauthorized)])
def test_extension_role_and_injected_owner_confirmation_are_rejected(services, role, error):
    from boss_assignment_extensions import AssignmentExtensionAPI
    store, commands = services
    task = sent_task(commands)
    requested = proposal(commands, task)[1]
    api, payload = AssignmentExtensionAPI(store), decision(task, requested)
    with pytest.raises(error):
        api.execute(role, payload)
    with pytest.raises(error):
        api.read(role, task["task_id"])
    for field in ("confirmed", "owner_id", "namespace", "authorization_id"):
        with pytest.raises(web.HTTPBadRequest):
            api.execute("BOSS", {**payload, field: True})


def test_changed_original_commitment_source_blocks_extension_and_completion(services):
    store, commands = services
    code, commitment = create_commitment(commands)
    assert code == 200, commitment
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    for action, fields in (("extend", {"due_at": "2026-10-26T17:00:00+08:00", "reason": "核查后延期"}),
                           ("complete", {"evidence_refs": [{"source_id": "meeting-minutes", "version": "1"}]})):
        code, result = commands.execute("BOSS", "boss.commitment." + action, {
            "client_request_id": "fc07-stale-commitment-" + action, "commitment_id": commitment["commitment_id"], "expected_version": "1", **fields})
        assert code == 410, result
    code, canceled = commands.execute("BOSS", "boss.commitment.cancel", {
        "client_request_id": "fc07-cancel-stale-commitment", "commitment_id": commitment["commitment_id"], "expected_version": "1", "reason": "停止采用原资料"})
    assert code == 200, canceled


def test_extension_cas_rollback_and_withdrawn_source_stop_approval(services):
    from boss_assignment_extensions import AssignmentExtensionAPI
    store, commands = services
    task = sent_task(commands)
    requested = proposal(commands, task)[1]
    api, payload = AssignmentExtensionAPI(store), decision(task, requested)
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", {**payload, "task_version": task["version"]})
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPGone):
        api.execute("BOSS", payload)
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", task["task_id"])["version"] == requested["task"]["version"]
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='assignment_extension_decision'").fetchone()[0] == 0


def test_competing_decisions_commit_only_once(services):
    from concurrent.futures import ThreadPoolExecutor
    from boss_assignment_extensions import AssignmentExtensionAPI
    store, commands = services
    task = sent_task(commands)
    requested = proposal(commands, task)[1]
    api = AssignmentExtensionAPI(store)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(api.execute, "BOSS", decision(task, requested, choice, "fc07-concurrent-" + choice)) for choice in ("APPROVE", "REJECT")]
    assert sum(future.exception() is None for future in futures) == 1
    assert all(future.exception() is None or isinstance(future.exception(), web.HTTPConflict) for future in futures)
    assert len(api.read("BOSS", task["task_id"])["decisions"]) == 1


def test_legacy_approval_keeps_request_reason_and_original_deadline(services):
    from boss_assignment_extensions import AssignmentExtensionAPI
    store, commands = services
    task = sent_task(commands)
    requested = proposal(commands, task)[1]
    code, result = commands.execute("BOSS", "boss.assignment.extend", {
        "client_request_id": "fc07-legacy-approved-extension", "task_id": task["task_id"], "task_version": requested["task"]["version"],
        "feedback_id": requested["feedback_id"], "due_at": "2026-10-26T17:00:00+08:00"})
    assert code == 200, result
    saved = AssignmentExtensionAPI(store).read("BOSS", task["task_id"])["decisions"][0]
    assert saved["old_due_at"] == create_input()["due_at"]
    assert saved["new_due_at"] == result["due_at"] and saved["request_reason"]
    assert saved["reason"] is None


def test_completion_uses_latest_actual_result_and_keeps_business_event(services):
    store, commands = services
    task = sent_task(commands)
    assert commands.execute("MAINTAINER", "boss.simulation.event.seed", {"client_request_id": "fc07-current-business-event", "event_id": "event-1"})[0] == 200
    code, submitted = commands.execute("MAINTAINER", "boss.simulation.feedback", feedback_input(task, "RESULT_SUBMITTED"))
    assert code == 200, submitted
    next_fields = feedback_input({"task_id": task["task_id"], "version": submitted["task"]["version"]}, "RESULT_SUBMITTED")
    next_fields.pop("client_request_id")
    # 使用既有正式维护控制入口提交当前结果，不直接修改业务记录。
    latest = store.control("ui-check", "feedback", next_fields)
    code, result = commands.execute("BOSS", "boss.assignment.complete", {
        "client_request_id": "fc07-cannot-complete-earlier-result", "task_id": task["task_id"], "task_version": latest["task"]["version"],
        "feedback_id": submitted["feedback_id"]})
    assert code == 409, result
    code, done = commands.execute("BOSS", "boss.assignment.complete", {
        "client_request_id": "fc07-complete-current-result", "task_id": task["task_id"], "task_version": latest["task"]["version"],
        "feedback_id": latest["feedback"]["feedback_id"]})
    assert code == 200, done
    assert done["status"] == "COMPLETED_CONFIRMED"
    with store.connect() as db:
        assert store.get(db, "ui-check", "event", "task-due:" + task["task_id"])["state"] == "CANCELED"
        assert store.get(db, "ui-check", "event", "event-1")["state"] == "OPEN"


def test_schema_matches_actual_decision_results(services):
    from jsonschema import Draft202012Validator
    from boss_assignment_extensions import SCHEMA
    Draft202012Validator.check_schema(SCHEMA)


def test_approved_event_input_remains_usable_for_assignment_creation(services):
    store, commands = services
    assert commands.execute("MAINTAINER", "boss.simulation.event.seed", {"client_request_id": "fc07-event-before-task", "event_id": "event-1"})[0] == 200
    code, created = commands.execute("BOSS", "boss.assignment.create", create_input())
    assert code == 200, created
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", created["task_id"])["related_event_ids"] == ["event-1"]
