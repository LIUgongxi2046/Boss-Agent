from decimal import Decimal

from aiohttp import web

from business import require


def aggregate_metrics(records):
    require(isinstance(records, list), "指标明细必须为列表", web.HTTPBadRequest)
    identifiers = [row["record_id"] for row in records]
    require(len(identifiers) == len(set(identifiers)), "重复明细不能重复计入经营指标", web.HTTPBadRequest)
    scopes = {(row["period"], row["region_id"], row["legal_entity_id"], row["trade_type"]) for row in records}
    require(len(scopes) <= 1 and all(row["trade_type"] == "EXTERNAL_SALES" for row in records),
            "当前指标不能合并不同期间、区域、法人或交易范围", web.HTTPBadRequest)
    missing = [] if records else ["records"]
    totals = []
    for field in ("quantity_tonnes", "revenue_cny", "cost_cny"):
        if not records or any(row.get(field) is None for row in records):
            if records:
                missing.append(field)
            totals.append(None)
            continue
        require(all(isinstance(row[field], str) for row in records), "原始数值须为 Decimal 字符串", web.HTTPBadRequest)
        values = [Decimal(row[field]) for row in records]
        require(all(value.is_finite() for value in values), "经营指标不接受非有限数值", web.HTTPBadRequest)
        totals.append(sum(values, Decimal(0)))
    quantity, revenue, cost = totals
    profit = revenue - cost if revenue is not None and cost is not None else None
    return {"metrics": {
        "sales_quantity": (quantity, "吨", "SUM(quantity_tonnes)"),
        "revenue": (revenue, "CNY", "SUM(revenue_cny)"),
        "cost": (cost, "CNY", "SUM(cost_cny)"),
        "gross_profit": (profit, "CNY", "revenue-cost"),
        "gross_margin": (profit / revenue * 100 if profit is not None and revenue else None, "%", "gross_profit/revenue*100"),
        "gross_profit_per_tonne": (profit / quantity if profit is not None and quantity else None, "CNY/吨", "gross_profit/quantity"),
    }, "missing_fields": missing, "detail_refs": identifiers}
