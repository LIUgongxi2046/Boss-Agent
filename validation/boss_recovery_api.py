"""Read-only business outcome reconciliation and privacy-safe share preview.

This is *not* a retry or an additional authorization. The client can query
the original idempotency receipt after a timeout; absence is an UNKNOWN
outcome, never proof that no side effect occurred. Status is derived from
SQLite, not a client-supplied success flag. Strict role gates and allowlisted
response fields keep private text out of these routes.
"""
from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qs

from aiohttp import web

from boss_command_api import BossCommandAPI, _client_key, _aware_due
from boss_message_calendar import work_meeting_conflict
from boss_meetings import meeting_materials
from business import now

from boss_execution_scope import NAMESPACE as NS
from boss_calendar_state import current_calendar
SAFE_RECEIPT_FIELDS = {
    "source_type", "draft_id", "draft_version", "message_id",
    "recipient_id", "send_state", "delivery_state", "reply_state",
    "external_channel_invoked", "status", "state", "decision", "version", "calendar_id",
    "share_id", "share_status", "fields", "active_shares_invalidated",
    "external_delivery_created", "external_recall_verified",
    "future_visibility_stopped", "task_id", "task_status_after_reply",
    "task_feedback_id", "feedback_id", "task_completion_confirmed", "confirmation_state",
    "minute_id", "minute_version", "entry_id", "meeting_id",
    "independent_send_required", "message_sent",
    "application_id", "decision_id",
    "commitment_id", "external_message_sent", "due_at", "event_id", "event_version", "until",
    "authorization_id", "run_id", "memory_id", "object_id", "index_state", "withdrawn",
    "plan_id", "date", "item_ids",
    "meeting_version", "review_sha256", "meeting_changed", "invitation_sent", "independent_tasks_unchanged",
    "historical_only",
    "task_status", "assignment_authorization_id", "meeting_arranged", "business_authorization_granted", "external_service_invoked", "definition_version", "source_id", "source_version",
    "task_version", "sources_reconfirmed", "business_status_unchanged", "result_evidence_requires_resubmission",
}


def calendar_share_state(share, calendar, clock):
    if share.get("revoked") is True:
        return "REVOKED"
    if calendar is None:
        return "OUTDATED"
    if calendar.get("status", "ACTIVE") != "ACTIVE" or (
        share.get("calendar_version") != calendar.get("version")
    ):
        return "OUTDATED"
    try:
        valid_until = datetime.fromisoformat(share["expires_at"])
        current = datetime.fromisoformat(clock["at"])
        if valid_until <= current:
            return "EXPIRED"
    except (KeyError, TypeError, ValueError):
        return "INVALID"
    return "ACTIVE_SIMULATED"


def _query(query_string, required):
    params = parse_qs(query_string, keep_blank_values=True)
    if set(params) != set(required) or any(len(params[name]) != 1 for name in required):
        raise web.HTTPBadRequest(text="查询标识缺少或重复")
    return {key: params[key][0] for key in required}


class BossRecoveryAPI:
    def __init__(self, store, namespace=NS):
        self.store, self.namespace = store, namespace

    def serve(self, role, path, query_string=""):
        if role not in ("BOSS", "MAINTAINER"):
            return 401, {"error": "UNAUTHENTICATED"}
        if path == "/api/boss/ui/calendar-conflict":
            if role != "BOSS":
                return 403, {"error": "FORBIDDEN"}
            params = _query(query_string, ("starts_at", "ends_at", "timezone"))
            start = _aware_due(params["starts_at"], params["timezone"])
            end = _aware_due(params["ends_at"], params["timezone"])
            if not start < end or (end - start).total_seconds() > 31 * 86400:
                return 400, {"error": "INVALID_TIME_WINDOW"}
            with self.store.connect() as db:
                self.store.active(db, self.namespace)
                data = meeting_materials(db, self.store.get(db, self.namespace, "initial", "snapshot"))
                meeting = data["meeting"]
                observed = work_meeting_conflict(
                    start, end, datetime.fromisoformat(meeting["starts_at"]),
                    datetime.fromisoformat(meeting["ends_at"]) if meeting.get("ends_at") else None,
                    meeting.get("state", "DRAFT"),
                )
                return 200, {
                    "source_type": "SIMULATED",
                    "calendar_id": "private-1",
                    "meeting_id": meeting["meeting_id"],
                    "meeting_version": meeting["version"],
                    "timezone": params["timezone"],
                    "proposed_starts_at": params["starts_at"],
                    "proposed_ends_at": params["ends_at"],
                    **observed,
                    "read_only": True,
                    "read_at": now(),
                }
        if path == "/api/boss/ui/operation-status":
            params = _query(query_string, ("action", "client_request_id"))
            action = params["action"]
            required = BossCommandAPI.ACTION_ROLES.get(action)
            if required is None:
                return 404, {"error": "UNKNOWN_ACTION"}
            if required != role:
                return 403, {"error": "FORBIDDEN"}
            key = _client_key(params["client_request_id"])
            if action == "boss.simulation.alert.load" or action.startswith(("boss.alert.", "boss.simulation.alert.rule.")):
                if self.namespace != NS:
                    return 409, {"error": "EXECUTION_SCOPE_UNAVAILABLE"}
                if action == "boss.simulation.alert.load":
                    from boss_alert_rules import BusinessAlertInputAPI
                    receipt = BusinessAlertInputAPI(self.store).receipt(role, key)
                elif action.startswith(("boss.alert.rule.", "boss.simulation.alert.rule.")):
                    from boss_alert_rules import BusinessAlertRulesAPI
                    receipt = BusinessAlertRulesAPI(self.store).receipt(role, action.rsplit(".", 1)[-1], key)
                else:
                    from boss_business_alerts import BusinessAlertsAPI
                    receipt = BusinessAlertsAPI(self.store).receipt(role, action.removeprefix("boss.alert."), key)
                return 200, {"source_type": "SIMULATED", **receipt, "write_performed_by_lookup": False}
            if action == "boss.assignment.extension.decide":
                if self.namespace != NS:
                    return 409, {"error": "EXECUTION_SCOPE_UNAVAILABLE"}
                from boss_assignment_extensions import AssignmentExtensionAPI
                return 200, {**AssignmentExtensionAPI(self.store).receipt(role, key), "write_performed_by_lookup": False}
            with self.store.connect() as db:
                self.store.active(db, self.namespace)
                found = db.execute(
                    "SELECT result FROM idempotency WHERE namespace=? "
                    "AND operation=? AND key=?",
                    (self.namespace, action, key),
                ).fetchone()
                if found is None:
                    return 200, {
                        "source_type": "SIMULATED", "action": action,
                        "client_request_id": key,
                        "outcome": "NOT_FOUND_IN_CURRENT_STORE",
                        "not_proof_of_failed_delivery": True,
                        "safe_same_key_retry": True,
                        "write_performed_by_lookup": False,
                        "read_at": now(),
                    }
                result = json.loads(found[0])
                if action.startswith(("boss.technical.", "boss.owner_workspace.")):
                    result = result["result"]
                safe = {
                    field: val for field, val in result.items()
                    if field in SAFE_RECEIPT_FIELDS
                    and isinstance(val, (str, bool, int, float, type(None), list))
                }
                if action == "boss.simulation.feedback" and isinstance(result.get("task"), dict):
                    task = result["task"]
                    safe.update({field: task[source] for field, source in (("task_id", "task_id"), ("task_version", "version"), ("task_status_after_reply", "status")) if isinstance(task.get(source), str)})
                return 200, {
                    "source_type": "SIMULATED", "action": action,
                    "client_request_id": key, "outcome": "RECORDED",
                    "result": safe, "write_performed_by_lookup": False,
                    "read_at": now(),
                }
        if path == "/api/boss/ui/calendar-share-preview":
            if role != "BOSS":
                return 403, {"error": "FORBIDDEN"}
            params = _query(query_string, ("share_id",))
            share_id = params["share_id"]
            if not share_id.startswith("busy-share-") or len(share_id) > 100:
                return 400, {"error": "INVALID_SHARE_ID"}
            with self.store.connect() as db:
                self.store.active(db, self.namespace)
                row = db.execute(
                    "SELECT body FROM objects WHERE namespace=? AND kind='calendar_share' AND id=?",
                    (self.namespace, share_id),
                ).fetchone()
                if row is None:
                    return 404, {"error": "SHARE_NOT_FOUND"}
                share = json.loads(row[0])
                data = self.store.get(db, self.namespace, "initial", "snapshot")
                calendar = current_calendar(db, self.namespace, data)
                clock = self.store.get(db, self.namespace, "clock", "current")
                authorization = self.store.get(db, self.namespace, "authorization", share["authorization_id"])
                if authorization["revoked"]:
                    return 410, {"error": "SHARE_INACTIVE", "share_status": "AUTHORIZATION_REVOKED"}
                status = calendar_share_state(share, calendar, clock)
                if status != "ACTIVE_SIMULATED":
                    return 410, {"error": "SHARE_INACTIVE", "share_status": status}
                return 200, {
                    "source_type": "SIMULATED",
                    "share_id": share_id, "share_status": status,
                    "recipient_id": share["recipient_id"],
                    "fields": ["busy", "starts_at", "ends_at", "timezone"],
                    "busy": True,
                    "starts_at": share["starts_at"],
                    "ends_at": share["ends_at"],
                    "timezone": share["timezone"],
                    "external_delivery_created": False,
                    "preview_only_not_external_access": True,
                    "read_at": now(),
                }
        return 404, {"error": "API_NOT_FOUND"}
