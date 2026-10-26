from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

from aiohttp import web

from business import checksum, encode, now, require
from boss_v7_store import NAMESPACE, optional, rows, text

METRICS = {
    "sales_quantity": ("销量", "SUM(quantity_tonnes)", "吨"),
    "revenue": ("收入", "SUM(revenue_cny)", "CNY"),
    "cost": ("成本", "SUM(cost_cny)", "CNY"),
    "gross_profit": ("毛利", "SUM(revenue_cny)-SUM(cost_cny)", "CNY"),
    "gross_margin": ("毛利率", "(SUM(revenue_cny)-SUM(cost_cny))/SUM(revenue_cny)*100", "%"),
    "gross_profit_per_tonne": ("单吨毛利", "(SUM(revenue_cny)-SUM(cost_cny))/SUM(quantity_tonnes)", "CNY/吨"),
}
DIMENSIONS = ("region_id", "product_id", "legal_entity_id", "period")
SCOPES = ("EXTERNAL_SALES", "EXTERNAL_SALES_SETTLED")
GROUP_FIELDS = ("period", "period_start", "period_end", "region_id", "legal_entity_id", "currency", "quantity_unit",
                "trade_type", "business_basis", "ownership_type", "asset_owner_id", "cost_owner_id")


def builtin_metric(identifier):
    require(identifier in METRICS, "指标不存在", web.HTTPBadRequest)
    title, formula, unit = METRICS[identifier]
    values = {"name": title, "metric_id": identifier, "formula": formula, "unit": unit,
              "dimensions": list(DIMENSIONS), "scope": "EXTERNAL_SALES", "precision": None,
              "effective_at": None, "refresh_seconds": None, "change_note": "当前经营明细提供的指标定义"}
    return {"version": "builtin-1", "values": values, "content_sha256": checksum(values), "state": "BUILTIN", "created_at": None}


def options():
    return {"metric_ids": [{"id": identifier, "label": item[0]} for identifier, item in METRICS.items()],
            "formulas": [{"id": item[1], "label": item[0] + " · " + item[1]} for item in METRICS.values()],
            "dimensions": [{"id": name, "label": label} for name, label in zip(DIMENSIONS, ("区域", "产品", "法人", "期间"))],
            "units": [{"id": unit, "label": unit} for unit in sorted({item[2] for item in METRICS.values()})],
            "metric_scopes": [{"id": "EXTERNAL_SALES", "label": "外销明细"}, {"id": "EXTERNAL_SALES_SETTLED", "label": "已结算外销明细"}]}


def validate_values(values):
    identifier = values.get("metric_id")
    require(isinstance(identifier, str) and identifier in METRICS, "指标不存在", web.HTTPBadRequest)
    require(set(values) == set(builtin_metric(identifier)["values"]), "指标配置字段无效", web.HTTPBadRequest)
    require(values["formula"] == METRICS[identifier][1] and values["unit"] == METRICS[identifier][2],
            "公式和单位需要符合当前指标的业务定义", web.HTTPBadRequest)
    require(isinstance(values["dimensions"], list) and values["dimensions"]
            and all(isinstance(field, str) and field in DIMENSIONS for field in values["dimensions"])
            and len(set(values["dimensions"])) == len(values["dimensions"]), "指标维度无效", web.HTTPBadRequest)
    require(values["scope"] in SCOPES, "统计范围无效", web.HTTPBadRequest)
    require(type(values["precision"]) is int and 0 <= values["precision"] <= 8, "显示精度无效", web.HTTPBadRequest)
    require(type(values["refresh_seconds"]) is int and 1 <= values["refresh_seconds"] <= 86400, "刷新间隔无效", web.HTTPBadRequest)
    effective = datetime.fromisoformat(text(values["effective_at"], "生效时间", 80))
    require(effective.tzinfo is not None, "生效时间需要包含时区", web.HTTPBadRequest)
    return values


def effective_configuration(db, namespace, identifier, at=None):
    at = at or datetime.now(timezone.utc)
    versions = [record for record in rows(db, "technical_revision", namespace)
                if record["domain"] == "metrics" and record["object_id"] == identifier and record["state"] == "ACTIVE"
                and datetime.fromisoformat(record["values"]["effective_at"]) <= at]
    return max(versions, key=lambda record: int(record["version"])) if versions else None


def policy_fingerprint(db, namespace, at=None):
    at = at or datetime.now(timezone.utc)
    return checksum({identifier: record["content_sha256"] for identifier in METRICS
                     if (record := effective_configuration(db, namespace, identifier, at)) is not None})


def selected_rows(records, values):
    return [row for row in records if row["trade_type"] == "EXTERNAL_SALES"
            and (values["scope"] == "EXTERNAL_SALES" or row.get("settlement_state", "SETTLED") == "SETTLED")]


def calculate(records, identifier, rational=False):
    require(identifier in METRICS, "指标不存在", web.HTTPBadRequest)
    ids = [row["record_id"] for row in records]
    require(len(ids) == len(set(ids)), "重复明细不能重复计入指标", web.HTTPBadRequest)
    zero = Fraction(0) if rational else Decimal(0)
    totals = {}
    for field in ("quantity_tonnes", "revenue_cny", "cost_cny"):
        if not records or any(row.get(field) is None for row in records):
            totals[field] = None
            continue
        require(all(isinstance(row[field], str) for row in records), "原始数值需要使用Decimal字符串", web.HTTPBadRequest)
        numbers = [Decimal(row[field]) for row in records]
        require(all(number.is_finite() for number in numbers), "经营数值必须有限", web.HTTPBadRequest)
        totals[field] = sum((Fraction(number) if rational else number for number in numbers), zero)
    quantity, revenue, cost = (totals[field] for field in ("quantity_tonnes", "revenue_cny", "cost_cny"))
    if identifier == "sales_quantity":
        return quantity
    if identifier == "revenue":
        return revenue
    if identifier == "cost":
        return cost
    profit = revenue - cost if revenue is not None and cost is not None else None
    if identifier == "gross_profit":
        return profit
    denominator = revenue if identifier == "gross_margin" else quantity
    return profit * (100 if identifier == "gross_margin" else 1) / denominator if profit is not None and denominator else None


def recompute(snapshot, values):
    validate_values(values)
    records = selected_rows(snapshot["details"], values)
    require(records, "当前统计范围没有可复算明细", web.HTTPBadRequest)
    groups = defaultdict(list)
    for row in records:
        groups[tuple(row.get(field) for field in GROUP_FIELDS)].append(row)
    checks = []
    with localcontext() as context:
        context.prec = max(80, sum(len(value) for row in records for value in row.values() if isinstance(value, str)))
        for index, group in enumerate(groups.values()):
            decimal_value = calculate(group, values["metric_id"])
            exact = calculate(group, values["metric_id"], rational=True)
            expected = Decimal(exact.numerator) / Decimal(exact.denominator) if exact is not None else None
            require(decimal_value == expected, "Decimal计算与有理数独立复算结果不一致")
            checks.append({"name": "原始明细复算 " + str(index + 1), "state": "PASSED",
                           "message": encode({"detail_refs": [row["record_id"] for row in group],
                                              "value": str(decimal_value) if decimal_value is not None else None,
                                              "unit": values["unit"], "formula": values["formula"], "independent_method": "fractions.Fraction"})})
    return {"state": "PASSED", "checked_at": now(), "input_sha256": checksum(snapshot["details"]), "checks": checks}


def apply_configurations(db, namespace, records, metrics, *, cache=False, at=None):
    result, adopted = dict(metrics), {}
    at = at or datetime.now(timezone.utc)
    with localcontext() as context:
        context.prec = max(80, sum(len(value) for row in records for value in row.values() if isinstance(value, str)))
        for identifier in metrics:
            policy = effective_configuration(db, namespace, identifier, at)
            if policy is None:
                continue
            values = policy["values"]
            selected = selected_rows(records, values)
            units_match = metrics[identifier][1] == values["unit"] or (values["unit"], metrics[identifier][1]) in {("吨", "tonne"), ("CNY/吨", "CNY/tonne")}
            inputs = {"policy": policy["content_sha256"], "records": selected, "unit": metrics[identifier][1], "input_available": metrics[identifier][0] is not None, "units_match": units_match}
            cache_id = checksum(inputs)
            calculation = optional(db, "metric_calculation", cache_id, namespace) if cache else None
            if calculation is None or datetime.fromisoformat(calculation["next_refresh_at"]) <= at:
                amount = calculate(selected, identifier)
                # 既有查询的不可比或资料不足状态继续约束结果。
                if metrics[identifier][0] is None or not units_match:
                    amount = None
                missing = []
                if not selected:
                    missing.append("NO_RECORDS_IN_CONFIGURED_SCOPE")
                if not units_match:
                    missing.append("CONFIGURED_UNIT_NOT_COMPARABLE")
                dependencies = {"sales_quantity": ("quantity_tonnes",), "revenue": ("revenue_cny",), "cost": ("cost_cny",),
                                "gross_profit": ("revenue_cny", "cost_cny"), "gross_margin": ("revenue_cny", "cost_cny"),
                                "gross_profit_per_tonne": ("revenue_cny", "cost_cny", "quantity_tonnes")}[identifier]
                missing.extend(field for field in dependencies if selected and any(row.get(field) is None for row in selected))
                if identifier in {"gross_margin", "gross_profit_per_tonne"}:
                    denominator = calculate(selected, "revenue" if identifier == "gross_margin" else "sales_quantity")
                    if denominator == 0:
                        missing.append("ZERO_DENOMINATOR_UNDEFINED")
                grouped = defaultdict(list)
                for row in selected:
                    grouped[tuple(row.get(field) for field in values["dimensions"])].append(row)
                quantum = Decimal(1).scaleb(-values["precision"])
                breakdown = []
                for dimension_values, group in grouped.items():
                    group_value = calculate(group, identifier) if amount is not None else None
                    breakdown.append({"dimensions": dict(zip(values["dimensions"], dimension_values)),
                                      "value": str(group_value) if group_value is not None else None,
                                      "display_value": format(group_value.quantize(quantum, rounding=ROUND_HALF_UP), "f") if group_value is not None else None,
                                      "detail_refs": [row["record_id"] for row in group]})
                calculation = {"metric_id": identifier, "configuration_version": policy["version"], "content_sha256": policy["content_sha256"],
                               "value": str(amount) if amount is not None else None, "unit": metrics[identifier][1], "formula": values["formula"],
                               "display_value": format(amount.quantize(quantum, rounding=ROUND_HALF_UP), "f") if amount is not None else None,
                               "precision": values["precision"], "scope": values["scope"], "breakdown": breakdown,
                               "missing_fields": missing,
                               "input_sha256": cache_id, "calculated_at": at.isoformat(),
                               "next_refresh_at": (at + timedelta(seconds=values["refresh_seconds"])).isoformat()}
                if cache:
                    db.execute("INSERT OR REPLACE INTO objects(namespace,kind,id,body) VALUES(?,?,?,?)",
                               (namespace, "metric_calculation", cache_id, encode(calculation)))
            result[identifier] = (Decimal(calculation["value"]) if calculation["value"] is not None else None,
                                  calculation["unit"], calculation["formula"])
            adopted[identifier] = calculation
    return result, adopted


def record_adoption(store, db, namespace, request_id, calculations):
    from boss_v7_configuration import record_use
    for period, entries in calculations.items():
        for identifier, calculation in entries.items():
            record_use(store, db, "metrics", identifier, calculation["configuration_version"], request_id + ":" + period, namespace, details=calculation)


def display_rounding(calculation):
    return "ROUND_HALF_UP(" + str(calculation["precision"]) + ")：" + (calculation["display_value"] or "未知") + "；原始值单独保留；配置v" + calculation["configuration_version"]
