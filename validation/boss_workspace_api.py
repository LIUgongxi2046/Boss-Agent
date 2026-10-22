"""Role-scoped Boss-Agent workspace projections.

Read-only, server-owned projections of *actual* selection data. These power the
next Desktop v6 implementation slice; empty data stays empty, with source,
version and coverage in response. No fake departmental users or inferred ROI.

Endpoints are deliberately under the authenticated RoleChannel gateway.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

from aiohttp import web

from business import OPERATIONS, ROOT, now
from boss_meeting_brief import briefing_projection
from boss_recovery_api import calendar_share_state

NS = "ui-check"
BOSS_PAGES = {
    "memory", "calendar", "notifications", "authorizations", "decisions",
    "outbox", "sources", "knowledge", "organization", "plans", "voice",
    "minutes", "approvals", "briefing",
}
MAINT_PAGES = {
    "dataset", "source-index", "tool-catalog", "metric-definitions",
    "relationships", "scheduler", "audit", "system", "evaluation", "approval-admin", "message-admin",
}


def _object_list(db, namespace, kind, limit=100):
    require = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id LIMIT ?",
        (namespace, kind, limit),
    ).fetchall()
    return [json.loads(row[0]) for row in require]


def _safe_date(raw):
    return raw if isinstance(raw, str) and len(raw) <= 64 else None


def _safe_source(entry):
    return {
        "source_id": entry.get("source_id"),
        "source_type": entry.get("source_type"),
        "version": entry.get("version"),
        "author_contact_id": entry.get("author_contact_id"),
        "published_at": entry.get("published_at"),
        "withdrawn": bool(entry.get("withdrawn")),
        "access_scope": "BOSS_ONLY" if entry.get("access_scope") == "boss-1" else "NOT_AUTHORIZED",
        "content_visible": False,
    }


class BossWorkspaceAPI:
    def __init__(self, store, namespace=NS):
        self.store = store
        self.namespace = namespace

    def serve(self, role, path, query_string=""):
        prefix = "/api/boss/ui/workspace/"
        if not isinstance(path, str) or not path.startswith(prefix):
            return 404, {"error": "API_NOT_FOUND"}
        key = path[len(prefix):]
        if "/" in key or not key:
            return 404, {"error": "API_NOT_FOUND"}
        if role not in ("BOSS", "MAINTAINER"):
            return 401, {"error": "UNAUTHENTICATED"}
        allowed = BOSS_PAGES if role == "BOSS" else MAINT_PAGES
        if key not in allowed:
            return 403, {"error": "FORBIDDEN"}
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            data = self.store.get(db, self.namespace, "initial", "snapshot")
            output = self._read(db, data, key, role, query_string)
        output["read_at"] = now()
        output["source_type"] = "SIMULATED"
        output["namespace"] = self.namespace
        output["data_version"] = data["dataset_version"]
        output["projection"] = key
        return 200, output

    def _read(self, db, data, key, role, query_string):
        if key == "voice":
            # Fixed local runtime configuration, never client-selected paths
            # or the raw Provider secret/transport state.
            runtime_config = ROOT / ".work" / "application" / "config.json"
            enabled = False
            max_duration = 120
            provider = "NOT_CONFIGURED"
            if runtime_config.is_file() and runtime_config.stat().st_size < 65536:
                settings = json.loads(runtime_config.read_text(encoding="utf-8"))
                transcription = settings.get("transcription", {})
                if isinstance(transcription, dict):
                    enabled = transcription.get("enabled") is True
                    max_duration = transcription.get("maxDurationSec", 120)
                    provider = transcription.get("provider") or "DEFAULT_NOT_VERIFIED"
            return {
                "transcription_enabled_in_saved_config": enabled,
                "transcription_provider_label": provider,
                "max_duration_seconds": max_duration,
                "connection_or_credentials_verified": False,
                "recording_is_local_until_explicit_send": True,
                "transcription_result_status": "NOT_EXECUTED",
                "transcription_input_mime": "audio/webm",
            }
        if key == "briefing":
            return briefing_projection(db,data)
        if key == "minutes":
            meeting = data["meeting"]
            item = db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='minutes' AND id=?",
                (self.namespace, meeting["meeting_id"]),
            ).fetchone()
            minute = json.loads(item[0]) if item else None
            current_sources = {
                d["source_id"]: d for d in _object_list(db, self.namespace, "document")
            }
            associated = [
                _safe_source(current_sources[source_id])
                for source_id in meeting["material_ids"]
                if source_id in current_sources
            ]
            revisions = _object_list(db, self.namespace, "minutes_revision")
            history = [
                {"version": row["version"], "state": row["state"],
                 "source_version": row["source_version"],
                 "updated_at": row.get("updated_at")}
                for row in revisions if row["meeting_id"] == meeting["meeting_id"]
            ]
            linked = []
            for link in _object_list(db, self.namespace, "minutes_assignment_link"):
                if link["meeting_id"] != meeting["meeting_id"]:
                    continue
                task = self.store.get(db, self.namespace, "task", link["task_id"])
                linked.append({
                    "minute_id": link["minute_id"],
                    "minute_version": link["minute_version"],
                    "entry_id": link["entry_id"],
                    "task_id": link["task_id"],
                    "task_status": task["status"],
                    "task_version": task["version"],
                    "send_status": "SENT_SIMULATED" if task.get("message_ids")
                                   else "NOT_SENT",
                    "sent_message_count": len(task.get("message_ids", [])),
                    "authorization_id": link["authorization_id"],
                    "source_id": link["source_id"],
                    "source_version": link["source_version"],
                })
            return {
                "meeting": {
                    "meeting_id": meeting["meeting_id"], "version": meeting["version"],
                    "starts_at": meeting["starts_at"], "timezone": meeting["timezone"],
                    "participant_ids": meeting["participant_ids"],
                },
                "minute": minute,
                "source_index": associated, "revisions": history,
                "linked_assignments": linked,
                "task_created_by_minutes": bool(linked),
                "message_sent_by_minutes": any(
                    item["sent_message_count"] > 0 for item in linked
                ),
            }
        if key == "approvals" or key == "approval-admin":
            apps = _object_list(db, self.namespace, "application")
            documents = {d["source_id"]: d for d in _object_list(
                db, self.namespace, "document"
            )}
            output = []
            for app in apps:
                doc = documents.get(app["source_id"])
                summary = {
                    k: app[k] for k in (
                        "application_id", "title", "amount", "currency", "version",
                        "source_id", "source_version", "state", "created_at",
                        "applicant_contact_id", "decision_id", "source_type",
                    ) if k in app
                }
                summary["attachment_status"] = (
                    "WITHDRAWN" if doc and doc.get("withdrawn") else
                    "CURRENT" if doc and doc.get("version") == app["source_version"]
                    else "MISSING_OR_CHANGED"
                )
                if key == "approvals":
                    summary["description"] = app["description"]
                    summary["funds_transferred"] = bool(app.get("funds_transferred", False))
                    summary["professional_release_issued"] = bool(app.get("professional_release_issued", False))
                output.append(summary)
            if key == "approval-admin":
                return {
                    "applications": output,
                    "eligible_applicant_contact_ids": [
                        c["contact_id"] for c in data["contacts"]
                        if c["contact_id"] != "contact-2"
                    ],
                    "can_seed_simulation": True,
                    "can_approve_on_behalf_of_owner": False,
                    "private_decision_comments_returned": False,
                }
            decisions = _object_list(db, self.namespace, "application_decision")
            return {
                "applications": output,
                "decisions": [{
                    k: row[k] for k in (
                        "decision_id", "application_id", "application_version",
                        "source_id", "source_version", "amount", "currency",
                        "action", "comment", "recorded_at", "authorization_id",
                    ) if k in row
                } for row in decisions],
                "actual_funds_transfer_supported": False,
            }
        if key == "memory":
            current = self.store.get(db, self.namespace, "memory", "current")
            return {
                "memory": {
                    "memory_id": current.get("memory_id"),
                    "version": current["version"],
                    "confirmation_state": current["confirmation_state"],
                    "text": current.get("text", "") if current["confirmation_state"] == "CONFIRMED" else "",
                },
                "effective": current["confirmation_state"] == "CONFIRMED",
                "future_turn_policy": "CONFIRMED_ONLY",
                "physical_secure_erasure_verified": False,
            }
        if key == "calendar":
            row = db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='private_calendar' AND id='private-1'",
                (self.namespace,),
            ).fetchone()
            calendar = json.loads(row[0]) if row else {
                **data["private_calendar"], "version": "1", "status": "ACTIVE",
                "title": "", "location": "", "attachment_refs": [],
            }
            shares = _object_list(db, self.namespace, "calendar_share")
            clock = self.store.get(db, self.namespace, "clock", "current")
            return {
                "calendar": calendar,
                "shares": [{
                    **{k: share[k] for k in (
                        "share_id", "calendar_version", "recipient_id",
                        "busy", "starts_at", "ends_at", "timezone", "expires_at",
                        "revoked", "revoked_at", "external_delivery_created",
                    ) if k in share},
                    "effective_state": calendar_share_state(share, calendar, clock),
                } for share in shares],
                "contacts": [{
                    "contact_id": c["contact_id"], "name": c["name"],
                    "organization": c["organization"],
                    "responsibility": c["responsibility"],
                } for c in data["contacts"]],
                "meeting": {
                    "meeting_id": data["meeting"]["meeting_id"],
                    "starts_at": data["meeting"]["starts_at"],
                    "ends_at": None, "end_is_known": False,
                },
                "visibility": "BOSS_PRIVATE",
                "external_share_created": False,
                "can_edit": calendar["status"] != "DELETED",
                "physical_secure_erasure_verified": False,
            }
        if key == "sources" or key == "source-index":
            docs = _object_list(db, self.namespace, "document")
            records = [_safe_source(d) for d in docs]
            if role == "MAINTAINER":
                records = [{k: v for k, v in d.items() if k not in
                            ("author_contact_id",)} for d in records]
            return {"sources": records, "count": len(records),
                    "original_body_available_here": False}
        if key == "knowledge":
            params = parse_qs(query_string, keep_blank_values=True)
            phrase = params.get("q", [""])[0].strip()[:100]
            # Use the original approved documents index, no public search.
            documents = _object_list(db, self.namespace, "document")
            matches = []
            for document in documents:
                if document.get("withdrawn") or document.get("access_scope") != data["owner_id"]:
                    continue
                if phrase and phrase.casefold() not in document.get("content", "").casefold():
                    continue
                matches.append({
                    "source_id": document["source_id"], "source_type": document["source_type"],
                    "version": document["version"], "author_contact_id": document["author_contact_id"],
                    "published_at": document.get("published_at"),
                    "excerpt": document.get("content", "")[:240],
                })
            return {"query": phrase, "results": matches[:20],
                    "coverage": "approved_simulated_documents_only",
                    "external_web_search_performed": False}
        if key == "organization":
            contacts = data.get("contacts", [])
            meeting = data.get("meeting")
            return {"contacts": [
                {"contact_id": c["contact_id"], "name": c["name"],
                 "organization": c["organization"], "responsibility": c["responsibility"],
                 "valid_from": c.get("valid_from"), "valid_until": c.get("valid_until")}
                for c in contacts
            ], "meeting": meeting,
            "contact_login_count": 0, "employee_accounts_created": False}
        if key == "plans":
            schedule = self.store.get(db, self.namespace, "schedule", "current")
            clock = self.store.get(db, self.namespace, "clock", "current")
            return {"schedule": {k: schedule.get(k) for k in (
                "schedule_id", "schedule_version", "version", "timezone",
                "enabled", "canceled", "trigger")},
                "business_clock": clock["at"],
                "owner_plan_events": [],
                "plan_event_tracking_implemented": False}
        if key == "notifications":
            events = _object_list(db, self.namespace, "event")
            sent = _object_list(db, self.namespace, "notification")
            reminders = _object_list(db, self.namespace, "reminder")
            deliveries = _object_list(db, self.namespace, "delivery")
            rules = _object_list(db, self.namespace, "rules")
            return {
                "events": [{k: row[k] for k in (
                    "event_id", "version", "state", "impact", "due_at", "task_id"
                ) if k in row} for row in events],
                "notifications": [{k: row[k] for k in (
                    "event_id", "event_version", "state", "reason",
                    "schedule_version", "created_at", "business_at", "source_type"
                ) if k in row} for row in sent],
                "reminders": reminders,
                "deliveries": [{k: row[k] for k in (
                    "event_id", "state", "reason", "delivered_at", "source_type"
                ) if k in row} for row in deliveries],
                "rules": [{
                    k: row.get(k) for k in (
                        "version", "cooldown_seconds", "quiet_start", "quiet_end",
                        "timezone", "important_escalation")
                } for row in rules],
                "count": len(sent), "notification_draft_only": len(sent) == 0,
            }
        if key == "authorizations":
            rows = _object_list(db, self.namespace, "authorization")
            return {"authorizations": [{
                k: row[k] for k in (
                    "authorization_id", "issuer_identity", "action", "target_id",
                    "content_version", "version", "revoked", "revoked_at",
                    "valid_from", "valid_until", "scope",
                ) if k in row
            } for row in rows], "secrets_or_payloads_returned": False}
        if key == "decisions":
            audit = db.execute(
                "SELECT id,operation,created_at,output FROM audit WHERE namespace=? "
                "AND operation IN ('boss.assignment.complete','boss.assignment.extend',"
                "'boss.assignment.cancel','boss.memory.confirm','boss.memory.delete',"
                "'boss.reminder.ack','boss.reminder.snooze','boss.reminder.close',"
                "'boss.minutes.confirm','boss.approval.decide') "
                "ORDER BY id DESC LIMIT 80",
                (self.namespace,),
            ).fetchall()
            entries = []
            for row in audit:
                try:
                    result = json.loads(row[3])
                except (TypeError, ValueError):
                    result = {}
                entries.append({
                    "sequence": row[0], "action": row[1], "at": row[2],
                    **{k: result[k] for k in (
                        "task_id", "meeting_id", "application_id", "decision_id",
                        "status", "version", "authorization_id",
                    ) if isinstance(result, dict) and k in result
                    and isinstance(result[k], (int, str))},
                })
            return {"history": entries, "raw_action_payload_returned": False}
        if key == "message-admin":
            # MAINTAINER gets technical identifiers only, never draft/body,
            # personal messages, attachment text or reply content.
            sent = _object_list(db, self.namespace, "message_outbox")
            return {
                "pending_reply_refs": [{
                    "message_id": row["message_id"],
                    "recipient_id": row["recipient_id"],
                    "send_state": row["send_state"],
                    "reply_state": row["reply_state"],
                    "related_task_id": row.get("related_task_id"),
                } for row in sent],
                "raw_message_text_returned": False,
                "contact_accounts_exist": False,
            }
        if key == "outbox":
            rows = _object_list(db, self.namespace, "outbox")
            drafts = _object_list(db, self.namespace, "message_draft")
            sent = _object_list(db, self.namespace, "message_outbox")
            replies = _object_list(db, self.namespace, "message_reply")
            return {
                "messages": [{k: r[k] for k in (
                    "message_id", "task_id", "message_status", "task_status",
                    "task_version", "recipient_id", "sent_at", "source_type",
                ) if k in r} for r in rows],
                "drafts": [dict(row) for row in drafts],
                "sent_messages": [{
                    k: row[k] for k in (
                        "message_id", "draft_id", "draft_version", "recipient_id",
                        "related_task_id", "body", "attachment_refs", "send_state",
                        "delivery_state", "reply_state", "sent_at", "source_type",
                        "external_channel_invoked",
                    ) if k in row
                } for row in sent],
                "replies": [{
                    k: row[k] for k in (
                        "reply_id", "reply_to", "author_contact_id",
                        "text", "source_type", "received_at",
                        "related_task_id", "task_completion_confirmed",
                    ) if k in row
                } for row in replies],
                "contacts": [{
                    k: row[k] for k in (
                        "contact_id", "name", "organization",
                        "responsibility", "valid_from", "valid_until",
                    ) if k in row
                } for row in data["contacts"]],
                "task_ids": [row["task_id"] for row in _object_list(
                    db, self.namespace, "task") if row.get("status") not in
                    ("CANCELED", "COMPLETED_CONFIRMED")],
                "body_exposed": True,
                "visibility": "BOSS_ONLY",
                "external_channel_invoked": False,
            }
        if key == "dataset":
            c = db.execute(
                "SELECT kind, COUNT(*) FROM objects WHERE namespace=? "
                "GROUP BY kind ORDER BY kind", (self.namespace,),
            ).fetchall()
            return {"dataset_id": data["dataset_id"], "version": data["dataset_version"],
                    "generator_version": data.get("generator_version"),
                    "seed": data.get("seed"), "object_counts": dict(c),
                    "business_periods": data["periods"],
                    "simulated_event_id": data["event"]["event_id"],
                    "owner_text_visible": False}
        if key == "tool-catalog":
            return {"operations": [
                {"operation_id": name, "input_schema": op["input_schema"],
                 "output_schema": op["output_schema"],
                 "source_type": "SIMULATED"}
                for name, op in OPERATIONS.items()
            ], "transport": "server_schema_checked", "external_tool_invoked": False}
        if key == "metric-definitions":
            return {"metric_definitions": data.get("metric_definitions", []),
                    "metric_version": "1", "calculation_owner": "Store.query_metrics",
                    "manual_overrides_allowed": False}
        if key == "relationships":
            return {"entity_counts": {
                "contacts": len(data.get("contacts", [])),
                "documents": len(data.get("documents", [])),
                "meetings": 1 if data.get("meeting") else 0,
                "historical_tasks": 1 if data.get("historical_task") else 0,
            }, "technical_links": {
                "meeting_id": data["meeting"]["meeting_id"],
                "event_id": data["event"]["event_id"],
            },
            "business_clock": self.store.get(db, self.namespace, "clock", "current")["at"],
            "owner_body_access": False}
        if key == "scheduler":
            schedule = self.store.get(db, self.namespace, "schedule", "current")
            clock = self.store.get(db, self.namespace, "clock", "current")
            return {"schedule": {k: schedule.get(k) for k in (
                    "schedule_id", "version", "schedule_version", "timezone",
                    "trigger", "enabled", "canceled"
                )},
                "simulated_business_time": clock["at"],
                "cron_runtime_verified_here": False}
        if key == "audit":
            rows = db.execute(
                "SELECT id,operation,created_at FROM audit WHERE namespace=? "
                "ORDER BY id DESC LIMIT 80", (self.namespace,),
            ).fetchall()
            return {"operations": [
                {"sequence": r[0], "operation": r[1], "created_at": r[2]}
                for r in rows
            ], "private_values_included": False}
        if key == "evaluation":
            contract_path = ROOT.parent / "specs" / "selection-probe.json"
            if not contract_path.is_file():
                raise web.HTTPServiceUnavailable(text="独立验证定义未安装")
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            return {
                "definition_id": contract["document_id"],
                "definition_version": contract["version"],
                "defined_step_count": len(contract["steps"]),
                "defined_assertion_count": len(contract["assertions"]),
                "steps": [
                    {"step_id": row["step_id"], "actor": row["actor"],
                     "action": row["action"]}
                    for row in contract["steps"][:30]
                ],
                "independent_product_evaluation_completed": False,
                "actual_score": None,
                "coverage": "T02_SELECTION_PROBE_DEFINITION_ONLY",
                "can_start_run_from_ui": False,
                "source_file": "specs/selection-probe.json",
            }
        if key == "system":
            rows = db.execute(
                "SELECT kind,COUNT(*) FROM objects WHERE namespace=? "
                "GROUP BY kind", (self.namespace,),
            ).fetchall()
            return {"namespace": self.namespace, "record_counts": dict(rows),
                    "installed_mac_app_verified": False,
                    "model_connection_verified_here": False,
                    "runtime_technical_checks": "CI_ONLY_NOT_MAC"}
        raise web.HTTPNotFound()
