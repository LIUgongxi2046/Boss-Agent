from concurrent.futures import ThreadPoolExecutor
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_simulation_api import SimulationAPI
from boss_supply_quality import IMPORT_ACTION, WITHDRAW_ACTION, COORDINATE_ACTION, SupplyQualityAPI
from boss_assignment_sources import AssignmentSourcesAPI
from business import checksum, initial_materials
from controls import ControlStore


def definition():
    return yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())


@pytest.fixture
def store(tmp_path):
    store = ControlStore(tmp_path / "supply-quality.sqlite")
    store.initialize("ui-check")
    return store


def imported(store):
    api = SupplyQualityAPI(store)
    result = api.execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"])
    assert result["state"] == "SUCCESS" and result["source_type"] == "SIMULATED"
    return api, result


def update_record(api, kind, identifier, changes, expected="1", key="simulated-external-update"):
    sample = definition()["initial_request"]
    config = json.loads((ROOT / "specs/simulated-supply-quality.schema.json").read_text())["x-entity-config"]
    record = deepcopy(next(record for record in sample["records"] if record["entity_type"] == kind and record["data"][config[kind]["id"]] == identifier))
    record["expected_version"] = expected
    record["data"].update(changes)
    return api.execute("MAINTAINER", IMPORT_ACTION, {**sample, "client_request_id": key, "records": [record]})


def test_explicit_simulated_import_uses_actual_store_sources_and_current_queries(store):
    api, imported_result = imported(store)
    assert imported_result["record_count"] == 21 and imported_result["external_service_invoked"] is False
    with store.connect() as db:
        assert store.get(db, "ui-check", "initial", "snapshot") == initial_materials()
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 23
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='external_record_binding'").fetchone()[0] == 21
    reader = SimulationAPI(ControlStore(store.path))
    for interface in ("SI09", "SI10"):
        result = reader.query("BOSS", {"interface_id": interface, "object_ids": [], "filters": {}})
        assert result["availability"] == "PARTIAL" and result["records"]
        assert all(record["data"]["source_type"] == "SIMULATED" for record in result["records"])
        technical = reader.inspect("MAINTAINER", {"interface_id": interface, "object_ids": [], "filters": {}})
        assert technical["records"] and all(record["data"] is None for record in technical["records"])
    assert api.execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"]) == imported_result


def test_supply_calculation_excludes_pending_in_transit_and_reports_unknown_actual_cost(store):
    api, _ = imported(store)
    view = api.read("BOSS", "SI09")
    assert view["source_type"] == "SIMULATED" and view["external_service_invoked"] is False
    stock = view["supply"][0]
    assert stock["material_id"] == "sim-material-1" and stock["available_quantity"] == "20"
    assert stock["daily_quantity"] == "2" and stock["coverage_days"] == "10"
    assert {row["inventory_id"] for row in stock["excluded_inventory"]} == {"sim-stock-pending-1", "sim-stock-transit-1"}
    assert stock["quote_price_difference"] == "200" and stock["hypothetical_plan_quote_difference"] == "2000"
    assert stock["contract_unit_prices"] == ["2050"] and stock["actual_cost_change"] is None
    assert "ACTUAL_COST_NOT_PROVIDED" in view["missing_fields"]


def test_trace_counts_a_processing_step_once_and_keeps_professional_state_separate(store):
    api, _ = imported(store)
    view = api.read("BOSS", "SI10")
    assert view["trace"]["processing_totals"] == [{"processing_id": "sim-processing-1", "input_quantity": "10", "output_quantity": "9.5", "loss_quantity": "0.5", "quantity_unit": "tonne"}]
    assert view["trace"]["confirmed_inventory"][0]["quantity"] == "3.5"
    assert view["trace"]["confirmed_customers"][0] == {"customer_id": "customer-1", "quantity": "6", "quantity_unit": "tonne"}
    assert view["trace"]["unconfirmed_relationships"] == []
    assert view["events"][0]["data"]["state"] == "PROFESSIONAL_REVIEW_PENDING"
    assert view["quality_release_executed"] is False


@pytest.mark.parametrize("role,error", [(None, web.HTTPUnauthorized), ("BOSS", web.HTTPForbidden)])
def test_simulated_external_import_requires_actual_maintainer_identity(store, role, error):
    with pytest.raises(error):
        SupplyQualityAPI(store).execute(role, IMPORT_ACTION, definition()["initial_request"])
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='inventory_lot'").fetchone()[0] == 0


@pytest.mark.parametrize("section,error", [("failed_request", web.HTTPBadGateway), ("timeout_request", web.HTTPGatewayTimeout)])
def test_simulated_failure_is_recorded_without_creating_business_facts_or_success(store, section, error):
    api = SupplyQualityAPI(store)
    payload = definition()[section]
    with pytest.raises(error):
        api.execute("MAINTAINER", IMPORT_ACTION, payload)
    with pytest.raises(error):
        api.execute("MAINTAINER", IMPORT_ACTION, payload)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='external_import'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('inventory_lot','authorization','outbox')").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation=?", (IMPORT_ACTION,)).fetchone()[0] == 1
    view = api.read("BOSS", "SI09")
    assert view["last_import"]["state"] == payload["outcome"] and view["last_import"]["external_service_invoked"] is False
    assert view["availability"] == "UNAVAILABLE"


def test_empty_external_result_keeps_existing_data_and_explicit_empty_state(store):
    api, _ = imported(store)
    before = api.read("BOSS", "SI09")["records"]
    result = api.execute("MAINTAINER", IMPORT_ACTION, definition()["empty_request"])
    assert result["state"] == "EMPTY" and result["record_count"] == 0
    after = api.read("BOSS", "SI09")
    assert after["records"] == before and after["last_import"]["state"] == "EMPTY"


def test_import_idempotency_cas_and_atomic_rejection(store):
    api, first = imported(store)
    assert api.execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"]) == first
    changed = definition()["initial_request"]
    changed["client_request_id"] = "simulated-stale-full-import"
    with pytest.raises(web.HTTPConflict):
        api.execute("MAINTAINER", IMPORT_ACTION, changed)
    invalid = definition()["initial_request"]
    invalid["client_request_id"] = "simulated-duplicate-record"
    invalid["records"].append(deepcopy(invalid["records"][0]))
    with pytest.raises(web.HTTPBadRequest):
        api.execute("MAINTAINER", IMPORT_ACTION, invalid)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='document_revision'").fetchone()[0] == 0


def test_external_state_updates_preserve_revisions_and_rejected_inventory_is_terminal(store):
    api, _ = imported(store)
    updated = update_record(api, "inventory_lot", "sim-stock-pending-1", {"quality_state": "REJECTED"})
    assert updated["records"][0]["version"] == "2"
    with pytest.raises(web.HTTPConflict):
        update_record(api, "inventory_lot", "sim-stock-pending-1", {"quality_state": "RELEASED", "available_quantity": "5"}, expected="2", key="simulated-invalid-release")
    with store.connect() as db:
        assert store.get(db, "ui-check", "inventory_lot", "sim-stock-pending-1")["data"]["quality_state"] == "REJECTED"
        assert store.get(db, "ui-check", "inventory_lot_revision", "sim-stock-pending-1:v1")["data"]["quality_state"] == "PENDING_TEST"


def test_withdrawal_stops_current_content_and_preserves_original_import_receipt(store):
    api, initial = imported(store)
    result = api.execute("MAINTAINER", WITHDRAW_ACTION, {"client_request_id": "sim-withdraw-stock-source", "entity_type": "inventory_lot", "record_id": "sim-stock-available-1", "expected_version": "1", "reason": "模拟来源撤销"})
    assert result["record_state"] == "WITHDRAWN"
    current = SimulationAPI(store).query("BOSS", {"interface_id": "SI09", "object_ids": ["sim-stock-available-1"], "filters": {}})
    assert current["records"][0]["data"] is None and current["records"][0]["source_refs"][0]["status"] == "WITHDRAWN"
    assert api.execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"]) == initial
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM knowledge WHERE source_id=?", (result["source_id"],)).fetchone()[0] == 0


def test_current_dependency_change_requires_reimported_trace_evidence(store):
    api, _ = imported(store)
    update_record(api, "professional_record", "sim-quality-review-1", {"state": "PROFESSIONALLY_CONFIRMED", "conclusion": "PASS_REPORTED"})
    result = SimulationAPI(store).query("BOSS", {"interface_id": "SI10", "object_ids": ["sim-trace-stock-1"], "filters": {}})
    assert result["records"][0]["data"] is None
    assert any(reference["status"] == "CHANGED" for reference in result["records"][0]["source_refs"])


def test_reset_uses_current_namespace_without_old_external_records(store):
    imported(store)
    store.control("ui-check", "reset", {"namespace": "supply-new-execution"})
    api = SupplyQualityAPI(ControlStore(store.path))
    assert api.read("BOSS", "SI09")["records"] == []
    with pytest.raises(web.HTTPConflict):
        api.execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"])
    fresh = definition()["initial_request"]
    fresh["client_request_id"] = "sim-new-space-import-v1"
    result = api.execute("MAINTAINER", IMPORT_ACTION, fresh)
    assert result["execution_namespace"] == "supply-new-execution"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind='inventory_lot'").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='supply-new-execution' AND kind='inventory_lot'").fetchone()[0] == 4


def test_schema_rejects_real_mode_unknown_numbers_and_client_scope(store):
    api = SupplyQualityAPI(store)
    for field, value in (("mode", "REAL"), ("owner_id", "boss-1"), ("execution_namespace", "ui-check")):
        payload = definition()["initial_request"]
        payload[field] = value
        with pytest.raises(web.HTTPBadRequest):
            api.execute("MAINTAINER", IMPORT_ACTION, payload)
    payload = definition()["initial_request"]
    payload["records"][1]["data"]["price"] = "NaN"
    with pytest.raises(web.HTTPBadRequest):
        api.execute("MAINTAINER", IMPORT_ACTION, payload)


def test_explicit_coordination_task_uses_existing_send_feedback_and_owner_completion(store):
    api, _ = imported(store)
    view = api.read("BOSS", "SI10")
    payload = {"client_request_id": "supply-quality-coordinate-v1", "interface_id": "SI10", "origin_entity_type": "production_event", "origin_record_id": "sim-production-event-1", "origin_version": "1", "review_sha256": view["review_sha256"],
        "purpose": "汇总SIMULATED来源和当前待核查事项", "coordinator_id": "coordinator-1", "due_at": "2026-10-24T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["当前模拟资料和待核查清单"]}
    with pytest.raises(web.HTTPForbidden):
        api.execute("MAINTAINER", COORDINATE_ACTION, payload)
    created = api.execute("BOSS", COORDINATE_ACTION, payload)
    assert created["purchase_executed"] is created["quality_release_executed"] is False
    assert api.execute("BOSS", COORDINATE_ACTION, payload) == created
    commands = BossCommandAPI(store)
    status, sent = commands.execute("BOSS", "boss.assignment.send", {"client_request_id": "sim-coordination-send-v1", "task_id": created["task_id"], "task_version": created["version"], "recipient_id": "coordinator-1", "body": "请汇总模拟来源与当前待核查清单。", "content_version": "1"})
    assert status == 200, sent
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", created["task_id"])
        assert task["related_meeting_id"] is None and task["related_event_ids"] == []
        references = task["source_refs"]
    status, feedback = commands.execute("MAINTAINER", "boss.simulation.feedback", {"client_request_id": "sim-coordination-result-v1", "task_id": created["task_id"], "task_version": sent["task_version"], "author_contact_id": "coordinator-1", "kind": "RESULT_SUBMITTED", "content": "已汇总当前模拟资料，专业事项继续待核查。", "evidence_refs": references})
    assert status == 200, feedback
    status, completed = commands.execute("BOSS", "boss.assignment.complete", {"client_request_id": "sim-coordination-complete-v1", "task_id": created["task_id"], "task_version": feedback["task"]["version"], "feedback_id": feedback["feedback_id"]})
    assert status == 200 and completed["status"] == "COMPLETED_CONFIRMED"
    with store.connect() as db:
        assert store.get(db, "ui-check", "production_event", "sim-production-event-1")["data"]["state"] == "PROFESSIONAL_REVIEW_PENDING"
        assert store.get(db, "ui-check", "inventory_lot", "sim-stock-finished-1")["data"]["quality_state"] == "HOLD"


def coordination_payload(api, key="sim-coordination-current-v1"):
    view = api.read("BOSS", "SI10")
    return {"client_request_id": key, "interface_id": "SI10", "origin_entity_type": "production_event", "origin_record_id": "sim-production-event-1", "origin_version": "1", "review_sha256": view["review_sha256"],
        "purpose": "核查当前SIMULATED批次资料", "coordinator_id": "coordinator-1", "due_at": "2026-10-24T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["当前明确的模拟来源"]}


def test_concurrent_imports_produce_one_persisted_result(store):
    api = SupplyQualityAPI(store)
    payload = definition()["initial_request"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(api.execute, "MAINTAINER", IMPORT_ACTION, payload) for _ in range(2)]
        results = [future.result() for future in futures]
    assert results[0] == results[1]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='external_import'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='inventory_lot'").fetchone()[0] == 4


def test_two_current_owner_requests_cannot_create_twice_from_same_review(store):
    api, _ = imported(store)
    payload = coordination_payload(api)
    second = {**payload, "client_request_id": "sim-coordination-current-v2"}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(api.execute, "BOSS", COORDINATE_ACTION, value) for value in (payload, second)]
        exceptions = [future.exception() for future in futures]
    assert exceptions.count(None) == 1
    assert sum(isinstance(error, web.HTTPConflict) for error in exceptions) == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='supply_quality_coordination'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1


@pytest.mark.parametrize("changes", [{"available_quantity": None}, {"expires_at": "2026-10-22T08:00:00+08:00"}])
def test_unknown_and_expired_inventory_never_become_positive_current_availability(store, changes):
    api, _ = imported(store)
    update_record(api, "inventory_lot", "sim-stock-available-1", changes)
    stock = api.read("BOSS", "SI09")["supply"][0]
    assert stock["available_quantity"] == (None if "available_quantity" in changes else "0")
    assert stock["coverage_days"] is None
    assert stock["actual_cost_change"] is None


@pytest.mark.parametrize("changes", [{"quantity_unit": "kg"}, {"ownership_type": "CUSTOMER", "customer_id": "customer-1", "asset_owner_id": "customer-1"}, {"quality_state": "HOLD", "available_quantity": "20"}])
def test_invalid_units_ownership_and_restricted_positive_availability_are_atomic(store, changes):
    api, _ = imported(store)
    with pytest.raises((web.HTTPBadRequest, web.HTTPConflict)):
        update_record(api, "inventory_lot", "sim-stock-available-1", changes)
    with store.connect() as db:
        current = store.get(db, "ui-check", "inventory_lot", "sim-stock-available-1")
        assert current["version"] == "1" and current["data"]["quantity_unit"] == "tonne"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='inventory_lot_revision'").fetchone()[0] == 0


@pytest.mark.parametrize("changes", [{"input_quantity": "11", "output_quantity": "10.5"}, {"destination_quantity": "7"}])
def test_same_processing_relations_reject_conflicting_totals_or_excess_destinations(store, changes):
    api, _ = imported(store)
    with pytest.raises(web.HTTPBadRequest):
        update_record(api, "quality_trace", "sim-trace-customer-1", changes)
    assert api.read("BOSS", "SI10")["trace"]["processing_totals"][0]["output_quantity"] == "9.5"


def test_new_child_cannot_adopt_an_existing_parent_with_changed_dependencies(store):
    api, _ = imported(store)
    update_record(api, "production_batch", "sim-raw-batch-1", {"quantity": "51"})
    with pytest.raises(web.HTTPConflict):
        update_record(api, "material_consumption", "sim-consumption-1", {"daily_quantity": "3"}, key="sim-stale-parent-adoption")
    current = api.read("BOSS", "SI09")
    assert not {"sim-stock-available-1", "sim-stock-pending-1", "sim-stock-transit-1", "sim-consumption-1"} & {record["record_id"] for record in current["records"]}
    assert "sim-stock-finished-1" in {record["record_id"] for record in current["records"]}


def test_filters_use_current_entity_fields_and_own_source_version(store):
    api, _ = imported(store)
    reader = SimulationAPI(store)
    payload = {"interface_id": "SI09", "object_ids": [], "filters": {"material_id": "sim-material-1", "legal_entity_id": "entity-1", "currency": "CNY"}}
    result = reader.query("BOSS", payload)
    assert {record["entity_type"] for record in result["records"]} == {"inventory_lot", "material_contract", "material_consumption"}
    technical = reader.inspect("MAINTAINER", payload)
    assert {record["record_id"] for record in technical["records"]} == {record["record_id"] for record in result["records"]}
    assert all(record["data"] is None for record in technical["records"])
    trace = reader.query("BOSS", {"interface_id": "SI10", "object_ids": ["sim-trace-stock-1"], "filters": {"batch_id": "sim-finished-batch-1"}})
    assert len(trace["records"]) == 1
    update_record(api, "professional_record", "sim-quality-review-1", {"state": "PROFESSIONALLY_CONFIRMED", "conclusion": "PASS_REPORTED"})
    version = reader.query("BOSS", {"interface_id": "SI10", "object_ids": ["sim-trace-stock-1"], "filters": {"source_version": "2"}})
    assert version["records"] == []


def test_stale_external_adoption_blocks_source_confirmation_and_knowledge_content(store):
    api, _ = imported(store)
    task = api.execute("BOSS", COORDINATE_ACTION, coordination_payload(api))
    update_record(api, "professional_record", "sim-quality-review-1", {"state": "PROFESSIONALLY_CONFIRMED", "conclusion": "PASS_REPORTED"})
    review = AssignmentSourcesAPI(store).read("BOSS", task["task_id"])
    assert review["binding_state"] == "NEEDS_REVIEW" and review["can_confirm"] is False
    assert any(row["adoption_state"] == "NEEDS_REIMPORT" and row["source_status"] == "VALID" and row["excerpt"] is None for row in review["sources"])
    with pytest.raises(web.HTTPConflict):
        AssignmentSourcesAPI(store).execute("BOSS", {"client_request_id": "sim-no-adoption-bypass", "task_id": task["task_id"], "task_version": task["version"], "review_sha256": review["review_sha256"], "reason": "当前记录需要重新导入"})
    result = SimulationAPI(store).query("BOSS", {"interface_id": "SI13", "object_ids": ["sim-business:production_event:sim-production-event-1"], "filters": {}})
    assert result["records"][0]["data"] is None


def test_generic_source_withdrawal_cannot_be_reenabled_by_record_import(store):
    api, _ = imported(store)
    store.control("ui-check", "withdraw", {"source_id": "sim-business:inventory_lot:sim-stock-available-1", "version": "1"})
    with pytest.raises(web.HTTPConflict):
        update_record(api, "inventory_lot", "sim-stock-available-1", {"quantity": "21"})


def test_coordinate_rejects_stale_review_and_invalid_due_without_authorization_writes(store):
    api, _ = imported(store)
    original = coordination_payload(api)
    update_record(api, "material_quote", "sim-quote-current-1", {"price": "2250"})
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", COORDINATE_ACTION, original)
    for changes in ({"due_at": "2026-10-20T17:00:00+08:00"}, {"timezone": "Europe/London"}, {"coordinator_id": "sim-professional-1"}):
        with pytest.raises((web.HTTPBadRequest, web.HTTPForbidden)):
            api.execute("BOSS", COORDINATE_ACTION, {**coordination_payload(api), **changes})
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_failed_receipt_is_readable_only_by_the_authenticated_maintainer(store):
    api = SupplyQualityAPI(store)
    payload = definition()["failed_request"]
    with pytest.raises(web.HTTPBadGateway):
        api.execute("MAINTAINER", IMPORT_ACTION, payload)
    receipt = api.receipt_http("MAINTAINER", "action=" + IMPORT_ACTION + "&client_request_id=" + payload["client_request_id"])
    assert receipt["outcome"] == "RECORDED" and receipt["result"]["state"] == "FAILED"
    assert receipt["result"]["records"] == []
    with pytest.raises(web.HTTPForbidden):
        api.receipt("BOSS", IMPORT_ACTION, payload["client_request_id"])
    with pytest.raises(web.HTTPUnauthorized):
        api.receipt(None, IMPORT_ACTION, payload["client_request_id"])
    assert api.receipt("MAINTAINER", IMPORT_ACTION, "sim-no-recorded-request")["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"


@pytest.mark.parametrize("query", ["", "interface_id=SI09&interface_id=SI10", "interface_id=SI09&owner_id=boss-1", "interface_id=SI13", "interface_id="])
def test_business_http_projection_rejects_invalid_or_client_scope_parameters(store, query):
    with pytest.raises(web.HTTPBadRequest):
        SupplyQualityAPI(store).read_http("BOSS", query)


def test_current_external_records_and_source_adoption_survive_independent_reopen(store):
    api, receipt = imported(store)
    before = api.read("BOSS", "SI10")
    reopened = SupplyQualityAPI(ControlStore(store.path))
    after = reopened.read_http("BOSS", "interface_id=SI10")
    assert after["records"] == before["records"] and after["review_sha256"] == before["review_sha256"]
    assert reopened.receipt("MAINTAINER", IMPORT_ACTION, definition()["initial_request"]["client_request_id"])["result"] == receipt
    update_record(reopened, "professional_record", "sim-quality-review-1", {"state": "PROFESSIONALLY_CONFIRMED", "conclusion": "PASS_REPORTED"})
    searched = store.control("ui-check", "search", {"query": "SIMULATED"})
    assert "sim-business:production_event:sim-production-event-1" not in {row["source_id"] for row in searched["results"]}


def test_actual_nanobot_registry_publishes_current_schema_and_reads_coordination_task(store):
    from nanobot.agent.tools.registry import ToolRegistry
    from model_probe import BusinessTool
    from business import SPEC
    api, _ = imported(store)
    created = api.execute("BOSS", COORDINATE_ACTION, coordination_payload(api))
    envelope = {"request_id": "sim-registry-read-request", "session_id": "sim-registry-read-session", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1"}
    registry = ToolRegistry()
    records = []
    registry.register(BusinessTool("create_assignment", store, envelope, {}, records))
    registry.register(BusinessTool("read_assignment", store, envelope, {}, records))
    definitions = {item["function"]["name"]: item["function"]["parameters"] for item in registry.get_definitions()}
    parameters = definitions["create_assignment"]
    Draft202012Validator(parameters, format_checker=FormatChecker()).validate({"purpose": "核查当前模拟资料", "content_version": "1", "coordinator_id": "coordinator-1", "due_at": "2026-10-24T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["当前来源"], "related_meeting_id": None, "related_event_ids": [], "source_refs": ["sim-business:production_event:sim-production-event-1"]})
    assert "envelope" not in parameters["properties"] and "authorization_id" not in parameters["properties"]
    raw = asyncio.run(registry.execute("read_assignment", {"task_id": created["task_id"]}))
    result = json.loads(raw)
    Draft202012Validator({**SPEC["io_schema"], "$ref": "#/$defs/read_output"}).validate(result)
    assert result["related_meeting_id"] is None and result["related_event_ids"] == [] and result["status"] == "OPEN"
    assert records[0]["name"] == "read_assignment"
