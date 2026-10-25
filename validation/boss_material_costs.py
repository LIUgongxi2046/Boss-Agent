from collections import defaultdict
from datetime import datetime
from decimal import Decimal, localcontext

from aiohttp import web

from business import require
from boss_supply_quality import COST_SCOPE_FIELDS


def _number(value):
    return None if value is None else Decimal(value)


def _text(value):
    return None if value is None else format(value.normalize(), "f")


def _summary(report):
    quantity, total = _number(report["quantity"]), _number(report["total_cost"])
    unit_cost = total / quantity if total is not None and quantity is not None and quantity > 0 else None
    return {field: report[field] for field in ("report_id", "source_id", "source_version", "period_start", "period_end", "inventory_ids", "quantity", "total_cost")} | {"unit_cost": _text(unit_cost)}


def calculate_cost_reports(records):
    require(len({record["report_id"] for record in records}) == len(records), "成本报告编号重复", web.HTTPBadRequest)
    groups = defaultdict(list)
    for record in records:
        if record["state"] == "REPORTED":
            groups[tuple(record[field] for field in COST_SCOPE_FIELDS)].append(record)
    result = []
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        for scope, reports in sorted(groups.items(), key=lambda item: str(item[0])):
            ordered = sorted(reports, key=lambda report: datetime.fromisoformat(report["period_start"]))
            for previous, current in zip(ordered, ordered[1:]):
                require(datetime.fromisoformat(previous["period_end"]) <= datetime.fromisoformat(current["period_start"]), "成本报告期间重复或重叠", web.HTTPBadRequest)
            latest = ordered[-1]
            current = _summary(latest)
            baseline = _summary(ordered[-2]) if len(ordered) > 1 else None
            cost_owner_known = latest["cost_owner_id"] is not None
            comparable = cost_owner_known and baseline is not None and datetime.fromisoformat(current["period_end"]) - datetime.fromisoformat(current["period_start"]) == datetime.fromisoformat(baseline["period_end"]) - datetime.fromisoformat(baseline["period_start"])
            missing = []
            if not cost_owner_known:
                missing.append("COST_OWNER_UNKNOWN")
            if baseline is None:
                missing.append("BASELINE_COST_REPORT_NOT_PROVIDED")
            elif cost_owner_known and not comparable:
                missing.append("COST_REPORT_PERIODS_NOT_COMPARABLE")
            for label, report in (("CURRENT", current), ("BASELINE", baseline)):
                if report is not None:
                    if report["unit_cost"] is None:
                        missing.append(label + "_UNIT_COST_UNKNOWN")
                    if report["total_cost"] is None:
                        missing.append(label + "_TOTAL_COST_UNKNOWN")
            changes = {}
            for field in ("unit_cost", "total_cost"):
                changes[field + "_change"] = _text(Decimal(current[field]) - Decimal(baseline[field])) if comparable and current[field] is not None and baseline[field] is not None else None
            result.append({**dict(zip(COST_SCOPE_FIELDS, scope)), "scope_description": latest["scope_description"], "current": current, "baseline": baseline,
                "comparison_state": "UNKNOWN_COST_OWNER" if not cost_owner_known else "COMPARABLE" if comparable else "NO_BASELINE" if baseline is None else "INCOMPARABLE_PERIODS",
                **changes, "missing_fields": missing,
                "formula": "unit_cost=total_cost/quantity；change=current-baseline；比较要求相同范围、口径、单位、币种和实际期间时长。"})
    return result
