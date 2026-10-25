import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, now, require
from boss_bi_queries import _aggregate, _period_rows
from boss_sector_api import SECTORS
from boss_simulation_api import SimulationAPI, _context
from boss_source_policy import source_validity
from boss_supply_quality import external_adoption
from boss_business_alerts import BusinessAlertsAPI


SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "specs/business-overview.schema.json").read_text())
TOPICS = tuple("F" + str(index) for index in range(14, 24))
KINDS = {"F14": {"material_quote", "material_contract", "inventory_lot", "material_consumption", "material_cost_report", "feed_formula"},
         "F21": {"production_batch", "quality_trace", "professional_record", "customer_feedback", "production_event"}}
GAPS = {
    "F14": ["COMPLETE_MARKET_CONTRACT_RECEIPT_CONSUMPTION_AND_FORMULA_SCOPE_REQUIRED"],
    "F15": ["SPECIES_STAGE_CYCLE_ORDERS_FORECAST_CUSTOMER_RETURN_AND_OBSERVATION_DENOMINATOR_REQUIRED"],
    "F16": ["SEED_BATCH_DELIVERY_AND_CULTURE_BATCH_RELATION_WITH_SAMPLE_DENOMINATOR_REQUIRED"],
    "F17": ["VETERINARY_AUTHOR_APPLICABILITY_CONFIRMATION_EXECUTION_AND_FOLLOWUP_REQUIRED"],
    "F18": ["PIG_COOPERATION_OWNERSHIP_COST_BALANCE_AND_SETTLEMENT_PERIOD_REQUIRED"],
    "F19": ["BROILER_EGG_MILK_BEEF_PURPOSE_STAGE_UNIT_AND_OBSERVATION_SCOPE_REQUIRED"],
    "F20": ["COMPANY_AQUACULTURE_UNIT_DEVICE_BATCH_AND_OBSERVATION_RELATION_REQUIRED"],
    "F21": ["COMPLETE_COMPLAINT_TRACE_SCOPE_AND_CURRENT_PROFESSIONAL_REVIEW_REQUIRED"],
    "F22": ["OVERSEAS_ENTITY_COUNTRY_LOCAL_GROUP_PERIOD_CURRENCY_FX_SOURCE_AND_PROCESS_CAPACITY_REQUIRED"],
    "F23": ["EXPERIMENT_CONTROL_SAMPLE_PERIOD_REVIEW_AUTHOR_AND_APPLICABILITY_REQUIRED"],
}


def validate(name, value):
    require(not list(Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}, format_checker=FormatChecker()).iter_errors(value)),
            "经营总览输入输出不符合Schema", web.HTTPBadRequest)
    return value


def owner(role):
    require(role is not None, "本人尚未认证", web.HTTPUnauthorized)
    require(role == "BOSS", "经营总览仅限本人读取", web.HTTPForbidden)


class BusinessOverviewAPI:
    def __init__(self, store):
        self.store, self.simulation = store, SimulationAPI(store)

    def dimensions(self, role):
        owner(role)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            data = self.store.get(db, context["namespace"], "initial", "snapshot")
            return self._dimensions(data, self._external(db, context))

    @staticmethod
    def _dimensions(data, records):
        bodies = [row["data"]["data"] for row in records]
        periods = [{"id": key, "period_start": value[0], "period_end": value[1]} for key, value in data["periods"].items()]
        for body in bodies:
            if body.get("period_start") and body.get("period_end"):
                dates = {key: datetime.fromisoformat(body[key]).astimezone(ZoneInfo(data["boss_profile"]["timezone"])).date().isoformat() for key in ("period_start", "period_end")}
                if not any(all(row[key] == value for key, value in dates.items()) for row in periods):
                    periods.append({"id": "recorded-" + checksum(dates), **dates})
        return {"source_type": "SIMULATED", "legal_entity_ids": sorted({row["legal_entity_id"] for row in data["details"]} | {row["legal_entity_id"] for row in bodies if row.get("legal_entity_id")}),
            "region_ids": sorted({row["region_id"] for row in data["details"]} | {row["region_id"] for row in bodies if row.get("region_id")}),
            "periods": periods,
            "timezones": [data["boss_profile"]["timezone"]], "attention_values": ["ALL", "OWNER_INVOLVEMENT", "SOURCE_REVIEW"],
            "region_null_meaning": "NO_REGION_RESTRICTION", "dimension_coverage": "APPROVED_RECORD_METADATA; CURRENT_VALUES_REVALIDATED_ON_READ"}

    def _external(self, db, context):
        records = []
        for interface in ("SI09", "SI10"):
            records.extend(self.simulation._records(db, context, {"interface_id": interface, "object_ids": [], "filters": {}}, technical=False))
        for row in records:
            wrapper = row["data"]
            require(all(wrapper[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")) and wrapper["execution_namespace"] == context["namespace"], "专题对象不属于当前范围", web.HTTPForbidden)
        return records

    def read(self, role, scope):
        owner(role)
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self.project_in_transaction(role, db, scope)

    def project_in_transaction(self, role, db, scope):
        owner(role)
        validate("Scope", scope)
        context = _context(db)
        ns = context["namespace"]
        data = self.store.get(db, ns, "initial", "snapshot")
        records = self._external(db, context)
        dimensions = self._dimensions(data, records)
        require(scope["legal_entity_id"] in dimensions["legal_entity_ids"] and (scope["region_id"] is None or scope["region_id"] in dimensions["region_ids"]), "法人或区域不在当前获准范围", web.HTTPBadRequest)
        require(scope["timezone"] in dimensions["timezones"] and any([scope["period_start"], scope["period_end"]] == [row["period_start"],row["period_end"]] for row in dimensions["periods"]), "期间或时区不属于当前接口已验证范围", web.HTTPBadRequest)
        sources = {}
        def source(identifier):
            if identifier not in sources:
                found = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=? AND json_extract(body,'$.access_scope')=? AND json_extract(body,'$.source_id')=? AND json_extract(body,'$.source_type')='SIMULATED'", (ns, identifier, context["owner_id"], identifier)).fetchone()
                doc = json.loads(found[0]) if found else None
                state = source_validity(doc, context["clock"]) if doc else "MISSING_OR_FORBIDDEN"
                if state == "VALID" and external_adoption(db, ns, data, context["clock"], doc)["state"] == "NEEDS_REIMPORT":
                    state = "NEEDS_REVIEW"
                sources[identifier] = {"source_id": identifier, "version": doc["version"] if doc else None, "status": state,
                    "sha256": checksum(doc) if doc else None, "metadata": {key: doc.get(key) for key in
                        ("source_type", "author_contact_id", "author_kind", "author_display_name", "published_at", "observed_at", "valid_from", "valid_until", "coverage", "original_locator")} if state == "VALID" else None}
            return sources[identifier]
        finance_matches = any(row["legal_entity_id"] == scope["legal_entity_id"] and (scope["region_id"] is None or row["region_id"] == scope["region_id"]) for row in data["details"])
        finance = source("finance-note") if finance_matches else {"status": "OUTSIDE_SELECTED_SCOPE", "version": None}
        metric_scope = {"legal_entity_id": scope["legal_entity_id"], "region_id": scope["region_id"] or data["details"][0]["region_id"],
            "region_ids": dimensions["region_ids"] if scope["region_id"] is None else [scope["region_id"]],
            "product_ids": sorted({row["product_id"] for row in data["details"]}), "currency": "CNY", "quantity_unit": "tonne",
            "trade_scope": "EXTERNAL_SALES", "definition_version": "1", "business_basis": "SELECTION_REPORTED", "settlement_state": "SETTLED"}
        selected = _period_rows(data, metric_scope, scope["period_start"], scope["period_end"]) if finance["status"] == "VALID" else []
        missing_regions = sorted(set(metric_scope["region_ids"]) - {row["region_id"] for row in selected})
        values, missing = _aggregate(selected, metric_scope)
        if finance["status"] != "VALID":
            missing.append("FINANCE_SOURCE_" + finance["status"])
        elif not selected:
            missing.append("NO_EXTERNAL_SALES_ROWS_FOR_SELECTED_SCOPE")
        as_of = datetime.combine(date.fromisoformat(scope["period_end"]), time(23, 59, 59), ZoneInfo(scope["timezone"])).isoformat()
        metrics = [{"metric_id": key, "value": str(value) if value is not None else None, "unit": unit, "formula": formula,
            "definition_version": "1", "precision": "DECIMAL_UNROUNDED", "business_as_of": as_of, "source_refs": [{"source_id": "finance-note", "version": finance["version"]}] if selected else []}
            for key, (value, unit, formula) in values.items()]
        raw = {(row["entity_type"], row["object_id"]): row["data"]["data"] for row in records}
        def entities(kind, body):
            if body.get("legal_entity_id"):
                return {body["legal_entity_id"]}
            linked = []
            for field, target in (("batch_id", "production_batch"), ("input_batch_id", "production_batch"), ("output_batch_id", "production_batch"), ("inventory_id", "inventory_lot")):
                if body.get(field) and (target, body[field]) in raw:
                    linked.append(raw[target, body[field]].get("legal_entity_id"))
            return {value for value in linked if value is not None}
        scoped = []
        excluded = []
        for row in records:
            wrapper, body = row["data"], row["data"]["data"]
            require(all(wrapper[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")) and wrapper["execution_namespace"] == ns, "专题对象不属于当前范围", web.HTTPForbidden)
            if entities(row["entity_type"], body) != {scope["legal_entity_id"]} or scope["region_id"] is not None and body.get("region_id") != scope["region_id"]:
                excluded.append({"kind": row["entity_type"], "reason": "ENTITY_OR_REGION_NOT_PROVEN"})
                continue
            self.simulation._protect(db, context, row)
            refs = row["source_refs"]
            for ref in refs:
                source(ref["source_id"])
            scoped.append({"kind": row["entity_type"], "id": row["object_id"], "version": row["version"], "state": row["state"],
                "adoption_state": "CURRENT" if row["data"] is not None else "NEEDS_REVIEW", "source_refs": refs,
                "facts": {key: body[key] for key in ("ownership_type", "asset_owner_id", "cost_owner_id", "quantity_unit", "currency", "trace_state", "inspection_state", "professional_state", "period_start", "period_end") if key in body} if row["data"] is not None else None})
        topics = []
        def latest(values):
            values = [value for value in values if value is not None]
            return max(values, key=lambda value: datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(scope["timezone"])) if datetime.fromisoformat(value).tzinfo is None else datetime.fromisoformat(value)) if values else None
        for page in TOPICS:
            title, filters, labels = SECTORS[page]
            related = [row for row in scoped if row["kind"] in KINDS.get(page, set())]
            had_records = bool(related)
            if scope["attention"] == "SOURCE_REVIEW":
                related = [row for row in related if row["adoption_state"] != "CURRENT"]
            if scope["attention"] == "OWNER_INVOLVEMENT":
                related = []
            topic_sources = sorted({ref["source_id"] for row in related for ref in row["source_refs"]})
            timestamps = [sources[sid]["metadata"].get("observed_at") for sid in topic_sources if sources[sid]["metadata"]]
            topics.append({"page_id": page, "title": title, "purpose": {"filters": filters, "indicators": labels},
                "availability": "PARTIAL" if any(row["adoption_state"] == "CURRENT" for row in related) else "NEEDS_REVIEW" if related else "FILTER_EMPTY" if had_records else "SOURCE_NOT_AVAILABLE",
                "data_as_of": latest(timestamps), "latest_source_published_at": latest([sources[sid]["metadata"].get("published_at") for sid in topic_sources if sources[sid]["metadata"]]), "records": related, "missing_fields": GAPS[page],
                "scope_application": "CURRENT_SNAPSHOT_AT_BUSINESS_CLOCK; PERIOD_IS_NOT_A_FLOW_AGGREGATION",
                "related_sales_source_refs": [{"source_id": "finance-note", "version": finance["version"]}] if page == "F14" and finance["status"] == "VALID" else [],
                "uses": ["BROILER", "EGG", "MILK", "BEEF"] if page == "F19" else []})
        alerts = BusinessAlertsAPI(self.store).project_in_transaction("BOSS", db)["items"]
        matching_alerts = []
        alert_exclusions = {"scope": 0, "attention": 0}
        for alert in alerts:
            facts = self.store.get(db, ns, "event", alert["event_id"])["facts"]
            scope_known = facts is not None and facts["comparison_periods"]["CURRENT"] == [scope["period_start"], scope["period_end"]] and all(
                row["legal_entity_id"] == scope["legal_entity_id"] and (scope["region_id"] is None or row["region_id"] == scope["region_id"]) for row in data["details"])
            if not scope_known:
                alert_exclusions["scope"] += 1
                continue
            if scope["attention"] == "SOURCE_REVIEW" and alert["adoption_state"] == "CURRENT" or scope["attention"] == "OWNER_INVOLVEMENT" and facts["participation"] == "INFORM_ONLY":
                alert_exclusions["attention"] += 1
                continue
            matching_alerts.append(alert)
            for ref in alert["sources"]:
                source(ref["source_id"])
        associations = []
        selected_ids = {ref["source_id"] for row in scoped for ref in row["source_refs"]}
        if all(row["legal_entity_id"] == scope["legal_entity_id"] and (scope["region_id"] is None or row["region_id"] == scope["region_id"]) for row in data["details"]):
            selected_ids.add("finance-note")
        tasks = self.simulation.project_in_transaction("BOSS", db, {"interface_id": "SI06", "object_ids": [], "filters": {}})["records"]
        for task in tasks:
            if task["entity_type"] != "task" or not any(ref["source_id"] in selected_ids for ref in task["source_refs"]):
                continue
            if scope["attention"] == "SOURCE_REVIEW" and task["content_state"] != "NEEDS_REVIEW":
                continue
            if scope["attention"] == "OWNER_INVOLVEMENT" and task["object_id"] not in {measure["task_id"] for alert in matching_alerts for measure in alert["existing_measures"] if measure["kind"] == "task"}:
                continue
            associations.append({"kind": "task", "id": task["object_id"], "version": task["version"], "state": task["state"],
                "adoption_state": task["content_state"], "source_refs": task["source_refs"], "relation": "EXPLICIT_SOURCE_REFERENCE"})
        handoff = {**metric_scope, "period_start": scope["period_start"], "period_end": scope["period_end"],
            "comparison_start": data["periods"]["BASE"][0], "comparison_end": data["periods"]["BASE"][1], "source_ids": ["finance-note"]} if selected and not missing_regions and [scope["period_start"], scope["period_end"]] == data["periods"]["CURRENT"] else None
        result = {"source_type": "SIMULATED", "projection": "business-overview", "applied_scope": scope, "dimensions": dimensions,
            "scope_application": {"metrics": "EXACT_SELECTED_PERIOD; ATTENTION_INDEPENDENT_SCOPE_CONTEXT", "topics": "CURRENT_SNAPSHOT; ATTENTION_FILTERED", "alerts": "EXACT_CURRENT_COMPARISON_PERIOD_AND_SELECTION_FINANCE_SCOPE; ATTENTION_FILTERED", "associations": "EXPLICIT_SOURCES; NOT_TASK_CREATION_PERIOD; ATTENTION_FILTERED"},
            "metrics": metrics, "metric_missing_fields": missing, "metric_scope": "WATER_FEED_EXTERNAL_SALES_ONLY", "query_handoff": handoff,
            "query_handoff_unavailable_reason": None if handoff else "FINANCE_SOURCE_" + finance["status"] if finance["status"] != "VALID" else "NO_EXTERNAL_SALES_ROWS_FOR_SCOPE" if not selected else "REGION_COVERAGE_INCOMPLETE" if missing_regions else "NO_PRIOR_COMPARISON_PERIOD",
            "metric_coverage": {"state": "UNAVAILABLE" if not selected else "PARTIAL" if missing_regions else "SCOPED_AVAILABLE", "missing_region_ids": missing_regions,
                "record_refs": [{"record_id": row["record_id"], "version": row["version"]} for row in selected]},
            "topics": topics, "alerts": matching_alerts, "associations": associations, "sources": list(sources.values()), "excluded_records": excluded,
            "alert_scope_exclusions": alert_exclusions,
            "unclassified_records": [{"record": row, "reason": "TOPIC_APPLICABILITY_NOT_PROVEN"} for row in scoped if row["kind"] not in set().union(*KINDS.values())],
            "business_at": context["clock"], "read_at": now(), "coverage_state": "PARTIAL",
            "business_authorization_granted": False, "business_mutation_performed": False}
        result["snapshot_sha256"] = checksum({"context": context, "initial": data, "result": {key: value for key, value in result.items() if key != "read_at"}})
        return validate("View", result)

    def detail(self, role, payload):
        owner(role)
        validate("Detail", payload)
        result = self.read(role, payload["scope"])
        require(result["snapshot_sha256"] == payload["snapshot_sha256"], "经营范围或来源版本已经变化", web.HTTPConflict)
        return {"source_type": "SIMULATED", "applied_scope": result["applied_scope"], "snapshot_sha256": result["snapshot_sha256"],
            "topic": next(row for row in result["topics"] if row["page_id"] == payload["page_id"]),
            "sources": result["sources"], "business_at": result["business_at"], "read_at": result["read_at"],
            "business_authorization_granted": False, "business_mutation_performed": False}
