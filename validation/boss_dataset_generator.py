import calendar
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from random import Random
from zoneinfo import ZoneInfo

import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, initial_materials, require
from boss_supply_quality import SCHEMA

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_VERSION = "business-facts-1"
RELATIONSHIP_VERSION = "supply-quality-1"
SCALES = {"SMALL": (1, "1组业务实体"), "MEDIUM": (4, "4组业务实体"), "LARGE": (16, "16组业务实体")}
PARAMETERS = {"seed", "scale", "period_start", "period_end", "generator_version", "relationship_version"}
TIME_FIELDS = {"observed_at", "valid_from", "valid_until", "quoted_at", "starts_at", "ends_at", "expires_at", "period_start", "period_end", "followup_at", "due_at"}
IMPORT_VALIDATOR = Draft202012Validator({**SCHEMA, "$ref": "#/$defs/ImportInput"}, format_checker=FormatChecker())


def month(value):
    require(isinstance(value, str) and len(value) == 7, "业务期间需要采用YYYY-MM格式", web.HTTPBadRequest)
    result = datetime.strptime(value, "%Y-%m").date()
    require(result.strftime("%Y-%m") == value and 2000 <= result.year <= 2100, "业务期间超出支持范围", web.HTTPBadRequest)
    return result


def parameters(payload):
    require(set(payload) == PARAMETERS, "数据生成条件字段不完整或存在未知字段", web.HTTPBadRequest)
    require(type(payload["seed"]) is int and 0 <= payload["seed"] <= 9007199254740991, "seed需要为有效非负整数", web.HTTPBadRequest)
    require(payload["scale"] in SCALES, "数据规模无效", web.HTTPBadRequest)
    require(payload["generator_version"] == GENERATOR_VERSION and payload["relationship_version"] == RELATIONSHIP_VERSION,
            "生成器或关系配置版本不可用", web.HTTPBadRequest)
    start, end = month(payload["period_start"]), month(payload["period_end"])
    require(start <= end and (end.year - start.year) * 12 + end.month - start.month < 36,
            "业务期间需要为连续1至36个月", web.HTTPBadRequest)
    return deepcopy(payload)


def _transform(value, offset, identities, field=""):
    if isinstance(value, dict):
        return {key: _transform(item, offset, identities, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_transform(item, offset, identities, field) for item in value]
    if not isinstance(value, str):
        return value
    if value in identities:
        return identities[value]
    if (field.endswith("_id") or field.endswith("_ids")) and value.startswith("sim-"):
        return identities["group_prefix"] + value
    if field in TIME_FIELDS:
        if len(value) == 10:
            return (date.fromisoformat(value) + offset).isoformat()
        return (datetime.fromisoformat(value) + offset).isoformat()
    return value


def generate_facts(values):
    values = parameters(values)
    start, last_month = month(values["period_start"]), month(values["period_end"])
    end = last_month.replace(day=calendar.monthrange(last_month.year, last_month.month)[1])
    duration = (end - start).days + 1
    clock = datetime.combine(end + timedelta(days=2), time(9), ZoneInfo("Asia/Shanghai"))
    offset = clock.date() - date(2026, 10, 22)
    template = yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())
    require(template["source_type"] == "SIMULATED" and template["external_services_invoked"] is False,
            "生成资料必须采用获准模拟来源")
    provenance = {"generator_version": GENERATOR_VERSION, "relationship_version": RELATIONSHIP_VERSION,
                  "template_sha256": checksum(template), "schema_sha256": checksum(SCHEMA),
                  "authorization_source": template["authorization_source"], "source_type": "SIMULATED"}
    identifier = "dataset-" + checksum({"parameters": values, "provenance": provenance})[:24]
    initial = initial_materials()
    initial.update({"dataset_id": identifier, "dataset_version": "1", "generator_version": GENERATOR_VERSION,
                    "seed": values["seed"], "business_clock": clock.isoformat(), "memory": None, "private_calendar": None,
                    "periods": {"BASE": [(start - timedelta(days=duration)).isoformat(), (start - timedelta(days=1)).isoformat()],
                                "CURRENT": [start.isoformat(), end.isoformat()]}})
    initial["boss_profile"].update({"goals": [], "confirmed_reading_requirement": ""})
    for contact in initial["contacts"]:
        contact["valid_from"] = (start - timedelta(days=duration + 366)).isoformat()
        contact["valid_until"] = (end + timedelta(days=366)).isoformat()
    for key in ("meeting", "event", "historical_task"):
        initial[key] = _transform(initial[key], offset, {})
        initial[key]["source_type"] = "SIMULATED"
    for document in initial["documents"]:
        document.update({"published_at": (clock - timedelta(hours=1)).isoformat(), "valid_from": (clock - timedelta(hours=1)).isoformat()})
    random = Random(values["seed"])
    details, imports = [], []
    for group in range(1, SCALES[values["scale"]][0] + 1):
        identities = {"group_prefix": f"group-{group}-", "entity-1": f"entity-{group}", "region-1": f"region-{group}",
                      "product-1": f"product-{group * 2 - 1}", "product-2": f"product-{group * 2}",
                      "factory-1": f"factory-{group * 2 - 1}", "factory-2": f"factory-{group * 2}",
                      **{f"customer-{index}": f"customer-{(group - 1) * 4 + index}" for index in range(1, 5)}}
        request = _transform(template["initial_request"], offset, identities)
        request["client_request_id"] = f"{identifier}-group-{group}"
        IMPORT_VALIDATOR.validate(request)
        imports.append(request)
        for period in ("BASE", "CURRENT"):
            for index in range(4):
                quantity = Decimal(random.randint(500, 5000))
                price = Decimal(random.randint(2800, 5200))
                unit_cost = price - Decimal(random.randint(100, 900))
                details.append({"record_id": f"{period}-{group}-{index}", "region_id": identities["region-1"],
                                "product_id": identities[f"product-{index % 2 + 1}"], "legal_entity_id": identities["entity-1"],
                                "customer_id": identities[f"customer-{index + 1}"], "factory_id": identities[f"factory-{index % 2 + 1}"],
                                "period": period, "quantity_tonnes": str(quantity), "revenue_cny": str(quantity * price),
                                "cost_cny": str(quantity * unit_cost), "trade_type": "EXTERNAL_SALES", "version": "1"})
    initial["details"] = details
    for definition in initial["metric_definitions"]:
        definition["scope"] = "EXTERNAL_SALES CNY"
    totals = {period: {field: str(sum(Decimal(row[field]) for row in details if row["period"] == period))
                      for field in ("quantity_tonnes", "revenue_cny", "cost_cny")} for period in initial["periods"]}
    counts = dict(Counter(entry["entity_type"] for request in imports for entry in request["records"]))
    counts.update({"financial_detail": len(details), "initial_contact": len(initial["contacts"]),
                   "initial_document": len(initial["documents"])})
    return {"id": identifier, "version": "1", "parameters": values, "provenance": provenance,
            "initial": initial, "imports": imports, "totals": totals, "counts": counts}
