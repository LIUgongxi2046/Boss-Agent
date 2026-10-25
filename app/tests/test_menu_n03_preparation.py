import asyncio
import importlib.util
import inspect
import json

import pytest
from aiohttp import web

from test_menu_n02_context_references import ROOT, ControlStore, BossCommandAPI
from test_menu_n03_overview import scope, snapshot
from test_boss_command_api import create_input, send_input


@pytest.fixture
def preparation(tmp_path):
    spec = importlib.util.spec_from_file_location("n03_preparation_overview", ROOT / "validation/boss_business_overview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = ControlStore(tmp_path / "preparation.sqlite")
    store.initialize("ui-check")
    api = module.BusinessOverviewAPI(store)
    getter = getattr(api, "preparation", None)
    assert callable(getter), "经营总览需要正式只读准备接口"
    bridge = getter()
    assert inspect.getfile(type(bridge)) == str(ROOT / "validation/boss_business_overview_preparation.py")
    return store, api, bridge


def selection(api, reference=None, topic=None, action="ASSIGNMENT_REVIEW", selected_scope=None):
    selected_scope = scope() if selected_scope is None else selected_scope
    view = api.read("BOSS", selected_scope)
    return {"applied_scope": selected_scope, "topic_reference": topic, "snapshot_sha256": view["snapshot_sha256"],
        "object_reference": reference, "action": action}


def create_task(store, key="n03-preparation-task"):
    code, task = BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input(key))
    assert code == 200, task
    return {"kind": "task", "id": task["task_id"], "version": task["version"]}


def test_explicit_task_uses_actual_source_review_and_current_scope_without_writes(preparation):
    from boss_assignment_sources import AssignmentSourcesAPI
    from boss_business_overview_preparation import SCHEMA
    from jsonschema import Draft202012Validator
    store, api, bridge = preparation
    ref = create_task(store)
    request = selection(api, ref, {"page_id": "F14", "use": None})
    before = snapshot(store)
    result = bridge.read("BOSS", request)
    assert result["state"] == "READY_FOR_REVIEW" and result["current_use_verified"], result
    assert result["applied_scope"] == request["applied_scope"] and result["topic_reference"] == request["topic_reference"]
    assert result["object_reference"] == ref and result["snapshot_sha256"] == request["snapshot_sha256"]
    formal = AssignmentSourcesAPI(store).read("BOSS", ref["id"])
    assert result["assignment_context"]["review_sha256"] == formal["review_sha256"]
    assert result["assignment_context"]["binding_state"] == "CURRENT"
    assert result["handoff"] == {"page_id": "F06", "operation": "boss.assignment.prepare",
        "parameters": {"task_id": ref["id"], "task_version": ref["version"]}, "required_inputs": ["client_request_id"]}
    assert result["source_references"] == [{"kind": "document", "id": "finance-note", "version": "1",
        "content_sha256": next(row["sha256"] for row in api.read("BOSS", scope())["sources"] if row["source_id"] == "finance-note"), "status": "VALID"}]
    assert bridge.verify("BOSS", request, result["context_sha256"])["context_sha256"] == result["context_sha256"]
    assert module_api(store.path).preparation().read("BOSS", request)["context_sha256"] == result["context_sha256"]
    assert snapshot(store) == before
    for flag in ("business_authorization_granted", "business_mutation_performed", "message_sent", "task_completed"):
        assert result[flag] is False
    assert result["owner_decision_required"] is True
    assert "purpose" not in json.dumps(result) and "coordinator_id" not in json.dumps(result)
    Draft202012Validator.check_schema(SCHEMA)


def module_api(path):
    spec = importlib.util.spec_from_file_location("n03_reopened_preparation_overview", ROOT / "validation/boss_business_overview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BusinessOverviewAPI(ControlStore(path))


def test_no_selection_or_no_topic_source_returns_specific_waiting_context(preparation):
    store, api, bridge = preparation
    before = snapshot(store)
    empty = bridge.read("BOSS", selection(api))
    assert empty["state"] == "WAITING_INPUT" and empty["handoff"] is None
    assert "EXPLICIT_OBJECT_SELECTION_REQUIRED" in empty["missing_conditions"]
    assert empty["object_reference"] is None and not empty["current_use_verified"]
    assert snapshot(store) == before


def test_current_source_withdrawal_waits_without_exposing_old_preparation(preparation):
    store, api, bridge = preparation
    ref = create_task(store)
    request = selection(api, ref)
    current = bridge.read("BOSS", request)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    before = snapshot(store)
    result = bridge.read("BOSS", selection(api, ref))
    assert result["state"] == "WAITING_INPUT" and not result["current_use_verified"] and result["handoff"] is None
    assert result["source_references"][0]["status"] == "WITHDRAWN"
    assert "CURRENT_OBJECT_SOURCES_REQUIRED" in result["missing_conditions"]
    with pytest.raises(web.HTTPConflict):
        bridge.verify("BOSS", request, current["context_sha256"])
    assert snapshot(store) == before


def test_formal_origin_revision_does_not_reuse_old_coordination_relation(preparation):
    from test_boss_supply_quality import imported, definition, coordination_payload
    from boss_supply_quality import IMPORT_ACTION, COORDINATE_ACTION
    store, api, bridge = preparation
    service, _ = imported(store)
    params = coordination_payload(service, "n03-revision-coordinate")
    service.execute("BOSS", COORDINATE_ACTION, params)
    origin = {"kind": params["origin_entity_type"], "id": params["origin_record_id"], "version": params["origin_version"]}
    topic = {"page_id": "F21", "use": None}
    request = selection(api, origin, topic)
    assert bridge.read("BOSS", request)["task_candidates"]
    manifest = definition()["initial_request"]
    assert service.execute("MAINTAINER", IMPORT_ACTION, {**manifest, "client_request_id": "n03-preparation-reimport",
        "records": [{**row, "expected_version": "1"} for row in manifest["records"]]})["state"] == "SUCCESS"
    before = snapshot(store)
    with pytest.raises(web.HTTPConflict):
        bridge.read("BOSS", request)
    result = bridge.read("BOSS", selection(api, {**origin, "version": "2"}, topic))
    assert result["task_candidates"] == [] and result["handoff"] is None
    assert "EXISTING_RELATED_TASK_REQUIRED" in result["missing_conditions"]
    assert snapshot(store) == before


def test_actual_meeting_change_updates_only_the_explicit_related_context(preparation):
    from boss_meetings import MeetingAPI
    store, api, bridge = preparation
    ref = create_task(store)
    request = selection(api, ref, action="MEETING_PREPARATION")
    original = bridge.read("BOSS", request)
    MeetingAPI(store).execute("BOSS", "cancel", {"client_request_id": "n03-explicit-meeting-cancel", "meeting_id": "meeting-1",
        "expected_version": "1", "reason": "本次核查取消明确关联的会议"})
    before = snapshot(store)
    result = bridge.read("BOSS", request)
    assert result["snapshot_sha256"] == original["snapshot_sha256"]
    assert result["context_sha256"] != original["context_sha256"]
    assert result["meeting_context"]["meeting_reference"]["version"] == "2"
    assert "CURRENT_MEETING_STATE_REQUIRED" in result["missing_conditions"]
    assert result["handoff"] is None and not result["current_use_verified"]
    assert snapshot(store) == before
    ref = create_task(store)
    before = snapshot(store)
    selected = selection(api, topic={"page_id": "F19", "use": "EGG"})
    result = bridge.read("BOSS", selected)
    assert not result["candidates"] and "CURRENT_TOPIC_SOURCE_REQUIRED" in result["missing_conditions"]
    with pytest.raises(web.HTTPForbidden):
        bridge.read("BOSS", {**selected, "object_reference": ref})
    with pytest.raises(web.HTTPConflict):
        bridge.verify("BOSS", selected, result["context_sha256"])
    assert before == snapshot(store)


def test_scoped_records_use_only_formal_coordination_links_and_explicit_task_selection(preparation):
    from test_boss_supply_quality import imported, coordination_payload
    from boss_supply_quality import COORDINATE_ACTION
    store, api, bridge = preparation
    service, _ = imported(store)
    topic = {"page_id": "F21", "use": None}
    view = api.read("BOSS", scope())
    record = next(row for row in view["topics"] if row["page_id"] == "F21")["records"][0]
    ref = {field: record[field] for field in ("kind", "id", "version")}
    request = selection(api, ref, topic)
    before = snapshot(store)
    result = bridge.read("BOSS", request)
    assert result["state"] == "WAITING_INPUT" and result["task_candidates"] == []
    assert "EXISTING_RELATED_TASK_REQUIRED" in result["missing_conditions"]
    assert result["source_references"] and result["handoff"] is None
    assert snapshot(store) == before
    params = coordination_payload(service, "n03-preparation-coordinate")
    task = service.execute("BOSS", COORDINATE_ACTION, params)
    origin = {"kind": params["origin_entity_type"], "id": params["origin_record_id"], "version": params["origin_version"]}
    request = selection(api, origin, topic)
    result = bridge.read("BOSS", request)
    candidate = {"kind": "task", "id": task["task_id"], "version": task["version"]}
    assert result["task_candidates"] == [candidate] and result["state"] == "WAITING_INPUT"
    assert "EXPLICIT_RELATED_TASK_SELECTION_REQUIRED" in result["missing_conditions"]
    reviewed = bridge.read("BOSS", selection(api, candidate, topic))
    assert reviewed["current_use_verified"] and reviewed["assignment_context"]["task_reference"] == candidate
    regional = bridge.read("BOSS", selection(api, topic=topic, selected_scope=scope("region-1")))
    assert all(row["kind"] == "task" for row in regional["candidates"])


@pytest.mark.parametrize("change", ["SOURCE", "TASK_VERSION", "SCOPE", "TOPIC"])
def test_changed_context_stops_adoption_without_replacing_old_result(preparation, change):
    store, api, bridge = preparation
    ref = create_task(store)
    request = selection(api, ref, {"page_id": "F14", "use": None})
    result = bridge.read("BOSS", request)
    if change == "SOURCE":
        store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    elif change == "TASK_VERSION":
        code, sent = BossCommandAPI(store).execute("BOSS", "boss.assignment.send", send_input({"task_id": ref["id"], "version": ref["version"]}, "n03-preparation-send"))
        assert code == 200, sent
    elif change == "SCOPE":
        request = {**request, "applied_scope": scope("region-1")}
    else:
        request = {**request, "topic_reference": None}
    before = snapshot(store)
    with pytest.raises(web.HTTPConflict):
        bridge.verify("BOSS", request, result["context_sha256"])
    assert snapshot(store) == before
    assert result["assignment_context"]["task_reference"] == ref


def test_meeting_requires_explicit_relationship_and_scoped_materials(preparation):
    from test_boss_supply_quality import imported, coordination_payload
    from boss_supply_quality import COORDINATE_ACTION
    store, api, bridge = preparation
    ref = create_task(store)
    before = snapshot(store)
    result = bridge.read("BOSS", selection(api, ref, action="MEETING_PREPARATION"))
    assert result["state"] == "WAITING_INPUT" and result["handoff"] is None
    assert result["meeting_context"]["meeting_reference"] == {"kind": "meeting", "id": "meeting-1", "version": "1"}
    assert "SCOPED_MEETING_PREPARATION_REQUIRED" in result["missing_conditions"]
    assert "MEETING_MATERIALS_OUTSIDE_SELECTED_SCOPE" in result["missing_conditions"]
    assert snapshot(store) == before
    service, _ = imported(store)
    task = service.execute("BOSS", COORDINATE_ACTION, coordination_payload(service, "n03-no-meeting-coordinate"))
    ref = {"kind": "task", "id": task["task_id"], "version": task["version"]}
    result = bridge.read("BOSS", selection(api, ref, {"page_id": "F21", "use": None}, "MEETING_PREPARATION"))
    assert result["meeting_context"] is None and result["state"] == "WAITING_INPUT"
    assert "RELATED_MEETING_REFERENCE_REQUIRED" in result["missing_conditions"]


def test_invalid_fields_roles_versions_and_unrelated_objects_do_not_write(preparation):
    store, api, bridge = preparation
    ref = create_task(store)
    request = selection(api, ref)
    before = snapshot(store)
    for role, error in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)):
        with pytest.raises(error):
            bridge.read(role, request)
    for field in ("owner_id", "namespace", "source_refs", "coordinator_id", "confirmed", "meeting_id"):
        with pytest.raises(web.HTTPBadRequest):
            bridge.read("BOSS", {**request, field: "injected"})
    with pytest.raises(web.HTTPForbidden):
        bridge.read("BOSS", {**request, "object_reference": {**ref, "id": "unrelated-task"}})
    with pytest.raises(web.HTTPConflict):
        bridge.read("BOSS", {**request, "object_reference": {**ref, "version": "999"}})
    with pytest.raises(web.HTTPConflict):
        bridge.read("BOSS", {**request, "snapshot_sha256": "0" * 64})
    with pytest.raises(web.HTTPBadRequest):
        bridge.read("BOSS", {**request, "topic_reference": {"page_id": "F14", "use": "EGG"}})
    assert snapshot(store) == before


def test_formal_assignment_handoff_runs_actual_sdk_with_same_task_and_review(preparation, tmp_path):
    from nanobot import Nanobot
    from nanobot.agent.loop import AgentLoop
    from nanobot.config.loader import save_config
    from nanobot.config.schema import Config
    from boss_runtime_records import runtime_records
    from connection import settings
    from product_assignment import ProductAssignment, AssignmentReadTool
    from product_bi import ProductBI, FeatureProvider, FeatureRecorder, FeatureToolRegistry
    from product_fc01 import ProductFc01
    from product_runtime import ProductRuntime
    from runtime_assignment_source_tool import BossAssignmentSourcesReadTool
    from sop_write_tools.fc01 import Fc01Tool, TOOLS
    settings()
    store, api, bridge = preparation
    ref = create_task(store)
    request = selection(api, ref)
    prepared = bridge.read("BOSS", request)
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(tmp_path / "workspace"), "provider": "deepseek",
        "model": "deepseek-flash", "maxToolIterations": 6, "maxTokens": 700, "maxToolResultChars": 200000,
        "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
        "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com"}}})
    path = tmp_path / "config.json"
    save_config(config, path)
    service, fc01, bi = ProductAssignment(store), ProductFc01(store), ProductBI(store)
    registry = FeatureToolRegistry()
    provider = FeatureProvider(fc01, bi, assignment=service)
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi, assignment=service)
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    tools = [AssignmentReadTool(Fc01Tool(store, fc01.context_provider, name), service) if name == "read_assignment"
        else Fc01Tool(store, fc01.context_provider, name) for name in sorted(TOOLS)]
    tools.append(AssignmentReadTool(BossAssignmentSourcesReadTool(store, "BOSS"), service))
    runtime = ProductRuntime(store, path, loop, registry, tools, provider)
    service.runtime = fc01.runtime = bi.runtime = runtime
    commands = BossCommandAPI(store, runtime)
    state = runtime.read()
    code, draft = commands.execute("MAINTAINER", "boss.runtime.save", {"client_request_id": "n03-prepare-sdk-save",
        "expected_version": state["draft"]["version"] if state["draft"] else "0", "values": {"max_tool_rounds": 6,
        "max_output_tokens": 700, "tool_scope": ["read_assignment", "assignmentSourcesRead"]}})
    assert code == 200, draft
    code, checked = commands.execute("MAINTAINER", "boss.runtime.validate", {"client_request_id": "n03-prepare-sdk-validate",
        "expected_version": draft["version"], "expected_content_sha256": draft["content_sha256"]})
    assert code == 200, checked
    code, active = commands.execute("MAINTAINER", "boss.runtime.activate", {"client_request_id": "n03-prepare-sdk-activate",
        "expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"], "expected_active_version": state["current"]["version"]})
    assert code == 200, active
    with store.connect() as db:
        before = db.execute("SELECT namespace,kind,id,body FROM objects WHERE kind NOT IN ('runtime_run','assignment_public_request') ORDER BY namespace,kind,id").fetchall()
        audit_before = db.execute("SELECT * FROM audit ORDER BY rowid").fetchall()
        idempotency_before = db.execute("SELECT * FROM idempotency ORDER BY rowid").fetchall()
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            service.bot = bot
            for context in (runtime.context, service.scope_context, recorder.context):
                bot.runtime.add_context_provider(context)
            bridge.verify("BOSS", request, prepared["context_sha256"])
            result = await service.prepare("BOSS", {"client_request_id": "n03-preparation-actual-sdk", **prepared["handoff"]["parameters"]}, lambda: True)
            bridge.verify("BOSS", request, prepared["context_sha256"])
            return result
    result = asyncio.run(execute())
    assert result["request_state"] == "SUCCEEDED" and result["adoption_state"] == "CURRENT"
    assert result["preparation"]["task"]["task_id"] == ref["id"]
    assert result["preparation"]["source_review"]["review_sha256"] == prepared["assignment_context"]["review_sha256"]
    run = next(row for row in runtime_records(store, "MAINTAINER")["runs"] if row["run_id"] == result["run_id"])
    assert [row["tool_id"] for row in run["tool_results"]] == ["read_assignment", "assignmentSourcesRead"]
    with store.connect() as db:
        assert db.execute("SELECT namespace,kind,id,body FROM objects WHERE kind NOT IN ('runtime_run','assignment_public_request') ORDER BY namespace,kind,id").fetchall() == before
        audit = db.execute("SELECT * FROM audit ORDER BY rowid").fetchall()
        assert audit[:len(audit_before)] == audit_before
        assert len(audit) == len(audit_before) + 1 and audit[-1][2] == "read_assignment"
        assert json.loads(audit[-1][4])["task_id"] == ref["id"]
        assert db.execute("SELECT * FROM idempotency ORDER BY rowid").fetchall() == idempotency_before
