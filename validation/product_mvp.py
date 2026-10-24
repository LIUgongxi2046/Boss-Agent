import asyncio
import json
from urllib.parse import parse_qs, urlencode

from aiohttp import web
from nanobot.agent.tools.context import current_request_context

from business import checksum, now, require
from boss_page_api import BossPageAPI
from boss_simulation_api import _context
from boss_supply_quality import SupplyQualityAPI, bound_source_references
from boss_source_access import require_current_business_source
from product_fc01 import ProductFc01, GRANT, validate_request


class ProductMVP(ProductFc01):
    def __init__(self, store):
        super().__init__(store)
        self.query_requests = set()
        self.active_queries = {}

    async def events(self, messages, tools):
        response = await super().events(messages, tools)
        request = current_request_context()
        if request is None or GRANT not in request.attributes:
            return response
        _, grant = self._grant()
        outputs = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        if grant.key in self.query_requests and len(outputs) == 1:
            view = outputs[0]
            report = next(report for row in view["supply"] for report in row["cost_reports"] if report["current"]["report_id"] == grant.params["origin_record_id"])
            require(view["review_sha256"] == grant.params["review_sha256"] and report["baseline"] is not None,
                    "当前采购报告不具备匹配的两个期间", web.HTTPConflict)
            result = {"query_id": grant.key, "source_type": "SIMULATED", "interface_id": "SI09", "read_at": now(),
                "business_at": view["business_at"], "review_sha256": view["review_sha256"], "cost_report": report,
                "source_refs": [{"source_id": report[period]["source_id"], "version": report[period]["source_version"]} for period in ("baseline", "current")],
                "coordinate_input": grant.params}
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                context = _context(db)
                require(context["dataset_id"] == grant.dataset_id and context["dataset_version"] == grant.dataset_version, "采购资料范围已经变化", web.HTTPConflict)
                references = {}
                for period in ("baseline", "current"):
                    record = next(record for record in view["records"] if record["record_id"] == report[period]["report_id"] and record["entity_type"] == "material_cost_report")
                    for reference in bound_source_references(db, context, "material_cost_report", record):
                        references[reference["source_id"]] = reference
                result["source_refs"] = list(references.values())
                self.store.put(db, "ui-check", "mvp_query", grant.key, {"owner_id": context["owner_id"], "dataset_id": grant.dataset_id,
                    "dataset_version": grant.dataset_version, "input_sha256": checksum(grant.params), "result": result})
        return response

    async def query(self, role, payload, active):
        require(role == "BOSS" and active(), "采购查询需要本人认证", web.HTTPForbidden)
        validate_request("Prepare", payload)
        params = payload["coordinate_input"]
        require(params["interface_id"] == "SI09" and params["origin_entity_type"] == "material_cost_report", "当前体验仅使用已有采购成本报告", web.HTTPBadRequest)
        view = SupplyQualityAPI(self.store).read(role, "SI09")
        require(any(report["current"]["report_id"] == params["origin_record_id"] and report["baseline"] is not None
                    for row in view["supply"] for report in row["cost_reports"]), "请选择具有两个期间的当前采购报告", web.HTTPConflict)
        key = payload["client_request_id"]
        require(key not in self.active_queries, "原查询正在执行，请读取原编号", web.HTTPConflict)
        self.query_requests.add(key)
        task = asyncio.create_task(super().prepare(role, payload, active))
        self.active_queries[key] = task
        try:
            await task
        finally:
            self.active_queries.pop(key, None)
            self.query_requests.discard(key)
        return self.receipt(role, key, active)

    def receipt(self, role, key, active):
        prepared = self.status(role, {"client_request_id": key}, active)
        state = "SUCCEEDED" if "preparation_sha256" in prepared else prepared["status"]
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            stored = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='mvp_query' AND id=?", (key,)).fetchone()
            snapshot = json.loads(stored[0]) if stored else None
            if snapshot:
                require(all(snapshot[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")), "原查询不属于当前本人资料范围", web.HTTPForbidden)
        current = False
        if snapshot:
            view = SupplyQualityAPI(self.store).read(role, "SI09")
            report = next((report for row in view["supply"] for report in row["cost_reports"] if report["current"]["report_id"] == snapshot["result"]["cost_report"]["current"]["report_id"]), None)
            current = report is not None and checksum(report) == checksum(snapshot["result"]["cost_report"])
            if current:
                with self.store.connect() as db:
                    db.execute("BEGIN")
                    for reference in snapshot["result"]["source_refs"]:
                        document = require_current_business_source(self.store, db, "ui-check", context["owner_id"], reference["source_id"])
                        require(document["version"] == reference["version"] and checksum(document) == reference["source_sha256"], "原查询来源已经变化", web.HTTPConflict)
        return {"client_request_id": key, "request_state": state, "run_id": prepared.get("run_id"),
            "adoption_state": "CURRENT" if current else "HISTORICAL_REQUIRES_REQUERY" if snapshot else "NOT_OBSERVED",
            "origin_reference": {field: snapshot["result"]["coordinate_input"][field] for field in ("origin_record_id", "review_sha256")} if snapshot else None,
            "query": snapshot["result"] if current else None, "preparation": prepared if state == "SUCCEEDED" and current else None,
            "write_performed_by_lookup": False}

    def serve(self, role, path, query_string):
        require(role == "BOSS", "采购查询与原文仅限本人读取", web.HTTPForbidden)
        values = parse_qs(query_string, keep_blank_values=True)
        required = {"client_request_id", "source_id"} if path.endswith("/source") else {"client_request_id"} if path.endswith("/query") else set()
        require(set(values) == required and all(len(value) == 1 and value[0] for value in values.values()), "采购查询字段无效", web.HTTPBadRequest)
        if path == "/api/boss/ui/mvp/history":
            with self.store.connect() as db:
                db.execute("BEGIN")
                context = _context(db)
                rows = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='mvp_query' ORDER BY json_extract(body,'$.result.read_at') DESC")]
            return {"requests": [{"client_request_id": row["result"]["query_id"], "read_at": row["result"]["read_at"], "cost_type": row["result"]["cost_report"]["cost_type"]}
                for row in rows if all(row[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version"))]}
        require(path in {"/api/boss/ui/mvp/query", "/api/boss/ui/mvp/source"}, "采购读取入口不存在", web.HTTPNotFound)
        receipt = self.receipt(role, values["client_request_id"][0], lambda: True)
        if path.endswith("/query"):
            return receipt
        require(receipt["adoption_state"] == "CURRENT", "来源或对象已经变化，请重新查询", web.HTTPConflict)
        source = values["source_id"][0]
        reference = next((reference for reference in receipt["query"]["source_refs"] if reference["source_id"] == source), None)
        require(reference is not None, "来源不属于当前采购查询", web.HTTPForbidden)
        status, document = BossPageAPI(self.store).serve(role, "/api/boss/ui/evidence", urlencode({"source": source}))
        require(status == 200 and document["version"] == reference["version"], "当前原文版本不可采用", web.HTTPConflict)
        return document

    def cancel_query(self, role, key, active):
        require(role == "BOSS" and active(), "取消采购查询需要本人认证", web.HTTPForbidden)
        self.status(role, {"client_request_id": key}, active)
        task = self.active_queries.get(key)
        if task is not None:
            task.cancel()
        return {"client_request_id": key, "cancel_requested": task is not None}
