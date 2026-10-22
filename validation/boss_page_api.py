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

    def __init__(self, store, namespace: str = DEMO_NAMESPACE):
        self.store = store
        self.namespace = namespace
        self.workspace = BossWorkspaceAPI(store, namespace)
        self.sectors = BossSectorAPI(store, namespace)
        self.recovery = BossRecoveryAPI(store, namespace)

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
            return self.store.get(db, self.namespace, "initial", "snapshot")

    def _dashboard(self):
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            data = self.store.get(db, self.namespace, "initial", "snapshot")
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
                "profile": {
                    "timezone": data["boss_profile"]["timezone"],
                    "goals": data["boss_profile"]["goals"],
                    "reading_requirement": data["boss_profile"]["confirmed_reading_requirement"],
                },
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
            self.store.active(db, self.namespace)
            data = self.store.get(db, self.namespace, "initial", "snapshot")
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
            linked_messages = sorted(
                [*task_messages, *followup_messages],
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
            for task in self._items(db, self.namespace, "task"):
                item = self._public_task(task)
                pinned = task.get("source_versions")
                violations = []
                sources = task.get("source_refs", [])
                if not isinstance(pinned, dict) or set(pinned) != set(sources):
                    violations.append("UNPINNED_SOURCE_VERSION")
                for source_id in sources:
                    doc = available.get(source_id)
                    if doc is None or doc.get("withdrawn") or (
                        doc.get("access_scope") != data["owner_id"]
                        or doc.get("source_type") != "SIMULATED"
                    ):
                        violations.append("SOURCE_UNAVAILABLE")
                    elif isinstance(pinned, dict) and doc.get("version") != pinned.get(source_id):
                        violations.append("SOURCE_VERSION_CHANGED")
                original_id = task.get("origin_source_id")
                if original_id:
                    doc = available.get(original_id)
                    if doc is None or doc.get("withdrawn") or (
                        doc.get("access_scope") != data["owner_id"]
                        or doc.get("source_type") != "SIMULATED"
                    ):
                        violations.append("MINUTE_SOURCE_UNAVAILABLE")
                    elif doc.get("version") != task.get("origin_source_version"):
                        violations.append("MINUTE_VERSION_CHANGED")
                item["source_reference_state"] = (
                    "NEEDS_REVIEW" if violations else "CURRENT"
                )
                item["source_reference_reasons"] = sorted(set(violations))
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
            self.store.active(db, self.namespace)
            data = self.store.get(db, self.namespace, "initial", "snapshot")
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
            if doc.get("access_scope") != data["owner_id"]:
                return 403, {"error": "SOURCE_FORBIDDEN"}
            if doc.get("withdrawn"):
                return 410, {"error": "SOURCE_WITHDRAWN", "source_id": source_id}
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
            if path in ("/api/boss/ui/operation-status", "/api/boss/ui/calendar-share-preview", "/api/boss/ui/calendar-conflict"):
                return self.recovery.serve(role, path, query_string)
            if path.startswith("/api/boss/ui/workspace/"):
                return self.workspace.serve(role, path, query_string)
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
