import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext

from aiohttp import web

from business import checksum, encode, now, require, validate
from boss_source_policy import source_validity
from boss_v7_metrics import apply_configurations, display_rounding, policy_fingerprint, record_adoption

SCOPE_FIELDS = ("legal_entity_id", "currency", "quantity_unit", "trade_scope", "definition_version", "target_version", "business_basis", "settlement_state", "ownership_type", "asset_owner_id", "cost_owner_id", "customer_id")


def _row_scope(row):
    # 既有selection明细的单位与口径由获准定义确定；新增元信息按原值保存。
    return {**row, "currency": row.get("currency", "CNY"), "quantity_unit": row.get("quantity_unit", "tonne"),
            "trade_scope": row["trade_type"], "definition_version": row.get("definition_version", "1"),
            "target_version": row.get("target_version"), "business_basis": row.get("business_basis", "SELECTION_REPORTED"),
            "settlement_state": row.get("settlement_state", "SETTLED")}


def _regions(scope):
    return scope.get("region_ids", [scope["region_id"]])


def _period_rows(data, scope, start, end):
    rows = []
    for original in data["details"]:
        row = _row_scope(original)
        if "source_ids" in scope and row.get("source_id", "finance-note") not in scope["source_ids"]:
            continue
        period = [row.get("period_start"), row.get("period_end")] if "period_start" in row else data["periods"][row["period"]]
        if period != [start, end] or row["region_id"] not in _regions(scope) or row["product_id"] not in scope["product_ids"]:
            continue
        if any(scope.get(field) is not None and row.get(field) != scope[field] for field in SCOPE_FIELDS if field != "settlement_state"):
            continue
        if scope["settlement_state"] != "ALL" and row["settlement_state"] != scope["settlement_state"]:
            continue
        rows.append(original)
    return rows


def _aggregate(rows, scope):
    identifiers = [row["record_id"] for row in rows]
    require(len(identifiers) == len(set(identifiers)), "重复明细不能重复计入指标", web.HTTPBadRequest)
    totals, missing = [], []
    owner_scopes = {tuple(row.get(field) for field in ("ownership_type", "asset_owner_id", "cost_owner_id")) for row in rows}
    if len(owner_scopes) > 1:
        missing.append("INCOMPATIBLE_OWNERSHIP_SCOPE")
    for field in ("quantity_tonnes", "revenue_cny", "cost_cny"):
        if not rows or len(owner_scopes) > 1 or any(row.get(field) is None for row in rows):
            missing.append(field)
            totals.append(None)
        else:
            require(all(isinstance(row[field], str) for row in rows), "数值必须为Decimal字符串", web.HTTPBadRequest)
            values = [Decimal(row[field]) for row in rows]
            require(all(value.is_finite() for value in values), "数值必须有限", web.HTTPBadRequest)
            totals.append(sum(values, Decimal(0)))
    quantity, revenue, cost = totals
    profit = revenue - cost if revenue is not None and cost is not None else None
    money, unit = scope["currency"], scope["quantity_unit"]
    return {"sales_quantity": (quantity, unit, "SUM(quantity_tonnes)"), "revenue": (revenue, money, "SUM(revenue_cny)"),
            "cost": (cost, money, "SUM(cost_cny)"), "gross_profit": (profit, money, "revenue-cost"),
            "gross_margin": (profit / revenue * 100 if profit is not None and revenue else None, "%", "SUM(gross_profit)/SUM(revenue)*100"),
            "gross_profit_per_tonne": (profit / quantity if profit is not None and quantity else None, money + "/" + unit, "SUM(gross_profit)/SUM(quantity_tonnes)")}, missing


def _binding(store, db, ns, data, query):
    binding = store.get(db, ns, "query_source_binding", query["query_id"])
    require(binding["owner_id"] == data["owner_id"] and binding["dataset_id"] == data["dataset_id"]
            and binding["dataset_version"] == data["dataset_version"], "查询范围不符", web.HTTPForbidden)
    return binding


def require_current(store, db, ns, data, query):
    binding = _binding(store, db, ns, data, query)
    require(binding.get("metric_policy_sha256", checksum({})) == policy_fingerprint(db, ns), "指标配置已经变化，需要重新查询")
    if "scenario_id" in binding:
        from boss_bi_scenarios import binding_current
        binding_current(store, db, ns, data, binding)
        return binding
    document = store._metric_source(db, ns, data)
    require(checksum(document) == binding["source_sha256"], "来源已经变化，需要重新查询")
    current = {row["record_id"]: checksum(row) for row in data["details"]}
    require(all(current.get(identifier) == digest for identifier, digest in binding["detail_fingerprints"].items()), "明细已经变化，需要重新查询")
    require(binding["definitions_sha256"] == checksum(data["metric_definitions"]), "指标定义已经变化，需要重新查询")
    return binding


def query_metrics(store, db, ns, data, payload):
    from boss_bi_scenarios import query_inputs
    env = payload["envelope"]
    policy_at = datetime.now(timezone.utc)
    calculations = {}
    digest = checksum(payload)
    receipt_id = checksum({"session_id": env["session_id"], "request_id": env["request_id"]})
    previous = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='bi_query_receipt' AND id=?", (ns, receipt_id)).fetchone()
    if previous:
        receipt = json.loads(previous[0])
        require(receipt["digest"] == digest, "原请求编号的查询内容已经变化")
        query = store.get(db, ns, "query", receipt["query_id"])
        require_current(store, db, ns, data, query)
        return query
    parent_id = payload.get("parent_query_id")
    overridden = []
    if parent_id:
        parent = store.get(db, ns, "query", parent_id)
        require("context_snapshot" in parent and parent["envelope"]["session_id"] == env["session_id"], "追问不属于当前会话", web.HTTPForbidden)
        require_current(store, db, ns, data, parent)
        overridden = sorted(field for field, value in payload.items() if field not in ("envelope", "question", "parent_query_id") and parent["context_snapshot"].get(field) != value)
    # 父查询按自身绑定核查通过后，才读取本次明确选择的资料。
    data, documents = query_inputs(store, db, ns, data, payload)
    start, end = date.fromisoformat(payload["period_start"]), date.fromisoformat(payload["period_end"])
    before, until = date.fromisoformat(payload["comparison_start"]), date.fromisoformat(payload["comparison_end"])
    require(start <= end and before <= until, "查询期间起止顺序无效", web.HTTPBadRequest)
    if "region_ids" in payload:
        require(payload["region_id"] in payload["region_ids"], "当前区域必须包含在明确区域范围内", web.HTTPBadRequest)
    baseline_scope = {**payload, **payload.get("comparison_scope", {})}
    if "region_ids" in baseline_scope:
        require(baseline_scope["region_id"] in baseline_scope["region_ids"], "比较区域必须包含在明确区域范围内", web.HTTPBadRequest)
    reasons = [field for field in SCOPE_FIELDS if payload.get(field) != baseline_scope.get(field)]
    if set(_regions(payload)) != set(_regions(baseline_scope)):
        reasons.append("region_ids")
    if set(payload["product_ids"]) != set(baseline_scope["product_ids"]):
        reasons.append("product_ids")
    if end - start != until - before:
        reasons.append("period_duration")
    if not (until < start or end < before):
        reasons.append("overlapping_periods")
    current_rows = _period_rows(data, payload, payload["period_start"], payload["period_end"])
    baseline_rows = _period_rows(data, baseline_scope, payload["comparison_start"], payload["comparison_end"])
    definitions = {item["metric_id"]: item for item in data["metric_definitions"]}
    if any(definitions[metric]["definition_version"] != payload["definition_version"] for metric in payload["metric_ids"]):
        current_rows = []
    if any(definitions[metric]["definition_version"] != baseline_scope["definition_version"] for metric in payload["metric_ids"]):
        baseline_rows = []
    values, missing, period_values, coverage = [], ["FULL_BUSINESS_COVERAGE_NOT_VERIFIED"], {}, {}
    missing.extend(field + ":UNKNOWN" for field in ("target_version", "ownership_type", "asset_owner_id", "cost_owner_id") if payload.get(field) is None)
    all_rows = {row["record_id"]: row for row in baseline_rows + current_rows}
    if all_rows and payload.get("scenario_id"):
        used_ids = {row["source_id"] for row in all_rows.values()}
        documents = [document for document in documents if document["source_id"] in used_ids]
    document = documents[0]
    with localcontext() as context:
        context.prec = max(80, sum(len(value) for row in all_rows.values() for value in row.values() if isinstance(value, str)))
        for name, rows, scope in (("BASE", baseline_rows, baseline_scope), ("CURRENT", current_rows, payload)):
            metrics, gaps = _aggregate(rows, scope)
            source_metrics = metrics
            metrics, calculations[name] = apply_configurations(db, ns, rows, metrics, cache=True, at=policy_at)
            period_values[name] = metrics
            missing.extend(name + ":" + field for field in gaps)
            missing.extend(name + ":" + identifier + ":" + field for identifier, calculation in calculations[name].items() for field in calculation["missing_fields"])
            if "gross_margin" not in calculations[name] and source_metrics["revenue"][0] == 0:
                missing.append(name + ":gross_margin:ZERO_DENOMINATOR_UNDEFINED")
            if "gross_profit_per_tonne" not in calculations[name] and source_metrics["sales_quantity"][0] == 0:
                missing.append(name + ":gross_profit_per_tonne:ZERO_DENOMINATOR_UNDEFINED")
            coverage[name] = {"record_count": len(rows), "region_ids": sorted({row["region_id"] for row in rows}),
                              "period_start": payload["comparison_start"] if name == "BASE" else payload["period_start"],
                              "period_end": payload["comparison_end"] if name == "BASE" else payload["period_end"]}
            for metric in payload["metric_ids"]:
                value, unit, formula = metrics[metric]
                if definitions[metric]["definition_version"] != scope["definition_version"]:
                    formula = "DEFINITION_NOT_PROVIDED"
                    missing.append(name + ":definition_version:UNKNOWN")
                metric_scope = {key: value for key, value in scope.items() if key not in ("envelope", "question")}
                if metric in calculations[name]:
                    metric_scope["metric_configuration"] = {key: calculations[name][metric][key] for key in ("configuration_version", "scope", "breakdown")}
                values.append({"metric_id": metric, "period_scope": name, "scope_description": encode(metric_scope),
                               "value": format(value, "f") if value is not None else None, "unit": unit, "formula": formula,
                               "definition_version": scope["definition_version"], "display_rounding": display_rounding(calculations[name][metric]) if metric in calculations[name] else "原始Decimal字符串；展示四舍五入不得覆盖原值"})
        missing_regions = sorted(set(_regions(payload)) - {row["region_id"] for row in current_rows})
        delayed = sorted({row["region_id"] for row in current_rows if row.get("sync_state") == "DELAYED"})
        unsynchronized = sorted({row["region_id"] for row in current_rows if row.get("sync_state") == "UNSYNCHRONIZED"})
        sync_known = bool(current_rows) and all("sync_state" in row for row in current_rows)
        if not sync_known:
            missing.append("COVERAGE_TIMELINESS_NOT_PROVIDED")
        baseline_regions = {row["region_id"] for row in baseline_rows}
        if missing_regions or delayed or unsynchronized or set(_regions(baseline_scope)) - baseline_regions or any(row.get("sync_state") in ("DELAYED", "UNSYNCHRONIZED") for row in baseline_rows):
            reasons.append("incomplete_coverage")
        for metric in payload["metric_ids"]:
            base, _, _ = period_values["BASE"][metric]
            current, _, _ = period_values["CURRENT"][metric]
            if metric != "gross_margin" and base == 0:
                missing.append("CHANGE:" + metric + ":ZERO_BASE_UNDEFINED")
            value = None
            if not reasons and base is not None and current is not None:
                value = current - base if metric == "gross_margin" else (current - base) / base * 100 if base else None
            values.append({"metric_id": metric, "period_scope": "CHANGE", "scope_description": "当前查询与比较范围",
                           "value": format(value, "f") if value is not None else None, "unit": "百分点" if metric == "gross_margin" else "%",
                           "formula": "current-base" if metric == "gross_margin" else "(current-base)/base*100",
                           "definition_version": payload["definition_version"], "display_rounding": "原始Decimal精度"})
    known_periods = all(any(period_values[name][metric][0] is not None for metric in payload["metric_ids"]) for name in ("BASE", "CURRENT"))
    state = "INCOMPARABLE" if reasons else "COMPARABLE" if known_periods else "INSUFFICIENT_EVIDENCE"
    result = {"query_id": str(uuid.uuid4()), "envelope": env, "values": values, "detail_refs": list(all_rows),
              "sources": [{**store.source(item, data, "INCOMPLETE"), **({"coverage": item["coverage"]} if payload.get("scenario_id") else {})} for item in documents], "missing_fields": missing,
              "unexplained_causes": ["原因贡献明细尚未提供"], "context_snapshot": payload,
              "coverage": {"state": "PARTIAL" if all_rows else "UNAVAILABLE", "periods": coverage, "missing_regions": missing_regions,
                           "delayed_regions": delayed if sync_known else None, "unsynchronized_regions": unsynchronized if sync_known else None},
              "comparison": {"state": state, "reasons": reasons}, "parent_query_id": parent_id,
              "overridden_fields": overridden, "source_type": "SIMULATED", "queried_at": now()}
    validate("scoped_query_output", result)
    store.put(db, ns, "query", result["query_id"], result)
    store.put(db, ns, "query_source_binding", result["query_id"], {
        "query_id": result["query_id"], "owner_id": data["owner_id"], "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"],
        "source_id": document["source_id"], "source_version": document["version"], "source_sha256": checksum(document),
        "definitions_sha256": checksum(data["metric_definitions"]), "detail_fingerprints": {identifier: checksum(row) for identifier, row in all_rows.items()},
        "metric_policy_sha256": policy_fingerprint(db, ns, policy_at), "metric_calculations": calculations,
        "original_records": list(all_rows.values()), "document_snapshot": document,
        **({"scenario_id": payload["scenario_id"], "document_snapshots": documents} if payload.get("scenario_id") else {})})
    store.put(db, ns, "bi_query_receipt", receipt_id, {"digest": digest, "query_id": result["query_id"], "session_id": env["session_id"], "request_id": env["request_id"]})
    record_adoption(store, db, ns, result["query_id"], calculations)
    return result


def read_evidence(store, db, ns, data, payload, query):
    require(set(payload["detail_refs"]) <= set(query["detail_refs"]) and set(payload["source_ids"]) <= {item["source_id"] for item in query["sources"]}, "依据范围不符", web.HTTPForbidden)
    require(len(payload["detail_refs"]) == len(set(payload["detail_refs"])), "依据明细重复", web.HTTPBadRequest)
    binding = require_current(store, db, ns, data, query)
    rows = [row for row in binding["original_records"] if row["record_id"] in payload["detail_refs"]]
    documents = binding.get("document_snapshots", [binding["document_snapshot"]])
    documents = [document for document in documents if document["source_id"] in payload["source_ids"]]
    require(all(row.get("source_id", "finance-note") in payload["source_ids"] for row in rows), "明细与所选来源不符", web.HTTPForbidden)
    return {"sources": [item for item in query["sources"] if item["source_id"] in payload["source_ids"]], "original_records": [{"record_id": row["record_id"], "version": row["version"], "content": row} for row in rows]
            + [{"record_id": document["source_id"], "version": document["version"], "content": document} for document in documents],
            "definition_version": query["context_snapshot"]["definition_version"], "conflicts": query["comparison"]["reasons"], "missing_fields": query["missing_fields"]}


class BIQueryAPI:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _role(role):
        require(role in ("BOSS", "MAINTAINER"), "当前尚未认证", web.HTTPUnauthorized)
        require(role == "BOSS", "当前身份不能读取经营查询", web.HTTPForbidden)

    def query(self, role, payload):
        self._role(role)
        validate("scoped_query_input", payload)
        return self.store.invoke("query_metrics", payload)

    def dimensions(self, role, scenario_id=None, source_ids=None):
        self._role(role)
        selection = {**({"scenario_id":scenario_id} if scenario_id is not None else {}), **({"source_ids":source_ids} if source_ids is not None else {})}
        validate("scope_fields",selection)
        from boss_simulation_api import _context
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            data = self.store.get(db, context["namespace"], "initial", "snapshot")
            from boss_bi_scenarios import query_inputs
            data, documents = query_inputs(self.store, db, context["namespace"], data, selection)
            document = documents[0]
            rows = [_row_scope(row) for row in data["details"]]
            return {"source_type": "SIMULATED", "available_dimensions": {field: sorted({row[field] for row in rows if row.get(field) is not None})
                    for field in ("region_id", "product_id", *SCOPE_FIELDS)}, "periods": data["periods"], "metric_definitions": data["metric_definitions"],
                    "source_id": document["source_id"], "source_version": document["version"], "coverage_state": "PARTIAL",
                    **({"scenario_id": scenario_id, "source_ids": [item["source_id"] for item in documents]} if scenario_id is not None else {}),
                    "missing_fields": ["FULL_BUSINESS_COVERAGE_NOT_VERIFIED", "TARGET_VERSION_NOT_PROVIDED", "OWNERSHIP_NOT_PROVIDED"]}

    def follow_up(self, role, payload):
        self._role(role)
        validate("bi_follow_up", payload)
        with self.store.connect() as db:
            ns = payload["envelope"]["execution_namespace"]
            self.store.active(db, ns)
            parent = self.store.get(db, ns, "query", payload["parent_query_id"])
            require("context_snapshot" in parent, "当前查询缺少可继承快照")
        current = {**parent["context_snapshot"], **payload["overrides"], "envelope": payload["envelope"],
                   "question": payload["question"], "parent_query_id": payload["parent_query_id"]}
        return self.store.invoke("query_metrics", current)

    def read(self, role, query_id, historical=False):
        self._role(role)
        validate("identifier", query_id)
        require(type(historical) is bool, "历史读取标识格式无效", web.HTTPBadRequest)
        from boss_simulation_api import _context
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            ns = context["namespace"]
            data = self.store.get(db, ns, "initial", "snapshot")
            query = self.store.get(db, ns, "query", query_id)
            require("context_snapshot" in query, "当前查询没有正式范围快照")
            binding = _binding(self.store, db, ns, data, query)
            if not historical:
                require_current(self.store, db, ns, data, query)
                result = {"adoption_state": "CURRENT", "result": query}
                validate("bi_read", result)
                return result
            if "scenario_id" in binding:
                from boss_bi_scenarios import binding_current
                valid = binding_current(self.store, db, ns, data, binding, enforce=False) and binding.get("metric_policy_sha256", checksum({})) == policy_fingerprint(db, ns)
                result = {"adoption_state": "HISTORICAL_CURRENT" if valid else "HISTORICAL_REQUIRES_REQUERY", "result": query}
                validate("bi_read", result)
                return result
            document = self.store.get(db, ns, "document", binding["source_id"])
            require(document["access_scope"] == data["owner_id"], "当前来源无权访问", web.HTTPForbidden)
            clock = self.store.get(db, ns, "clock", "current")["at"]
            valid = source_validity(document, clock) == "VALID" and checksum(document) == binding["source_sha256"]
            current = {row["record_id"]: checksum(row) for row in data["details"]}
            valid = valid and binding["definitions_sha256"] == checksum(data["metric_definitions"]) and all(current.get(key) == value for key, value in binding["detail_fingerprints"].items())
            valid = valid and binding.get("metric_policy_sha256", checksum({})) == policy_fingerprint(db, ns)
            result = {"adoption_state": "HISTORICAL_CURRENT" if valid else "HISTORICAL_REQUIRES_REQUERY", "result": query}
            validate("bi_read", result)
            return result

    def receipt(self, role, session_id, request_id):
        self._role(role)
        validate("identifier", session_id)
        validate("identifier", request_id)
        from boss_simulation_api import _context
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            identifier = checksum({"session_id": session_id, "request_id": request_id})
            row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='bi_query_receipt' AND id=?", (context["namespace"], identifier)).fetchone()
            receipt = json.loads(row[0]) if row else None
        result = {"request_id": request_id, "session_id": session_id, "outcome": "RECORDED" if receipt else "NOT_FOUND_IN_CURRENT_STORE",
                  "query": self.read(role, receipt["query_id"], historical=True) if receipt else None}
        validate("bi_receipt", result)
        return result
