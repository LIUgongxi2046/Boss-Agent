from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from controls import ControlStore
from boss_command_api import BossCommandAPI
from aiohttp import web
from business import checksum
from boss_alert_policy import MANIFEST
from boss_alert_rules import BusinessAlertRulesAPI, BusinessAlertInputAPI
from boss_business_alerts import BusinessAlertsAPI


@pytest.fixture
def store(tmp_path):
    value = ControlStore(tmp_path / "fc04.sqlite")
    value.initialize("ui-check")
    assert BossCommandAPI(value).execute("MAINTAINER", "boss.simulation.event.seed", {
        "client_request_id": "fc04-approved-event", "event_id": "event-1"})[0] == 200
    return value


def rules(store, important=False):
    store.control("ui-check", "rules", {"version": "2", "cooldown_seconds": 1800, "quiet_start": 22, "quiet_end": 7,
        "timezone": "Asia/Shanghai", "important_escalation": important})


def clock(store, at):
    store.control("ui-check", "clock", {"at": at})


def test_technical_important_switch_cannot_override_quiet_without_owner_setting(store):
    rules(store, True)
    store.control("ui-check", "event", {"event_id": "event-1", "version": "2", "state": "OPEN", "impact": "IMPORTANT", "due_at": "2026-10-24T17:00:00+08:00"})
    clock(store, "2026-10-24T23:00:00+08:00")
    result = store.dispatch_due("ui-check")[0]
    assert result["state"] == "SUPPRESSED"
    assert result["reason"] == "QUIET_HOURS"


def test_dispatch_preserves_each_distinct_outcome_in_history(store):
    rules(store)
    clock(store, "2026-10-24T18:00:00+08:00")
    assert store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"
    assert store.dispatch_due("ui-check")[0]["state"] == "SUPPRESSED"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='dispatch_history'").fetchone()[0] == 2


def configure(store, role="MAINTAINER", **configuration):
    api = BusinessAlertRulesAPI(store)
    current = api.read("BOSS")
    cfg = {**MANIFEST["configuration"], **configuration}
    suffix = str(int(current["draft"]["version"]) + 1) if current["draft"] else "1"
    saved = api.execute(role, "save", {"client_request_id": "fc04-rule-save-" + suffix, "expected_version": current["draft"]["version"] if current["draft"] else "0", "configuration": cfg})
    validated = api.execute(role, "validate", {"client_request_id": "fc04-rule-validate-" + suffix, "expected_version": saved["version"]})
    active = api.execute(role, "activate", {"client_request_id": "fc04-rule-activate-" + suffix, "expected_version": validated["version"], "expected_active_version": current["active_version"]})
    return active


def view(store):
    return BusinessAlertsAPI(store).read("BOSS")["items"][0]


def load(store, frame="MARGIN_DROP"):
    all_rows = BusinessAlertsAPI(store).read("BOSS")["items"]
    previous = all_rows[0]["event_version"] if all_rows else "0"
    payload = {"client_request_id": "fc04-observation-" + str(int(previous) + 1), "expected_version": previous,
        "mode": "SIMULATED", "definition_version": "FC04-ALERT-1", "seed": 20261024, "frame": frame}
    result = BusinessAlertInputAPI(store).load("MAINTAINER", payload)
    assert BusinessAlertInputAPI(store).load("MAINTAINER", payload) == result
    assert BusinessAlertInputAPI(ControlStore(store.path)).receipt("MAINTAINER", payload["client_request_id"])["result"] == result
    return result


def handle(store, action, key=None, **fields):
    current = view(store)
    payload = {"client_request_id": key or "fc04-owner-" + action, "event_id": current["event_id"], "event_version": current["event_version"],
        "expected_version": current["reminder_version"], "review_sha256": current["review_sha256"], **fields}
    return BusinessAlertsAPI(store).execute("BOSS", action, payload), payload


def ready(store, frame="RESOURCE_SHORTAGE"):
    rules(store)
    configure(store)
    load(store, frame)
    return store.dispatch_due("ui-check")[0]


def test_rule_save_validate_and_activate_are_distinct_and_maintenance_is_limited(store):
    api = BusinessAlertRulesAPI(store)
    saved = api.execute("MAINTAINER", "save", {"client_request_id": "fc04-only-rule-draft", "expected_version": "0", "configuration": MANIFEST["configuration"]})
    assert api.read("BOSS")["active"] is None and saved["state"] == "DRAFT"
    with pytest.raises(web.HTTPConflict):
        api.execute("MAINTAINER", "activate", {"client_request_id": "fc04-unvalidated-activation", "expected_version": saved["version"], "expected_active_version": "0"})
    with pytest.raises(web.HTTPForbidden):
        api.execute("MAINTAINER", "save", {"client_request_id": "fc04-expanded-business-rule", "expected_version": saved["version"], "configuration": {**MANIFEST["configuration"], "threshold_pp": "1"}})
    active = configure(store, "BOSS", threshold_pp="2")
    assert active["state"] == "ACTIVE" and api.read("MAINTAINER")["active"] is None
    with pytest.raises(web.HTTPForbidden):
        api.execute("MAINTAINER", "disable", {"client_request_id": "fc04-maint-owner-rule-denied", "expected_version": active["version"]})


def test_formal_input_keeps_snapshot_provenance_and_requires_continuous_observations(store):
    rules(store)
    configure(store)
    with store.connect() as db:
        original = checksum(store.get(db, "ui-check", "initial", "snapshot"))
    load(store)
    assert store.dispatch_due("ui-check")[0]["reason"] == "DURATION_NOT_MET"
    clock(store, "2026-10-22T09:10:00+08:00")
    assert store.dispatch_due("ui-check")[0]["reason"] == "OBSERVATION_NOT_UPDATED"
    load(store)
    assert view(store)["evaluation"]["duration_seconds"] == 0
    for minute in (15, 20):
        clock(store, f"2026-10-22T09:{minute}:00+08:00")
        load(store)
        result = store.dispatch_due("ui-check")[0]
    assert result["state"] == "DELIVERED"
    actual = view(store)
    assert actual["facts"]["base_value"] == "10.0" and actual["facts"]["current_value"] == "8.00"
    assert actual["evaluation"]["duration_seconds"] == 600
    assert actual["data_as_of"] == "2026-10-10T23:59:59+08:00"
    assert actual["observed_at"] == "2026-10-22T09:20:00+08:00"
    assert actual["sources"][1]["author_contact_id"] == "simulated-generator:FC04-ALERT-1"
    assert actual["documents"][1]["real_enterprise_data"] is False
    assert actual["documents"][1]["business_authorization_granted"] is False
    with store.connect() as db:
        assert checksum(store.get(db, "ui-check", "initial", "snapshot")) == original


@pytest.mark.parametrize("frame,reason", [("PROGRESS", "GENERAL_PROGRESS_SUMMARY"), ("LOW_CONFIDENCE", "INSUFFICIENT_CURRENT_EVIDENCE"), ("MISSING_HANDLER", "INSUFFICIENT_CURRENT_EVIDENCE")])
def test_general_progress_and_missing_conditions_never_claim_immediate_delivery(store, frame, reason):
    result = ready(store, frame)
    assert result["state"] == "SUPPRESSED" and result["reason"] == reason
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='business_alert_delivery'").fetchone()[0] == 0


def test_same_event_merges_and_only_confirmed_important_escalation_bypasses_cooldown(store):
    rules(store, True)
    configure(store)
    for minute in (0, 5, 10):
        clock(store, f"2026-10-22T09:{minute:02}:00+08:00")
        load(store)
        result = store.dispatch_due("ui-check")[0]
    assert result["state"] == "DELIVERED"
    clock(store, "2026-10-22T09:15:00+08:00")
    load(store, "RESOURCE_SHORTAGE")
    assert store.dispatch_due("ui-check")[0]["reason"] == "SAME_INCIDENT_MERGED"
    configure(store, "BOSS", important_escalation=True)
    assert store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"
    assert store.dispatch_due("ui-check")[0]["reason"] == "SAME_INCIDENT_MERGED"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='notification'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='business_alert_delivery'").fetchone()[0] == 2


def test_quiet_override_requires_current_explicit_owner_notification_setting(store):
    from test_boss_owner_preferences import notice, confirm_input
    rules(store, True)
    configure(store, "BOSS", important_escalation=True)
    clock(store, "2026-10-22T23:00:00+08:00")
    load(store, "RESOURCE_SHORTAGE")
    assert store.dispatch_due("ui-check")[0]["reason"] == "QUIET_HOURS"
    commands = BossCommandAPI(store)
    code, draft = commands.execute("BOSS", "boss.owner.notice.save", {"client_request_id": "fc04-owner-important-draft", **notice(important_during_quiet=True)})
    assert code == 200
    code, confirmed = commands.execute("BOSS", "boss.owner.notice.confirm", {"client_request_id": "fc04-owner-important-confirm", **confirm_input(draft)})
    assert code == 200
    assert store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"
    assert commands.execute("BOSS", "boss.authorization.revoke", {"client_request_id": "fc04-stop-important-setting", "authorization_id": confirmed["authorization_id"], "expected_version": "1", "reason": "停止后续采用"})[0] == 200
    assert store.dispatch_due("ui-check")[0]["reason"] == "QUIET_HOURS"


def test_ack_snooze_expiry_and_close_preserve_independent_event_and_history(store):
    assert ready(store)["state"] == "DELIVERED"
    api = BusinessAlertsAPI(store)
    ack, ack_input = handle(store, "ack")
    assert ack["state"] == "ACKNOWLEDGED"
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", "ack", {**ack_input, "expected_version": "999"})
    snoozed, payload = handle(store, "snooze", until="2026-10-22T09:30:00+08:00")
    assert api.execute("BOSS", "snooze", payload) == snoozed
    assert BusinessAlertsAPI(ControlStore(store.path)).receipt("BOSS", "snooze", payload["client_request_id"])["result"] == snoozed
    clock(store, "2026-10-22T09:05:00+08:00")
    load(store, "RESOURCE_SHORTAGE")
    assert store.dispatch_due("ui-check")[0]["reason"] == "BOSS_SNOOZED"
    clock(store, "2026-10-22T09:30:00+08:00")
    load(store, "RESOURCE_SHORTAGE")
    assert store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"
    assert store.dispatch_due("ui-check")[0]["reason"] == "SAME_INCIDENT_MERGED"
    closed, close_input = handle(store, "close")
    assert closed["state"] == "CLOSED"
    assert api.execute("BOSS", "close", close_input) == closed
    assert ControlStore(store.path).dispatch_due("ui-check")[0]["reason"] == "BOSS_CLOSED"
    with store.connect() as db:
        assert store.get(db, "ui-check", "event", closed["event_id"])["state"] == "OPEN"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='business_alert_action'").fetchone()[0] == 3


def test_recovery_has_independent_record_and_recurrence_obeys_cooldown(store):
    rules(store)
    configure(store)
    for minute in (0, 5, 10):
        clock(store, f"2026-10-22T09:{minute:02}:00+08:00")
        load(store)
        store.dispatch_due("ui-check")
    for minute in (15, 20, 25):
        clock(store, f"2026-10-22T09:{minute}:00+08:00")
        load(store, "RECOVERY")
        result = store.dispatch_due("ui-check")[0]
    assert result["reason"] == "RECOVERY_RECORDED_WITHOUT_NOTIFICATION"
    assert len(view(store)["recovery_history"]) == 1
    for minute in (26, 31, 36):
        clock(store, f"2026-10-22T09:{minute}:00+08:00")
        load(store)
        result = store.dispatch_due("ui-check")[0]
    assert result["reason"] == "COOLDOWN"
    clock(store, "2026-10-22T09:41:00+08:00")
    load(store)
    assert store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"


def test_source_withdrawal_invalidates_current_adoption_and_close_remains_possible(store):
    ready(store)
    before = view(store)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    current = view(store)
    assert current["adoption_state"] == "NEEDS_REVIEW" and current["facts"] is None
    assert current["documents"] == []
    assert store.dispatch_due("ui-check")[0]["reason"] == "SOURCE_NOT_CURRENT"
    with pytest.raises(web.HTTPConflict):
        BusinessAlertsAPI(store).execute("BOSS", "ack", {"client_request_id": "fc04-stale-source-decision", "event_id": before["event_id"],
            "event_version": before["event_version"], "expected_version": before["reminder_version"], "review_sha256": before["review_sha256"]})
    assert handle(store, "close")[0]["state"] == "CLOSED"


def test_derived_report_search_and_morning_source_stop_when_original_is_withdrawn(store):
    from boss_morning import MorningAPI
    from boss_source_access import require_current_business_source
    from boss_simulation_api import SimulationAPI
    ready(store)
    assert store.control("ui-check", "search", {"query": "SIMULATED"})["results"]
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    assert store.control("ui-check", "search", {"query": "SIMULATED"})["results"] == []
    report = SimulationAPI(store).query("BOSS", {"interface_id": "SI13", "object_ids": ["fc04-observation:business-alert-1"], "filters": {}})["records"][0]
    assert report["content_state"] == "NEEDS_REVIEW" and report["data"] is None
    with store.connect() as db, pytest.raises(web.HTTPConflict):
        require_current_business_source(store, db, "ui-check", "boss-1", "fc04-observation:business-alert-1")
    morning = MorningAPI(store)
    saved = morning.query("BOSS", {"client_request_id": "fc04-current-morning-after-withdraw", "session_id": "fc04-source-check", "date": "2026-10-22", "timezone": "Asia/Shanghai"})
    with pytest.raises(web.HTTPForbidden):
        morning.source("BOSS", saved["list_id"], "fc04-observation:business-alert-1")


def test_meeting_link_and_assignment_use_existing_objects_and_independent_send(store):
    from test_boss_command_api import send_input
    ready(store)
    current = view(store)
    linked, _ = handle(store, "meeting.link", **{field: current["meeting_reference"][field] for field in ("meeting_id",)}, meeting_version=current["meeting_reference"]["version"])
    assert linked["meeting_arranged"] is False
    created, payload = handle(store, "assignment.create", purpose="核查当前毛利变化与资源条件", coordinator_id="coordinator-1", due_at="2026-10-24T17:00:00+08:00", timezone="Asia/Shanghai", evidence_requirements=["原始经营明细及资源措施"])
    assert created["task_status"] == "OPEN" and created["external_message_sent"] is False
    assert BusinessAlertsAPI(store).execute("BOSS", "assignment.create", payload) == created
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", created["task_id"])
        assert task["related_event_ids"] == [current["event_id"]]
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
    code, sent = BossCommandAPI(store).execute("BOSS", "boss.assignment.send", send_input({"task_id": created["task_id"], "version": created["task_version"]}))
    assert code == 200, sent
    assert view(store)["existing_measures"][0]["status"] == "WAITING_FEEDBACK"


@pytest.mark.parametrize("role,error", [(None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden), ("boss-1", web.HTTPUnauthorized)])
def test_private_read_decisions_and_model_confirmation_injection_are_rejected(store, role, error):
    ready(store)
    api, current = BusinessAlertsAPI(store), view(store)
    payload = {"client_request_id": "fc04-scope-injection", "event_id": current["event_id"], "event_version": current["event_version"], "expected_version": current["reminder_version"], "review_sha256": current["review_sha256"]}
    with pytest.raises(error):
        api.read(role)
    with pytest.raises(error):
        api.execute(role, "ack", payload)
    with pytest.raises(error):
        api.receipt(role, "ack", payload["client_request_id"])
    for field in ("confirmed", "owner_id", "namespace", "authorization_id"):
        with pytest.raises(web.HTTPBadRequest):
            api.execute("BOSS", "ack", {**payload, field: True})


def test_concurrent_decisions_commit_once_and_do_not_replay_unknown_requests(store):
    from concurrent.futures import ThreadPoolExecutor
    ready(store)
    api, current = BusinessAlertsAPI(store), view(store)
    payload = {"event_id": current["event_id"], "event_version": current["event_version"], "expected_version": current["reminder_version"], "review_sha256": current["review_sha256"]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(api.execute, "BOSS", "ack", {**payload, "client_request_id": "fc04-concurrent-" + suffix}) for suffix in ("a", "b")]
    assert sum(future.exception() is None for future in futures) == 1
    assert all(future.exception() is None or isinstance(future.exception(), web.HTTPConflict) for future in futures)
    assert api.receipt("BOSS", "ack", "fc04-unknown-request")["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"


def test_legacy_reminder_entry_cannot_skip_business_review(store):
    ready(store)
    current = view(store)
    code, result = BossCommandAPI(store).execute("BOSS", "boss.reminder.ack", {"client_request_id": "fc04-legacy-review-bypass", "event_id": current["event_id"], "event_version": current["event_version"], "reminder_version": current["reminder_version"]})
    assert code == 409, result


@pytest.mark.parametrize("action,expected", [("pause", "OWNER_PLAN_PAUSED"), ("cancel", "OWNER_PLAN_CANCELED")])
def test_paused_or_canceled_owner_plan_stops_queued_and_reopened_dispatch(store, action, expected):
    from boss_owner_plans import OwnerPlansAPI
    ready(store)
    plans = OwnerPlansAPI(store)
    saved = plans.execute("BOSS", "save", {"client_request_id": "fc04-followup-plan", "plan_id": "", "expected_version": "0", "purpose": "本人复查当前经营提醒",
        "event_ids": [view(store)["event_id"]], "timezone": "Asia/Shanghai", "not_before": "2026-10-22T09:01:00+08:00"})
    plans.execute("BOSS", action, {"client_request_id": "fc04-plan-" + action, "plan_id": saved["plan_id"], "expected_version": saved["version"]})
    clock(store, "2026-10-22T09:30:00+08:00")
    load(store, "RESOURCE_SHORTAGE")
    assert ControlStore(store.path).dispatch_due("ui-check")[0]["reason"] == expected


def test_revoked_snooze_and_rule_authority_stop_future_adoption(store):
    ready(store)
    snoozed, _ = handle(store, "snooze", until="2026-10-22T09:30:00+08:00")
    before = view(store)
    commands = BossCommandAPI(store)
    assert commands.execute("BOSS", "boss.authorization.revoke", {"client_request_id": "fc04-revoke-snooze", "authorization_id": snoozed["authorization_id"], "expected_version": "1", "reason": "停止后续提醒采用"})[0] == 200
    with pytest.raises(web.HTTPConflict):
        BusinessAlertsAPI(store).execute("BOSS", "snooze", {"client_request_id": "fc04-old-reconfirmation", "event_id": before["event_id"], "event_version": before["event_version"],
            "expected_version": before["reminder_version"], "review_sha256": before["review_sha256"], "until": "2026-10-22T09:40:00+08:00"})
    clock(store, "2026-10-22T09:30:00+08:00")
    load(store, "RESOURCE_SHORTAGE")
    assert store.dispatch_due("ui-check")[0]["reason"] == "REMINDER_AUTHORIZATION_REVOKED"
    configure(store, "BOSS")
    active = BusinessAlertRulesAPI(store).read("BOSS")["active"]
    assert commands.execute("BOSS", "boss.authorization.revoke", {"client_request_id": "fc04-revoke-rule", "authorization_id": active["authorization_id"], "expected_version": "1", "reason": "停止当前关注规则"})[0] == 200
    assert store.dispatch_due("ui-check")[0]["reason"] == "RULE_AUTHORIZATION_REVOKED"


def test_canceled_event_cannot_reactivate_and_snooze_rejects_past_time(store):
    ready(store)
    with pytest.raises(web.HTTPBadRequest):
        handle(store, "snooze", until="2026-10-22T08:59:00+08:00")
    clock(store, "2026-10-22T09:05:00+08:00")
    load(store, "CANCELED")
    assert store.dispatch_due("ui-check")[0]["reason"] == "SOURCE_CANCELED"
    clock(store, "2026-10-22T09:10:00+08:00")
    with pytest.raises(web.HTTPConflict):
        load(store, "RESOURCE_SHORTAGE")


def test_existing_cron_executes_the_same_dispatcher_and_persists_disabled_job(store, tmp_path):
    import asyncio
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronSchedule
    rules(store)
    configure(store)
    load(store, "RESOURCE_SHORTAGE")

    async def run():
        fired = asyncio.Event()
        observed = []

        async def callback(job):
            observed.extend(ControlStore(store.path).dispatch_due("ui-check"))
            fired.set()
            return "FC04实际SQLite调度完成"

        cron_path = tmp_path / "cron" / "jobs.json"
        service = CronService(cron_path, on_job=callback, max_sleep_ms=20)
        await service.start()
        try:
            job = service.add_job("FC04经营提醒", CronSchedule(kind="every", every_ms=50), "核查已启用规则与当前获准事件", session_key="ui-check", origin_channel="websocket", origin_chat_id="fc04-check")
            await asyncio.wait_for(fired.wait(), 5)
            service.enable_job(job.id, False)
        finally:
            service.stop()
        assert observed[0]["state"] == "DELIVERED"
        restarted = CronService(cron_path, on_job=callback, max_sleep_ms=20)
        await restarted.start()
        try:
            assert next(item for item in restarted.list_jobs(include_disabled=True) if item.id == job.id).enabled is False
            assert ControlStore(store.path).dispatch_due("ui-check")[0]["reason"] == "SAME_INCIDENT_MERGED"
        finally:
            restarted.stop()

    asyncio.run(run())


def test_schema_is_valid_and_maintenance_cannot_inject_subject_or_business_values(store):
    from jsonschema import Draft202012Validator
    from boss_alert_policy import SCHEMA
    Draft202012Validator.check_schema(SCHEMA)
    payload = {"client_request_id": "fc04-invalid-generated-values", "expected_version": "0", "mode": "SIMULATED", "definition_version": "FC04-ALERT-1", "seed": 20261024, "frame": "MARGIN_DROP"}
    for field in ("owner_id", "namespace", "current_value", "authorization_id"):
        with pytest.raises(web.HTTPBadRequest):
            BusinessAlertInputAPI(store).load("MAINTAINER", {**payload, field: "forged"})
    with pytest.raises(web.HTTPForbidden):
        BusinessAlertInputAPI(store).load("BOSS", payload)


def test_meeting_source_change_requires_current_review_and_source_qualification(store):
    ready(store)
    current = view(store)
    store.control("ui-check", "withdraw", {"source_id": "meeting-minutes", "version": "1"})
    assert view(store)["meeting_reference"]["adoption_state"] == "NEEDS_REVIEW"
    with pytest.raises(web.HTTPConflict):
        handle(store, "meeting.link", meeting_id=current["meeting_reference"]["meeting_id"], meeting_version=current["meeting_reference"]["version"])
    assert view(store)["facts"] is not None


def test_current_handler_and_original_request_receipts_remain_explicit(store):
    rules(store)
    configured = configure(store)
    assert BusinessAlertRulesAPI(ControlStore(store.path)).receipt("MAINTAINER", "activate", "fc04-rule-activate-1")["result"] == configured
    clock(store, "2027-01-01T16:30:00+00:00")
    load(store, "RESOURCE_SHORTAGE")
    assert store.dispatch_due("ui-check")[0]["reason"] == "HANDLER_NOT_CURRENT"
    api = BusinessAlertsAPI(store)
    with store.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPForbidden):
            store.require_current_coordinator(db, "ui-check", store.get(db, "ui-check", "initial", "snapshot"), "coordinator-1")
        projected = api.project_in_transaction("BOSS", db)
    assert projected == api.read("BOSS")
    with pytest.raises(web.HTTPNotFound):
        api.read("BOSS", "event-1")


def test_closed_state_and_zero_new_business_actions_survive_independent_process(store):
    import json
    import os
    import subprocess
    ready(store)
    handle(store, "close")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "validation/check_fc04_restart.py"), "--database", str(store.path)],
        cwd=root, check=True, capture_output=True, text=True)
    observed = json.loads(result.stdout)
    assert observed["status"] == "PASS" and observed["pid"] != os.getpid()
    assert observed["new_business_actions"] == 0
    assert observed["backup"] == "VERIFIED_FIVE_TABLES"


def test_recurrence_can_create_a_new_task_while_current_incident_has_only_one(store):
    ready(store)
    fields = {"purpose": "核查当前经营与资源条件", "coordinator_id": "coordinator-1", "due_at": "2026-10-24T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["原始明细及当前措施"]}
    first, _ = handle(store, "assignment.create", key="fc04-first-incident-task", **fields)
    with pytest.raises(web.HTTPConflict):
        handle(store, "assignment.create", key="fc04-duplicate-incident-task", **fields)
    for minute in (5, 10, 15):
        clock(store, f"2026-10-22T09:{minute:02}:00+08:00")
        load(store, "RECOVERY")
        store.dispatch_due("ui-check")
    clock(store, "2026-10-22T09:30:00+08:00")
    load(store, "RESOURCE_SHORTAGE")
    assert store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"
    second, _ = handle(store, "assignment.create", key="fc04-next-incident-task", **fields)
    assert first["task_id"] != second["task_id"]
    assert len(view(store)["assignment_references"]) == 2
