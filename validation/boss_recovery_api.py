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
from business import now

NS = "ui-check"
SAFE_RECEIPT_FIELDS = {
    "source_type", "draft_id", "draft_version", "message_id",
    "recipient_id", "send_state", "delivery_state", "reply_state",
    "external_channel_invoked", "status", "version", "calendar_id",
    "share_id", "share_status", "fields", "active_shares_invalidated",
    "external_delivery_created", "external_recall_verified",
    "future_visibility_stopped", "task_id", "task_status_after_reply",
    "task_feedback_id", "task_completion_confirmed", "confirmation_state",
    "minute_id", "meeting_id", "application_id", "decision_id",
    "authorization_id",
}


def calendar_share_state(share, calendar, clock):
    if share.get("revoked") is True:
        return "REVOKED"
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
                data = self.store.get(db, self.namespace, "initial", "snapshot")
                meeting = data["meeting"]
                observed = work_meeting_conflict(
                    start, end, datetime.fromisoformat(meeting["starts_at"]),
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
                safe = {
                    field: val for field, val in result.items()
                    if field in SAFE_RECEIPT_FIELDS
                    and isinstance(val, (str, bool, int, float, type(None), list))
                }
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
                saved = db.execute(
                    "SELECT body FROM objects WHERE namespace=? AND kind='private_calendar' AND id='private-1'",
                    (self.namespace,),
                ).fetchone()
                data = self.store.get(db, self.namespace, "initial", "snapshot")
                calendar = json.loads(saved[0]) if saved else {
                    **data["private_calendar"], "version": "1", "status": "ACTIVE",
                }
                clock = self.store.get(db, self.namespace, "clock", "current")
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
