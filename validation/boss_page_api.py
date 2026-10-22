"""Boss-Agent read projections for the first desktop React slice (T11/T18).

Every result comes from the same scoped ControlStore used by the running Agent.
No synthetic success, no client-supplied role, no uncontrolled business writes.
This is the authorized selection demo (ui-check) only, not a production API.
"""
from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs
from aiohttp import web

from business import now

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
            "execution_namespace",
        )
        return {key: item[key] for key in keys if key in item}

    def _tasks(self):
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            data = self.store.get(db, self.namespace, "initial", "snapshot")
            return {
                "source_type": "SIMULATED",
                "namespace": self.namespace,
                "tasks": [self._public_task(v) for v in self._items(db, self.namespace, "task")],
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
            known = {doc["source_id"] for doc in data.get("documents", [])}
            if source_id not in known:
                return 404, {"error": "SOURCE_NOT_FOUND"}
            doc = self.store.get(db, self.namespace, "document", source_id)
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
            if path == "/api/boss/ui/maintenance":
                if role != "MAINTAINER":
                    return 403, {"error": "FORBIDDEN"}
                return 200, self._maintenance()
            if role != "BOSS":
                return 403, {"error": "FORBIDDEN"}
            if path == "/api/boss/ui/dashboard":
                return 200, self._dashboard()
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
