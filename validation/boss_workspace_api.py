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
from boss_prompt_config import KINDS, active_runtime_prompts
from boss_research import project as research_projection
from boss_travel import projection as travel_projection
from boss_people import projection as people_projection
from boss_owner_preferences import goals_projection, notice_projection, effective_owner_notice
from boss_recovery_api import calendar_share_state
from boss_meetings import meeting_materials
from boss_memory import confirmed_memory, current_memory
from boss_calendar_state import current_calendar
from boss_owner_authorizations import authorization_can_revoke
from boss_source_policy import source_validity
from boss_supply_quality import external_adoption

from boss_execution_scope import NAMESPACE as NS
BOSS_PAGES = {
    "memory", "calendar", "notifications", "authorizations", "decisions",
    "outbox", "sources", "knowledge", "organization", "plans", "voice",
    "minutes", "approvals", "briefing", "research", "travel", "people",
    "owner-goals", "owner-notice",
}
MAINT_PAGES = {
    "dataset", "source-index", "tool-catalog", "metric-definitions",
    "relationships", "scheduler", "audit", "system", "evaluation", "approval-admin", "message-admin", "prompt-versions",
}


def _object_list(db, namespace, kind, limit=100):
    require = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id LIMIT ?",
        (namespace, kind, limit),
    ).fetchall()
    return [json.loads(row[0]) for row in require]


def _safe_date(raw):
    return raw if isinstance(raw, str) and len(raw) <= 64 else None


def _safe_source(entry, business_at):
    return {
        "source_id": entry.get("source_id"),
        "source_type": entry.get("source_type"),
        "version": entry.get("version"),
        "author_contact_id": entry.get("author_contact_id"),
        "published_at": entry.get("published_at"),
        "valid_from": entry.get("valid_from"),
        "valid_until": entry.get("valid_until"),
        "validity_state": source_validity(entry, business_at),
        "withdrawn": bool(entry.get("withdrawn")),
        "access_scope": "BOSS_ONLY" if entry.get("access_scope") == "boss-1" else "NOT_AUTHORIZED",
        "content_visible": False,
        "index_state": entry.get("index_state", "LEGACY_INDEX_STATE_UNVERIFIED"),
        "created_by_role": entry.get("created_by_role"),
        "title": entry.get("title") if entry.get("created_by_role") == "MAINTAINER" else None,
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
            db.execute("BEGIN")
            self.store.active(db, self.namespace)
            data = meeting_materials(db, self.store.get(db, self.namespace, "initial", "snapshot"))
            output = self._read(db, data, key, role, query_string)
        output["read_at"] = now()
        output["source_type"] = "SIMULATED"
        output["namespace"] = self.namespace
        output["data_version"] = data["dataset_version"]
        output["projection"] = key
        return 200, output

    def _read(self, db, data, key, role, query_string):
        business_at = self.store.get(db, self.namespace, "clock", "current")["at"]
        if key == "voice":
            # Fixed local runtime configuration, never client-selected paths
            # or the raw Provider secret/transport state.
            runtime_config = Path(self.store.path).parent / "config.json"
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
        if key == "research":
            return research_projection(db,data)
        if key == "travel":
            return travel_projection(self, db, data)
        if key == "people":
            return people_projection(self, db, data)
        if key == "owner-goals":
            return goals_projection(self, db, data)
        if key == "owner-notice":
            return notice_projection(self, db, data)
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
            # Persisted confirmed minutes remain immutable for audit, but a
            # withdrawn/replaced source cannot be revived as a current quote
            # through this separate read projection.
            if minute is not None:
                source = current_sources.get(minute["source_id"])
                current = bool(
                    source and source_validity(source, business_at) == "VALID"
                    and source.get("access_scope") == data["owner_id"]
                    and source.get("source_type") == "SIMULATED"
                    and source.get("version") == minute["source_version"]
                    and external_adoption(db, self.namespace, data, business_at, source)["state"] != "NEEDS_REIMPORT"
                )
                minute = dict(minute)
                minute["source_reference_state"] = "CURRENT" if current else "NEEDS_REVIEW"
                if not current:
                    minute["entries"] = [{
                        "entry_id": entry["entry_id"],
                        "kind": entry["kind"],
                        "text": "",
                        "source_anchor": "",
                        "source_id": entry["source_id"],
                        "source_version": entry["source_version"],
                        "reference_state": "NEEDS_REVIEW",
                    } for entry in minute["entries"]]
            associated = [
                _safe_source(current_sources[source_id], business_at)
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
                "eligible_assignment_contacts": [{
                    "contact_id": c["contact_id"],
                    "name": c["name"],
                    "organization": c["organization"],
                    "responsibility": c["responsibility"],
                    "allowed_for_fixture_assignment": c["contact_id"] == "coordinator-1"
                    and c["valid_from"] <=
                    self.store.get(db, self.namespace, "clock", "current")["at"][:10]
                    <= c["valid_until"],
                } for c in data["contacts"]],
                "business_clock": self.store.get(db, self.namespace, "clock", "current")["at"],
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
            current = current_memory(db, self.namespace)
            return {
                "memory": {
                    "memory_id": current.get("memory_id"),
                    "version": current["version"],
                    "confirmation_state": current["confirmation_state"],
                    "text": current.get("text", "") if current["confirmation_state"] == "CONFIRMED" else "",
                } if current else None,
                "effective": confirmed_memory(db, self.namespace, current, data["owner_id"]) is not None,
                "future_turn_policy": "CURRENT_NON_REVOKED_CONFIRMATION_ONLY",
                "physical_secure_erasure_verified": False,
            }
        if key == "calendar":
            calendar = current_calendar(db, self.namespace, data)
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
                    "ends_at": data["meeting"].get("ends_at"),
                    "end_is_known": bool(data["meeting"].get("ends_at")),
                },
                "visibility": "BOSS_PRIVATE",
                "external_share_created": False,
                "can_edit": calendar is None or calendar["status"] != "DELETED",
                "physical_secure_erasure_verified": False,
            }
        if key == "sources" or key == "source-index":
            docs = _object_list(db, self.namespace, "document")
            records = [_safe_source(d, business_at) for d in docs]
            if role == "MAINTAINER":
                records = [{k: v for k, v in d.items() if k not in
                            ("author_contact_id",)} for d in records]
            return {
                "sources": records, "count": len(records),
                "original_body_available_here": False,
                "available_simulated_author_ids": [
                    c["contact_id"] for c in data["contacts"]
                ] if key == "source-index" else [],
                "external_ingestion_performed": False,
            }
        if key == "knowledge":
            params = parse_qs(query_string, keep_blank_values=True)
            phrase = params.get("q", [""])[0].strip()[:100]
            # Use the original approved documents index, no public search.
            documents = _object_list(db, self.namespace, "document")
            matches = []
            for document in documents:
                if (source_validity(document, business_at) != "VALID"
                        or document.get("access_scope") != data["owner_id"]
                        or document.get("source_type") != "SIMULATED"
                        or external_adoption(db, self.namespace, data, business_at, document)["state"] == "NEEDS_REIMPORT"):
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
            from boss_business_alerts import BusinessAlertsAPI

            if self.namespace != NS:
                raise web.HTTPConflict(text="当前经营提醒执行空间不匹配")
            events = _object_list(db, self.namespace, "event")
            operating_ids = {event["event_id"] for event in events if event.get("generated_by") == "BUSINESS_ALERT_INPUT"}
            events = [event for event in events if event["event_id"] not in operating_ids]
            sent = _object_list(db, self.namespace, "notification")
            reminders = _object_list(db, self.namespace, "reminder")
            deliveries = _object_list(db, self.namespace, "delivery")
            rules = _object_list(db, self.namespace, "rules")
            active_notice = effective_owner_notice(db, data)
            dispatches = _object_list(db, self.namespace, "dispatch")
            sent = [row for row in sent if row.get("event_id") not in operating_ids]
            reminders = [row for row in reminders if row.get("event_id") not in operating_ids]
            deliveries = [row for row in deliveries if row.get("event_id") not in operating_ids]
            dispatches = [row for row in dispatches if row.get("event_id") not in operating_ids]
            return {
                "business_alerts": BusinessAlertsAPI(self.store).project_in_transaction(role, db),
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
                "owner_notification_preferences": ({
                    "version": active_notice["version"],
                    "reading_format": active_notice["content"]["reading_format"],
                    "notifications_enabled": active_notice["content"]["notifications_enabled"],
                    "timezone": active_notice["content"]["timezone"],
                    "quiet_start": active_notice["content"]["quiet_start"],
                    "quiet_end": active_notice["content"]["quiet_end"],
                    "important_during_quiet": active_notice["content"]["important_during_quiet"],
                } if active_notice else None),
                "dispatches": [{
                    k: row[k] for k in ("event_id", "event_version",
                        "state", "reason", "business_at", "rule_version",
                        "schedule_version", "owner_notice_version") if k in row
                } for row in dispatches],
                "count": len(sent), "notification_draft_only": len(sent) == 0,
            }
        if key == "authorizations":
            rows = [row for row in _object_list(db, self.namespace, "authorization")
                    if row.get("owner_id") == data["owner_id"]
                    and row.get("scope") == self.namespace
                    and row.get("issuer_identity") == "BOSS"]
            return {"authorizations": [{
                **{k: row[k] for k in (
                    "authorization_id", "issuer_identity", "action", "target_id",
                    "content_version", "version", "revoked", "revoked_at",
                    "valid_from", "valid_until", "scope",
                ) if k in row},
                "can_revoke": authorization_can_revoke(row, data["owner_id"], self.namespace),
            } for row in rows],
            "revocation_only_affects_future_use": True,
            "historical_actions_reversed": False,
            "secrets_or_payloads_returned": False}
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
        if key == "prompt-versions":
            drafts = _object_list(db, self.namespace, "prompt_draft")
            revisions = _object_list(db, self.namespace, "prompt_revision")
            context_records = _object_list(db, self.namespace, "prompt_context_use")
            context_index = {
                (item["prompt_id"],item["prompt_version"]):item
                for item in context_records
            }
            active = []
            for kind in KINDS:
                record = db.execute(
                    "SELECT body FROM objects WHERE namespace=? AND kind='prompt_active' AND id=?",
                    (self.namespace, kind),
                ).fetchone()
                if record:
                    item = json.loads(record[0])
                    active.append({
                        "kind": kind, "prompt_id": item["prompt_id"],
                        "prompt_version": item["prompt_version"],
                        "active_version": item["active_version"],
                        "enabled": item["enabled"],
                        "adoption_policy": item["adoption_policy"],
                        "actual_model_evaluation_passed": False,
                        "runtime_context_adoption": context_index.get(
                            (item["prompt_id"],item["prompt_version"]),{}
                        ).get("observation","NOT_OBSERVED"),
                        "context_load_count": context_index.get(
                            (item["prompt_id"],item["prompt_version"]),{}
                        ).get("context_load_count",0),
                        "last_context_at": context_index.get(
                            (item["prompt_id"],item["prompt_version"]),{}
                        ).get("at"),
                    })
            valid_runtime_ids = {
                p["prompt_id"] for p in active_runtime_prompts(self.store, self.namespace)
            }
            return {
                "kinds": list(KINDS),
                "drafts": [{
                    k: entry[k] for k in (
                        "prompt_id", "kind", "title", "instruction_text", "version",
                        "content_sha256", "source_refs", "change_note",
                        "validation_status", "validated_at", "updated_at",
                    ) if k in entry
                } for entry in drafts],
                "active": active,
                "revisions": [{
                    k: entry[k] for k in (
                        "prompt_id", "kind", "title", "instruction_text", "version",
                        "content_sha256", "source_refs", "change_note",
                        "validation_status", "validated_at", "updated_at",
                    ) if k in entry
                } for entry in revisions],
                "adoptable_current_ids": sorted(valid_runtime_ids),
                "model_evaluation_completed": False,
                "full_security_evaluation_completed": False,
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
            from boss_scheduler_config import SCOPES, RESTART_POLICIES, plan_fields
            schedule = self.store.get(db, self.namespace, "schedule", "current")
            clock = self.store.get(db, self.namespace, "clock", "current")
            draft_row = db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='scheduler_draft' AND id='current'",
                (self.namespace,),
            ).fetchone()
            rules_row = db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='rules' AND id='current'",
                (self.namespace,),
            ).fetchone()
            draft = json.loads(draft_row[0]) if draft_row else None
            if draft is not None:
                draft = {**draft, "configuration": {**draft["configuration"], **plan_fields(draft["configuration"])}}
            rules = json.loads(rules_row[0]) if rules_row else None
            dispatches = _object_list(db, self.namespace, "dispatch")
            executor = getattr(self.store, "scheduler_runtime", None)
            runtime = executor.snapshot() if executor is not None else {
                "state": "NOT_ATTACHED", "active_run_count": 0, "resume_checked_at": None,
                "quit_behavior": "当前接口未连接应用调度责任组件", "next_run_time": None,
            }
            if executor is not None and runtime["schedule_version"] != schedule["version"]:
                runtime = {**runtime, "state": "CONFIGURATION_PENDING", "next_run_time": None}
            return {
                "schedule": {**{k: schedule.get(k) for k in (
                    "schedule_id", "version", "schedule_version", "timezone",
                    "trigger", "enabled", "canceled", "active_draft_version",
                )}, **plan_fields(schedule)},
                "executors": [{"id": "CronService", "label": "nanobot CronService"}],
                "authorized_scopes": [{"id": key, "label": label} for key, label in SCOPES.items()],
                "restart_policies": [{"id": key, "label": label} for key, label in RESTART_POLICIES.items()],
                "runtime": runtime,
                "draft": draft,
                "rules": rules,
                "simulated_business_time": clock["at"],
                "cron_runtime_verified_here": False,
                "manual_dispatch_supported_here": bool(
                    schedule["enabled"] and not schedule["canceled"]
                    and schedule.get("active_draft_version")
                ),
                "available_manual_events": [{
                    k: event[k] for k in ("event_id","version","due_at","state")
                    if k in event
                } for event in _object_list(db, self.namespace, "event")
                  if event.get("source_type") == "SIMULATED"
                  and (event.get("event_id") == data["event"]["event_id"]
                       or event.get("generated_by") in (
                           "BOSS_AUTHORIZED_TASK", "BOSS_OWN_COMMITMENT"
                       ))],
                "next_run_time": runtime["next_run_time"],
                "recent_dispatches": [{
                    k: row[k] for k in (
                        "event_id", "event_version", "state", "reason",
                        "rule_version", "schedule_version", "business_at",
                    ) if k in row
                } for row in dispatches[-20:]],
                "external_delivery_verified": False,
                "owner_business_authorization_granted": False,
            }
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
