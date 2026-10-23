import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, localcontext

from business import checksum, now
from boss_supply_quality import DEFINITION, external_records


def decimal_text(value):
    return None if value is None else format(value.normalize(), "f")


def _total(values):
    return None if any(value is None for value in values) else sum((Decimal(value) for value in values), Decimal(0))


def _supply(records, clock, missing, withheld):
    groups = defaultdict(list)
    for row in records.get("inventory_lot", []):
        if row["material_id"] is not None:
            fields = ("material_id", "legal_entity_id", "asset_owner_id", "ownership_type", "customer_id", "quantity_unit", "currency")
            groups[tuple(row[field] for field in fields)].append(row)
    result = []
    for scope, lots in sorted(groups.items(), key=lambda item: str(item[0])):
        material, entity, asset_owner, ownership, customer, unit, currency = scope
        excluded, quantities = [], []
        for lot in lots:
            reason = "IN_TRANSIT" if lot["in_transit"] else lot["quality_state"] if lot["quality_state"] != "RELEASED" else "EXPIRED" if lot["expires_at"] and datetime.fromisoformat(lot["expires_at"]) <= clock else None
            if reason:
                excluded.append({"inventory_id": lot["inventory_id"], "reason": reason})
            else:
                quantities.append(lot["available_quantity"])
        available = None if withheld else _total(quantities)
        if available is None:
            missing.add("CURRENT_AVAILABLE_QUANTITY_INCOMPLETE")
        consumption = [row for row in records.get("material_consumption", []) if row["state"] == "REPORTED" and row["material_id"] == material
                       and row["legal_entity_id"] == entity and row["quantity_unit"] == unit and row["currency"] == currency
                       and row["inventory_id"] in {lot["inventory_id"] for lot in lots}]
        daily = Decimal(consumption[0]["daily_quantity"]) if len(consumption) == 1 and consumption[0]["daily_quantity"] is not None else None
        if daily is None or daily == 0:
            missing.add("CURRENT_DAILY_CONSUMPTION_NOT_UNIQUE_OR_UNKNOWN")
        coverage = available / daily if available is not None and daily is not None and daily > 0 else None
        quote_groups = defaultdict(list)
        for quote in records.get("material_quote", []):
            if quote["material_id"] == material and quote["price_unit"] == unit and quote["currency"] == currency and quote["state"] == "QUOTED":
                quote_groups[quote["origin"]].append(quote)
        delta, selected_quotes = None, []
        if len(quote_groups) == 1:
            selected_quotes = sorted(next(iter(quote_groups.values())), key=lambda row: datetime.fromisoformat(row["quoted_at"]))
            if len(selected_quotes) >= 2:
                before, current = selected_quotes[-2:]
                if datetime.fromisoformat(before["quoted_at"]) < datetime.fromisoformat(current["quoted_at"]) and before["price"] is not None and current["price"] is not None:
                    delta = Decimal(current["price"]) - Decimal(before["price"])
        if delta is None:
            missing.add("COMPARABLE_QUOTE_HISTORY_INCOMPLETE")
        contracts = [row for row in records.get("material_contract", []) if row["material_id"] == material and row["legal_entity_id"] == entity
                     and row["quantity_unit"] == unit and row["currency"] == currency and row["contract_state"] not in ("CANCELED_REPORTED", "FULFILLED_REPORTED")]
        requirements = []
        for capacity in records.get("production_capacity", []):
            if ownership != "COMPANY" or asset_owner != entity or customer is not None or capacity["legal_entity_id"] != entity or capacity["quantity_unit"] != unit or unit != "tonne":
                continue
            if datetime.fromisoformat(capacity["period_end"]) <= clock:
                continue
            formulas = [formula for formula in records.get("feed_formula", []) if formula["product_id"] == capacity["product_id"]
                        and formula["professional_state"] == "PROFESSIONALLY_CONFIRMED" and formula["composition_complete"]
                        and datetime.fromisoformat(formula["valid_from"]) <= clock
                        and (formula["valid_until"] is None or datetime.fromisoformat(formula["valid_until"]) >= datetime.fromisoformat(capacity["period_end"]))]
            if len(formulas) != 1 or capacity["planned_quantity"] is None:
                missing.add("CURRENT_FORMULA_OR_PLAN_INCOMPLETE")
                continue
            ingredients = [row for row in formulas[0]["ingredients"] if row["material_id"] == material and row["ratio_unit"] == "tonne_per_tonne"]
            if len(ingredients) != 1 or ingredients[0]["ratio"] is None:
                missing.add("MATERIAL_PLAN_RATIO_INCOMPLETE")
                continue
            requirements.append({"capacity_id": capacity["capacity_id"], "formula_id": formulas[0]["formula_id"],
                                 "period_start": capacity["period_start"], "period_end": capacity["period_end"],
                                 "quantity": decimal_text(Decimal(ingredients[0]["ratio"]) * Decimal(capacity["planned_quantity"]))})
        required = Decimal(requirements[0]["quantity"]) if len(requirements) == 1 else None
        if len(requirements) > 1:
            missing.add("MULTIPLE_PLAN_ALLOCATION_NOT_PROVIDED")
        missing.add("ACTUAL_COST_NOT_PROVIDED")
        result.append({"material_id": material, "legal_entity_id": entity, "asset_owner_id": asset_owner,
            "ownership_type": ownership, "customer_id": customer, "quantity_unit": unit, "currency": currency,
            "available_quantity": decimal_text(available), "daily_quantity": decimal_text(daily), "coverage_days": decimal_text(coverage),
            "consumption_assumptions": [row["assumption"] for row in consumption], "excluded_inventory": excluded,
            "quote_price_difference": decimal_text(delta), "quote_ids": [row["quote_id"] for row in selected_quotes],
            "contract_unit_prices": [row["unit_price"] for row in contracts], "actual_cost_change": None,
            "plan_requirements": requirements, "required_quantity": decimal_text(required),
            "quantity_gap": decimal_text(max(required - available, Decimal(0))) if required is not None and available is not None else None,
            "hypothetical_plan_quote_difference": decimal_text(required * delta) if required is not None and delta is not None else None,
            "calculation_basis": "SIMULATED：库存采用外部报告余额；日耗用采用明确假设；计划数量乘原料比例及同产地报价变化仅表示计划假设。"})
    return result


def _trace(records):
    processing, inventory, customers, unconfirmed = {}, [], [], []
    states = {state: [] for state in ("CONFIRMED", "POSSIBLE", "MISSING", "CONFLICTED")}
    for row in records.get("quality_trace", []):
        states[row["trace_state"]].append(row)
        if row["trace_state"] != "CONFIRMED":
            unconfirmed.append(row)
            continue
        fields = ("processing_id", "input_quantity", "output_quantity", "loss_quantity", "quantity_unit")
        current = processing.setdefault(row["processing_id"], {field: row[field] for field in fields})
        for field in fields:
            if current[field] is None and row[field] is not None:
                current[field] = row[field]
        if row["inventory_id"] is not None:
            inventory.append({"inventory_id": row["inventory_id"], "batch_id": row["output_batch_id"], "quantity": row["destination_quantity"], "quantity_unit": row["quantity_unit"]})
        if row["customer_id"] is not None:
            customers.append({"customer_id": row["customer_id"], "quantity": row["destination_quantity"], "quantity_unit": row["quantity_unit"]})
    return {"processing_totals": [processing[key] for key in sorted(processing)], "confirmed_inventory": inventory,
            "confirmed_customers": customers, "unconfirmed_relationships": unconfirmed, "relationships_by_state": states,
            "causal_conclusion": None}


def read_projection(store, db, context, interface_id):
    from boss_simulation_api import SimulationAPI
    broker = SimulationAPI(store)
    projections = {interface: broker.project_in_transaction("BOSS", db, {"interface_id": interface, "object_ids": [], "filters": {}}) for interface in ("SI09", "SI10")}
    selected = projections[interface_id]
    by_kind, visible = defaultdict(list), []
    for projection in projections.values():
        for record in projection["records"]:
            wrapper = record["data"]
            if wrapper is not None and wrapper.get("simulation_definition") == DEFINITION and wrapper["record_state"] == "ACTIVE":
                by_kind[record["entity_type"]].append(wrapper["data"])
                if projection is selected:
                    visible.append(wrapper)
    namespace = context["namespace"]
    imports = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='external_import' AND json_extract(body,'$.simulation_definition')=? ORDER BY json_extract(body,'$.received_at') DESC,id DESC LIMIT 1", (namespace, DEFINITION)).fetchall()]
    links = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='supply_quality_coordination' ORDER BY id", (namespace,)).fetchall()]
    task_states = [store.get(db, namespace, "task", link["task_id"]) for link in links]
    raw_records = external_records(db, namespace)
    source_states = [store.get(db, namespace, "document", record["source_id"]) for _, record in sorted(raw_records.items())]
    bindings = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='external_record_binding' ORDER BY id", (namespace,)).fetchall()]
    digest = checksum({"context": context, "records": [record for _, record in sorted(raw_records.items())], "documents": source_states,
                       "bindings": bindings, "links": links, "tasks": task_states, "initial": store.get(db, namespace, "initial", "snapshot")})
    missing = set(selected["missing_fields"])
    if not visible:
        missing.add("NO_CURRENT_IMPORTED_SIMULATED_RECORDS")
    if imports and imports[0]["state"] != "SUCCESS":
        missing.add("LATEST_IMPORT_" + imports[0]["state"])
    withheld = any(record["data"] is None and record["entity_type"] == "inventory_lot" for projection in projections.values() for record in projection["records"])
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        supply = _supply(by_kind, datetime.fromisoformat(context["clock"]), missing, withheld) if interface_id == "SI09" else []
    return {"source_type": "SIMULATED", "simulation_definition": DEFINITION, "interface_id": interface_id,
            "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"], "execution_namespace": namespace,
            "records": visible, "source_statuses": selected["records"], "availability": "PARTIAL" if visible else "UNAVAILABLE",
            "last_import": imports[0] if imports else None, "missing_fields": sorted(missing),
            "supply": supply, "trace": _trace(by_kind) if interface_id == "SI10" else None,
            "events": [wrapper for wrapper in visible if wrapper["entity_type"] == "production_event"],
            "coordination_links": links, "review_sha256": digest, "business_at": context["clock"], "read_at": now(),
            "external_service_invoked": False, "purchase_executed": False, "quality_release_executed": False}
