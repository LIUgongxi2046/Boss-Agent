import calendar
from datetime import date
from decimal import Decimal

from business import require


def month_period(value):
    start = date.fromisoformat(value + "-01")
    return start.isoformat(), start.replace(day=calendar.monthrange(start.year, start.month)[1]).isoformat()


def periods(documents):
    values = sorted({period for document in documents for period in document["sector_facts"]["periods"]})
    return [{"id": "SECTOR_CURRENT" if index == len(values) - 1 else "SECTOR_" + value,
             "period_start": month_period(value)[0], "period_end": month_period(value)[1]} for index, value in enumerate(values)]


def metrics(document, scope):
    declared = document.get("sector_scope")
    if declared is None or declared["legal_entity_ids"] != [scope["legal_entity_id"]]:
        return []
    if scope["region_id"] is not None and declared["region_ids"] != [scope["region_id"]]:
        return []
    results = []
    for metric in document["sector_facts"]["metrics"]:
        for index, point in enumerate(metric["points"]):
            if month_period(point["period"]) != (scope["period_start"], scope["period_end"]):
                continue
            value = Decimal(point["value"])
            require(value.is_finite(), "经营指标数值无效")
            previous = Decimal(metric["points"][index - 1]["value"]) if index > 0 else None
            require(previous is None or previous.is_finite(), "比较期间经营指标数值无效")
            change = ((value - previous) / abs(previous) * 100).quantize(Decimal("0.01")) if previous is not None and previous != 0 else None
            results.append({"label": metric["label"], "value": str(value), "unit": metric["unit"], "period": point["period"],
                            "previous_value": str(previous) if previous is not None else None,
                            "change_percent": str(change) if change is not None else None,
                            "source_refs": [{"source_id": document["source_id"], "version": document["version"]}]})
    return results
