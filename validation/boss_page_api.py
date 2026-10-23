"""Boss-Agent read projections for the first desktop React slice (T11/T18).

Every result comes from the same scoped ControlStore used by the running Agent.
No synthetic success, no client-supplied role, no uncontrolled business writes.
This is the authorized selection demo (ui-check) only, not a production API.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import parse_qs
from aiohttp import web

from business import now
from boss_workspace_api import BossWorkspaceAPI
from boss_sector_api import BossSectorAPI
from boss_recovery_api import BossRecoveryAPI
from boss_owner_preferences import owner_profile
from boss_admin_config import memory_technical_status, prompt_technical_status
from boss_owner_plans import OwnerPlansAPI
from boss_today import TodayAPI
from boss_meetings import MeetingAPI, meeting_materials
from boss_source_access import require_current_simulated_source
from boss_source_policy import source_validity
from boss_runtime_records import runtime_records
from runtime_records_query import read_runtime_task_reference
from boss_assignment_sources import AssignmentSourcesAPI
from boss_simulation_api import SimulationAPI

DEMO_NAMESPACE = "ui-check"
METRIC_IDS = (
    "sales_quantity", "revenue", "cost", "gross_profit",
    "gross_margin", "gross_profit_per_tonne",
)


class BossPageAPI:
    """Role-scoped adapter called *after* RoleChannel validates the API token.

    Returns (http_status, JSON body); it does not bypass the authenticated
    nanobot gateway, expose secrets or grant owner authority to maintainers.
    """

    def __init__(self, store, namespace: str = DEMO_NAMESPACE, runtime_control=None, skills=None):
        self.store = store
        self.namespace = namespace
        self.workspace = BossWorkspaceAPI(store, namespace)
        self.sectors = BossSectorAPI(store, namespace)
        self.recovery = BossRecoveryAPI(store, namespace)
        self.runtime_control = runtime_control
        self.skills = skills

    @staticmethod
    def _items(db, namespace, kind):
        result = db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id",
            (namespace, kind),
        ).fetchall()
        return [json.loads(row[0]) for row in result]

    def _snapshot(self):
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            return meeting_materials(db, self.store.get(db, self.namespace, "initial", "snapshot"))

    def _dashboard(self):
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            data = meeting_materials(db, self.store.get(db, self.namespace, "initial", "snapshot"))
            clock = self.store.get(db, self.namespace, "clock", "current")
            tasks = self._items(db, self.namespace, "task")
            notifications = self._items(db, self.namespace, "notification")
            return {
                "source_type": "SIMULATED",
                "namespace": self.namespace,
                "dataset_id": data["dataset_id"],
                "dataset_version": data["dataset_version"],
                "business_clock": clock["at"],
                "refreshed_at": now(),
                "profile": owner_profile(db, data),
                "source_coverage": {
                    "region": "region-1",
                    "trade_scope": "EXTERNAL_SALES",
                    "periods": data["periods"],
                    "dataset_version": data["dataset_version"],
                },
                "tasks": [self._public_task(task) for task in tasks],
                "historical_commitment": data.get("historical_task"),
                "meeting": data.get("meeting"),
                "event": {"event_id": data["event"]["event_id"],
                          "status": data["event"]["status"]},
                "assignment_source_ids": [
                    item["source_id"] for item in data["documents"]
                    if item["source_id"] == "finance-note"
                    and not self.store.get(db, self.namespace, "document", item["source_id"]).get("withdrawn")
                ],
                "contacts": [
                    {"contact_id": item["contact_id"], "name": item["name"],
                     "organization": item["organization"], "responsibility": item["responsibility"]}
                    for item in data.get("contacts", [])
                ],
                "notifications": [
                    {"event_id": obj.get("event_id"), "state": obj.get("state"),
                     "created_at": obj.get("created_at"), "source_type": obj.get("source_type")}
                    for obj in notifications
                ],
            }

    @staticmethod
    def _public_task(item):
        keys = (
            "task_id", "status", "version", "purpose", "coordinator_id",
            "due_at", "timezone", "evidence_requirements", "related_meeting_id",
            "related_event_ids", "source_refs", "feedback_ids", "message_ids",
            "execution_namespace", "origin_minute_id", "origin_minute_version",
            "origin_entry_id", "origin_source_id", "origin_source_version",
        )
        return {key: item[key] for key in keys if key in item}

    def _tasks(self):
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, self.namespace)
            data = meeting_materials(db, self.store.get(db, self.namespace, "initial", "snapshot"))
            business_at = self.store.get(db, self.namespace, "clock", "current")["at"]
            task_messages = [{
                "message_id": row["message_id"],
                "task_id": row["task_id"],
                "type": "ASSIGNMENT_SEND",
                "recipient_id": row["recipient_id"],
                "sent_at": row["sent_at"],
                "send_state": "SENT_SIMULATED",
                "delivery_state": "NOT_VERIFIED",
                "reply_state": "NOT_VERIFIED",
                "external_channel_invoked": False,
                "source_type": "SIMULATED",
            } for row in self._items(db, self.namespace, "outbox")
              if row.get("task_id") and row.get("message_id")]
            followup_messages = [{
                "message_id": row["message_id"],
                "task_id": row["related_task_id"],
                "type": "FOLLOWUP_MESSAGE",
                "recipient_id": row["recipient_id"],
                "sent_at": row["sent_at"],
                "send_state": row["send_state"],
                "delivery_state": row["delivery_state"],
                "reply_state": row["reply_state"],
                "external_channel_invoked": False,
                "source_type": "SIMULATED",
            } for row in self._items(db, self.namespace, "message_outbox")
              if row.get("related_task_id") and row.get("message_id")]
            nudge_messages = [{
                "message_id": row["message_id"],
                "task_id": row["task_id"],
                "type": "ASSIGNMENT_NUDGE",
                "recipient_id": row["recipient_id"],
                "sent_at": row["sent_at"],
                "business_at": row["business_at"],
                "send_state": row["message_status"],
                "delivery_state": row["delivery_state"],
                "reply_state": row["reply_state"],
                "external_channel_invoked": False,
                "source_type": "SIMULATED",
            } for row in self._items(db, self.namespace, "assignment_nudge")]
            linked_messages = sorted(
                [*task_messages, *followup_messages, *nudge_messages],
                key=lambda row: (row["sent_at"], row["message_id"]),
            )
            # Task-specific due notifications are owned by the same SQLite
            # business lifecycle as F06, not inferred from displayed deadlines.
            dispatch_index = {
                row["event_id"]: row for row in
                self._items(db, self.namespace, "dispatch")
                if row.get("event_id")
            }
            task_due_events = [
                {
                    "task_id": row["task_id"],
                    "event_id": row["event_id"],
                    "event_version": row["version"],
                    "event_state": row["state"],
                    "due_at": row["due_at"],
                    "task_version_at_sync": row["task_version"],
                    "dispatch_state": dispatch_index.get(
                        row["event_id"], {}
                    ).get("state", "NOT_DISPATCHED"),
                    "dispatch_reason": dispatch_index.get(
                        row["event_id"], {}
                    ).get("reason"),
                    "external_delivery_verified": False,
                }
                for row in self._items(db, self.namespace, "event")
                if row.get("generated_by") == "BOSS_AUTHORIZED_TASK"
                and row.get("task_id")
            ]
            available = {
                row["source_id"]: row for row in
                self._items(db, self.namespace, "document")
            }
            tasks = []
            source_reviews = AssignmentSourcesAPI(self.store)
            for task in self._items(db, self.namespace, "task"):
                item = self._public_task(task)
                review = source_reviews.project_in_transaction("BOSS", db, task["task_id"])
                item["source_reference_state"] = "CURRENT" if review["binding_state"] == "CURRENT" else "NEEDS_REVIEW"
                reasons = []
                if review["binding_state"] != "CURRENT":
                    reasons.append("SOURCE_BINDING_" + review["binding_state"])
                    for source in review["sources"]:
                        prefix = "MINUTE" if source["is_minute_origin"] else "SOURCE"
                        if source["source_status"] != "VALID":
                            reasons.append(prefix + "_UNAVAILABLE")
                        if source["pinned_version"] is None:
                            reasons.append("UNPINNED_SOURCE_VERSION")
                        elif source["current_version"] is not None and source["pinned_version"] != source["current_version"]:
                            reasons.append(prefix + "_VERSION_CHANGED")
                item["source_reference_reasons"] = list(dict.fromkeys(reasons))
                item["result_evidence_requires_resubmission"] = review["result_evidence_requires_resubmission"]
                tasks.append(item)
            return {
                "source_type": "SIMULATED",
                "namespace": self.namespace,
                "tasks": tasks,
                "linked_messages": linked_messages,
                "task_due_events": task_due_events,
                "feedback": [
                    {key: item[key] for key in (
                        "feedback_id", "task_id", "kind", "content",
                        "evidence_refs", "author_contact_id", "submitted_at",
                        "source_type", "proposed_due_at",
                    ) if key in item}
                    for item in self._items(db, self.namespace, "feedback")
                ],
                "historical_commitment": data.get("historical_task"),
                "self_commitments": [{
                    **{k: item[k] for k in (
                        "commitment_id", "purpose", "version", "status", "due_at",
                        "timezone", "importance", "evidence_requirements", "source_refs",
                        "completion_evidence", "created_at", "completed_at", "canceled_at",
                        "source_type",
                    ) if k in item},
                    "source_reference_state": (
                        "CURRENT" if all(
                            ref["source_id"] in available
                            and available[ref["source_id"]].get("version") == ref["version"]
                            and not available[ref["source_id"]].get("withdrawn")
                            and available[ref["source_id"]].get("access_scope") == data["owner_id"]
                            and available[ref["source_id"]].get("source_type") == "SIMULATED"
                            for ref in (item.get("source_refs", []) + item.get("completion_evidence", []))
                        ) else "NEEDS_REVIEW"
                    ),
                } for item in self._items(db, self.namespace, "self_commitment")],
                "self_due_events": [{
                    "event_id": row["event_id"],
                    "commitment_id": row["commitment_id"],
                    "event_version": row["version"], "event_state": row["state"],
                    "due_at": row["due_at"], "external_delivery_verified": False,
                } for row in self._items(db, self.namespace, "event")
                  if row.get("generated_by") == "BOSS_OWN_COMMITMENT"],
                "business_clock": self.store.get(db, self.namespace, "clock", "current")["at"],
                "read_at": now(),
            }

    def _meetings(self):
        data = self._snapshot()
        return {
            "source_type": "SIMULATED",
            "meeting": data.get("meeting"),
            "documents": [
                {"source_id": d["source_id"], "version": d["version"],
                 "source_type": d["source_type"], "author_contact_id": d["author_contact_id"],
                 "published_at": d["published_at"]}
                for d in data.get("documents", [])
            ],
            "read_at": now(),
        }

    def _evidence(self, query):
        source_id = query.get("source", [""])[0]
        if not source_id or len(source_id) > 100:
            return 400, {"error": "SOURCE_REQUIRED"}
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, self.namespace)
            data = meeting_materials(db, self.store.get(db, self.namespace, "initial", "snapshot"))
            # Current documented records are the source of truth, including
            # applications created later by the authorized simulation editor.
            # Never trust an arbitrary client locator or path.
            row = db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?",
                (self.namespace, source_id),
            ).fetchone()
            if row is None:
                return 404, {"error": "SOURCE_NOT_FOUND"}
            doc = json.loads(row[0])
            business_at = self.store.get(db, self.namespace, "clock", "current")["at"]
            require_current_simulated_source(doc, data["owner_id"], business_at)
            return 200, {
                "source_type": doc["source_type"],
                "source_id": doc["source_id"],
                "version": doc["version"],
                "published_at": doc.get("published_at"),
                "author_contact_id": doc.get("author_contact_id"),
                "original_locator": doc.get("original_locator"),
                "content": doc["content"],
                "read_at": now(),
            }

    def _metrics(self, query):
        data = self._snapshot()
        raw = query.get("products", ["product-1,product-2"])[0]
        products = [v.strip() for v in raw.split(",") if v.strip()]
        if not products or len(products) != len(set(products)) or set(products) - {"product-1", "product-2"}:
            return 400, {"error": "PRODUCT_SCOPE_INVALID"}
        # The exact *existing* business tool is called with validated, server-
        # generated envelope. No fake result or independent frontend calculator.
        payload = {
            "envelope": {
                "request_id": str(uuid.uuid4()),
                "owner_id": data["owner_id"],
                "execution_namespace": self.namespace,
                "dataset_id": data["dataset_id"],
                "dataset_version": data["dataset_version"],
                "session_id": "boss-ui",
            },
            "question": "查询获准模拟经营指标，并保留原始精度与来源",
            "metric_ids": list(METRIC_IDS),
            "region_id": "region-1",
            "product_ids": products,
            "period_start": data["periods"]["CURRENT"][0],
            "period_end": data["periods"]["CURRENT"][1],
            "comparison_start": data["periods"]["BASE"][0],
            "comparison_end": data["periods"]["BASE"][1],
            "currency": "CNY",
            "trade_scope": "EXTERNAL_SALES",
            "definition_version": "1",
        }
        result = self.store.invoke("query_metrics", payload)
        return 200, {
            "source_type": "SIMULATED",
            "result": result,
            "read_at": now(),
        }

    def _model_runtime(self, role: str):
        """Project metadata-only model/probe log; never return prompts or API keys."""
        local = Path(self.store.path).parent / "diagnostics"
        transports = local / "http-requests.json"
        events_file = local / "events.json"

        def read_local(file):
            if not file.is_file():
                return []
            if file.stat().st_size > 8 * 1024 * 1024:
                return []  # bounded read; never a remote URL or supplied path
            result = json.loads(file.read_text(encoding="utf-8"))
            return result if isinstance(result, list) else []

        requests = read_local(transports)
        events = read_local(events_file)
        calls = [v for v in requests
                 if isinstance(v, dict) and v.get("type") == "request"]
        responses = {}
        for record in requests:
            if not isinstance(record, dict):
                continue
            if record.get("type") not in ("stream_metadata", "response"):
                continue
            rid = record.get("response_id")
            if not isinstance(rid, str) or not rid:
                continue
            # The final usage chunk can follow the initial response chunk.
            original = responses.get(rid, {})
            responses[rid] = {
                "response_id": rid[:128],
                "at": record.get("at", original.get("at")),
                "model": record.get("model") or original.get("model"),
                "usage": record.get("usage") if isinstance(record.get("usage"), dict)
                         else original.get("usage"),
                "finish_reasons": record.get("finish_reasons")
                         if isinstance(record.get("finish_reasons"), list)
                         else original.get("finish_reasons", []),
            }
        latest = list(responses.values())[-1] if responses else None
        usage = latest.get("usage") if latest else None
        # Refuse arbitrary provider usage fields: only numeric token counts.
        summary = {
            k: usage.get(k) if isinstance(usage, dict) and
                  isinstance(usage.get(k), (int, float)) else None
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        result = {
            "source_type": "ACTUAL_PROVIDER_DIAGNOSTICS",
            "provider": "deepseek" if calls else "NOT_OBSERVED",
            "data_source": "LOCAL_PRIVATE_REDACTED_LOG",
            "observed_request_count": len(calls),
            "observed_response_count": len(responses),
            "runtime_response_observed": bool(latest),
            "latest_response": {
                "response_id": latest["response_id"],
                "at": latest.get("at"),
                "model": latest.get("model"),
                "finish_reasons": latest.get("finish_reasons", []),
            } if latest else None,
            "reported_usage": summary if latest else None,
            "cost_total": None,
            "business_task_completed": False,
            "read_at": now(),
        }
        if role == "MAINTAINER":
            result["tool_event_count"] = sum(
                1 for row in events
                if isinstance(row, dict) and row.get("type") == "tool"
            )
            result["observed_error_count"] = sum(
                1 for row in events
                if isinstance(row, dict) and row.get("error_present")
            )
        return result

    def _maintenance(self):
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            configuration = self.store.get(db, self.namespace, "configuration", "current")
            count = db.execute(
                "SELECT kind,COUNT(*) FROM objects WHERE namespace=? "
                "AND kind IN ('task','notification','document') GROUP BY kind",
                (self.namespace,),
            ).fetchall()
            return {
                "scope": "MAINTAINER_METADATA_ONLY",
                "source_type": "SIMULATED",
                "status": "VALIDATION_SERVICE_NOT_PRODUCT_INSTALL",
                "task_refs": [
                    {key: item[key] for key in ("task_id", "status", "version", "coordinator_id")
                     if key in item}
                    for item in self._items(db, self.namespace, "task")
                ],
                "configured_provider": configuration["provider"],
                "configured_model": configuration["model_id"],
                "configuration_version": configuration["version"],
                "counts": dict(count),
                "read_at": now(),
            }

    def serve(self, role: str | None, path: str, query_string: str = ""):
        """Exact allowlist; fail closed for expired/missing roles and paths."""
        if role not in ("BOSS", "MAINTAINER"):
            return 401, {"error": "UNAUTHENTICATED"}
        try:
            if path == "/api/boss/ui/simulation-query":
                return 200, SimulationAPI(self.store).query_http(role, query_string)
            if path == "/api/boss/ui/simulation-inspect":
                return 200, SimulationAPI(self.store).inspect_http(role, query_string)
            if path == "/api/boss/ui/admin/skills":
                if role != "MAINTAINER":
                    return 403, {"error": "FORBIDDEN"}
                if query_string:
                    return 400, {"error": "INVALID_QUERY_PARAMETERS"}
                if self.skills is None:
                    return 503, {"error": "SKILL_SERVICE_NOT_READY"}
                return 200, self.skills.read(role)
            if path in {"/api/boss/ui/assignment-source-review", "/api/boss/ui/runtime-records/task"}:
                if path == "/api/boss/ui/assignment-source-review" and role != "BOSS":
                    return 403, {"error": "FORBIDDEN"}
                query = parse_qs(query_string, keep_blank_values=True)
                keys = {"task_id"} if path == "/api/boss/ui/assignment-source-review" else {"run_id", "task_id"}
                if set(query) != keys or any(len(values) != 1 or not values[0] for values in query.values()):
                    return 400, {"error": "INVALID_QUERY_PARAMETERS"}
                if self.namespace != DEMO_NAMESPACE:
                    return 409, {"error": "EXECUTION_SCOPE_UNAVAILABLE"}
                if path == "/api/boss/ui/assignment-source-review":
                    return 200, AssignmentSourcesAPI(self.store).read(role, query["task_id"][0])
                return 200, read_runtime_task_reference(self.store, role, self.namespace, query["run_id"][0], query["task_id"][0])
            if path == "/api/boss/ui/admin/runtime-configuration":
                if role != "MAINTAINER":
                    return 403, {"error": "FORBIDDEN"}
                if query_string:
                    return 400, {"error": "INVALID_INPUT"}
                if self.runtime_control is None:
                    return 503, {"error": "RUNTIME_NOT_READY"}
                return 200, self.runtime_control.read()
            if path == "/api/boss/ui/runtime-records":
                query = parse_qs(query_string, keep_blank_values=True)
                if any(len(values) != 1 for values in query.values()):
                    return 400, {"error": "DUPLICATE_QUERY_PARAMETER"}
                parameters = {key: values[0] for key, values in query.items()}
                if set(parameters) == {"run_id"}:
                    return 200, runtime_records(self.store, role, self.namespace, run_id=parameters["run_id"])
                return 200, runtime_records(self.store, role, self.namespace, query=parameters)
            if path == "/api/boss/ui/admin/memory-status":
                if role != "MAINTAINER":
                    return 403, {"error": "FORBIDDEN"}
                if query_string:
                    return 400, {"error": "INVALID_INPUT"}
                return 200, memory_technical_status(self.store, role, self.namespace)
            if path in ("/api/boss/ui/operation-status", "/api/boss/ui/calendar-share-preview", "/api/boss/ui/calendar-conflict"):
                return self.recovery.serve(role, path, query_string)
            if path.startswith("/api/boss/ui/workspace/"):
                status, result = self.workspace.serve(role, path, query_string)
                if status == 200 and path == "/api/boss/ui/workspace/prompt-versions":
                    if query_string:
                        return 400, {"error": "INVALID_INPUT"}
                    result["runtime_eligibility"] = prompt_technical_status(self.store, role, self.namespace)
                return status, result
            if path == "/api/boss/ui/sector":
                return self.sectors.serve(role, query_string)
            if path == "/api/boss/ui/maintenance":
                if role != "MAINTAINER":
                    return 403, {"error": "FORBIDDEN"}
                return 200, self._maintenance()
            if path == "/api/boss/ui/model-usage":
                if role != "MAINTAINER":
                    return 403, {"error": "FORBIDDEN"}
                return 200, self._model_runtime(role)
            if role != "BOSS":
                return 403, {"error": "FORBIDDEN"}
            if path in ("/api/boss/ui/today", "/api/boss/ui/owner-plans", "/api/boss/ui/meeting-arrangement"):
                if query_string:
                    return 400, {"error": "INVALID_INPUT"}
                if path == "/api/boss/ui/today":
                    return 200, TodayAPI(self.store).read(role)
                if path == "/api/boss/ui/meeting-arrangement":
                    return 200, MeetingAPI(self.store).read(role)
                return 200, OwnerPlansAPI(self.store).read(role)
            if path == "/api/boss/ui/dashboard":
                return 200, self._dashboard()
            if path == "/api/boss/ui/model-health":
                return 200, self._model_runtime(role)
            if path == "/api/boss/ui/tasks":
                return 200, self._tasks()
            if path == "/api/boss/ui/meetings":
                return 200, self._meetings()
            query = parse_qs(query_string, keep_blank_values=True)
            if path == "/api/boss/ui/evidence":
                return self._evidence(query)
            if path == "/api/boss/ui/metrics":
                return self._metrics(query)
            return 404, {"error": "API_NOT_FOUND"}
        except web.HTTPException as error:
            # No stack traces or sensitive object text in the renderer.
            return error.status, {"error": "BUSINESS_OPERATION_FAILED", "status": error.status}
