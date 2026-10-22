"""Role-scoped Boss-Agent workspace projections.

Read-only, server-owned projections of *actual* selection data. These power the
next Desktop v6 implementation slice; empty data stays empty, with source,
version and coverage in response. No fake departmental users or inferred ROI.

Endpoints are deliberately under the authenticated RoleChannel gateway.
"""
from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qs

from aiohttp import web

from business import OPERATIONS, now

NS = "ui-check"
BOSS_PAGES = {
    "memory", "calendar", "notifications", "authorizations", "decisions",
    "outbox", "sources", "knowledge", "organization", "plans",
}
MAINT_PAGES = {
    "dataset", "source-index", "tool-catalog", "metric-definitions",
    "relationships", "scheduler", "audit", "system",
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
            calendar = dict(data["private_calendar"])
            # Only BOSS sees private_body. No public/maintainer counterpart.
            return {"calendar": calendar, "visibility": "BOSS_PRIVATE",
                    "external_share_created": False, "can_edit": False}
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
                "SELECT id,operation,created_at FROM audit WHERE namespace=? "
                "AND operation IN ('boss.assignment.complete','boss.assignment.extend',"
                "'boss.assignment.cancel','boss.memory.confirm','boss.memory.delete',"
                "'boss.reminder.ack','boss.reminder.snooze','boss.reminder.close') "
                "ORDER BY id DESC LIMIT 80",
                (self.namespace,),
            ).fetchall()
            return {"history": [
                {"sequence": row[0], "action": row[1], "at": row[2]}
                for row in audit
            ], "raw_action_payload_returned": False}
        if key == "outbox":
            rows = _object_list(db, self.namespace, "outbox")
            return {"messages": [{k: r[k] for k in (
                "message_id", "task_id", "message_status", "task_status",
                "task_version", "recipient_id", "sent_at", "source_type"
            ) if k in r} for r in rows], "body_exposed": False}
        if key == "dataset":
            c = db.execute(
                "SELECT kind, COUNT(*) FROM objects WHERE namespace=? "
                "GROUP BY kind ORDER BY kind", (self.namespace,),
            ).fetchall()
            return {"dataset_id": data["dataset_id"], "version": data["dataset_version"],
                    "generator_version": data.get("generator_version"),
                    "seed": data.get("seed"), "object_counts": dict(c),
                    "business_periods": data["periods"],
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
            }, "owner_body_access": False}
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
