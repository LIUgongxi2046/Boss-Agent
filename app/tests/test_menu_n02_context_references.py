import asyncio
from datetime import datetime
import inspect
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode
from uuid import uuid4

import pytest
import yaml
from aiohttp import web
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = Path(os.environ["MENU_N02_PRODUCT_ROOT"])
sys.path.insert(0, str(PRODUCT / "validation"))
from boss_page_api import BossPageAPI
from boss_command_api import BossCommandAPI
from boss_runtime_records import runtime_records
from conversation_agent import ConversationContext, ConversationScope, register_conversation_reads
from conversation_agent.runtime import ConversationRuntimeRecorder, ConversationSimulatedProvider
from runtime_page_read_tools import BossEvidenceReadTool

sys.path.insert(0, str(ROOT / "validation"))
from boss_conversation import ConversationAPI, SCHEMA
from boss_simulation_api import KINDS, SimulationAPI
from boss_supply_quality import DEFINITION, IMPORT_ACTION, SupplyQualityAPI
from business import checksum, encode
from controls import ControlStore


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("N02上下文引用检查禁止外部连接")


sys.addaudithook(prohibit_network)


@pytest.fixture
def store(tmp_path):
    assert Path(inspect.getfile(ConversationAPI)).resolve() == ROOT / "validation/boss_conversation.py"
    value = ControlStore(tmp_path / "context.sqlite")
    value.initialize("ui-check")
    return value


def source(store, identifier="finance-note"):
    status, value = BossPageAPI(store).serve("BOSS", "/api/boss/ui/evidence", urlencode({"source": identifier}))
    assert status == 200, value
    return value


def actual_conversation(store, directory, document, *, references=None, chat_id="n02-context"):
    api = BossPageAPI(store)
    references = references if references is not None else (("document", document["source_id"], document["version"]),)
    state = {}
    def validate_current(context):
        for kind, identifier, version in context.references:
            if kind == "document":
                code, row = api.serve("BOSS", "/api/boss/ui/evidence", urlencode({"source": identifier}))
                if code != 200 or row["version"] != version:
                    return False
            else:
                interface = next(interface for interface, kinds in KINDS.items() if kind in kinds)
                rows = SimulationAPI(store).query("BOSS", {"interface_id": interface, "object_ids": [kind + ":" + identifier], "filters": {}})["records"]
                if not any(row["entity_type"] == kind and row["object_id"] == identifier and row["version"] == version
                           and row["data"] is not None for row in rows):
                    return False
        return True
    scope = ConversationScope(store, lambda request: state[request.turn_id], validate_current)
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(directory / "workspace"),
        "provider": "deepseek", "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    params = {"source": document["source_id"]}
    async def actual_source_events(messages, tools):
        last_user = max(index for index, item in enumerate(messages) if item["role"] == "user")
        outputs = [json.loads(item["content"]) for item in messages[last_user + 1:] if item["role"] == "tool"]
        if not outputs:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="bossEvidenceRead", arguments=params)])
        return LLMResponse(content=encode(outputs[-1]))
    registry = ToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions",
        "max_tool_rounds": 12, "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    recorder = ConversationRuntimeRecorder(scope, registry, lambda: snapshot)
    provider = ConversationSimulatedProvider(actual_source_events, scope)
    provider.generation = config.resolve_preset().to_generation_settings()
    sessions = SessionManager(directory / "workspace", sessions_root=directory / "native-sessions")
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry,
        hook_factories=[recorder.hook_factory], session_manager=sessions)
    for name in list(registry.tool_names):
        registry.unregister(name)
    register_conversation_reads(registry, [BossEvidenceReadTool(api, "BOSS")], scope)
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
        configuration["tool_scope"] = registry.tool_names
        store.put(db, "ui-check", "configuration", "current", configuration)
    question = "读取当前资料 " + document["source_id"]
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            async def authenticated_input(request):
                state[request.turn_id] = ConversationContext("BOSS", "boss-1", "ui-check", "selection", "1", request.turn_id,
                    request.session_key, request.chat_id, request.turn_id, True, checksum(request.original_user_text),
                    frozenset({"bossEvidenceRead"}), frozenset({("bossEvidenceRead", checksum(params))}), references)
            bot.runtime.add_context_provider(authenticated_input)
            bot.runtime.add_context_provider(recorder.context)
            return await bot.run(question, sender_id="boss-1", channel="websocket", chat_id=chat_id, session_key="websocket:" + chat_id)
    result = asyncio.run(execute())
    assert not result.error and json.loads(result.content)["source_id"] == document["source_id"]
    run = next(row for row in runtime_records(store, "MAINTAINER")["runs"] if row["session_id"] == "websocket:" + chat_id)
    assert run["status"] == "SUCCEEDED" and run["feature_id"] == "N02"
    return run, {"session_id": run["session_id"], "chat_id": run["chat_id"]}, question


def test_actual_sdk_source_context_preserves_history_and_current_metadata(store, tmp_path):
    document = source(store)
    run, context, question = actual_conversation(store, tmp_path, document)
    with store.connect() as db:
        before = db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()
        audit = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    view = ConversationAPI(store).read("BOSS", context)
    row = view["runs"][0]
    assert row["origin_references"]["conversation_context"] == run["conversation_context"]
    ref = row["context_references"][0]
    assert (ref["kind"], ref["id"], ref["recorded_version"], ref["current_version"]) == ("document", document["source_id"], document["version"], document["version"])
    assert ref["reference_state"] == ref["adoption_state"] == "CURRENT"
    assert ref["current_validity"] == "VALID"
    assert ref["source_metadata"]["author_contact_id"] == document["author_contact_id"]
    assert ref["source_metadata"]["published_at"] == document["published_at"]
    assert {item["origin"] for item in ref["support"]} == {"CONVERSATION_CONTEXT", "TOOL_RESULT"}
    assert next(item for item in ref["support"] if item["origin"] == "TOOL_RESULT")["tool_call_id"] == run["tool_results"][0]["tool_call_id"]
    assert row["tool_steps"][0]["source_id"] == document["source_id"]
    assert document["content"] not in json.dumps(view, ensure_ascii=False) and question not in json.dumps(view, ensure_ascii=False)
    assert "original_locator" not in json.dumps(view) and "parameters\"" not in json.dumps(view)
    assert ConversationAPI(ControlStore(store.path)).read("BOSS", context) == view
    with store.connect() as db:
        assert db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall() == before
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == audit


def test_source_withdrawal_keeps_recorded_reference_and_original_runtime(store, tmp_path):
    document = source(store)
    run, context, _ = actual_conversation(store, tmp_path, document)
    store.control("ui-check", "withdraw", {"source_id": document["source_id"], "version": document["version"]})
    row = ConversationAPI(ControlStore(store.path)).read("BOSS", context)["runs"][0]
    ref = row["context_references"][0]
    assert row["run_id"] == run["run_id"] and row["status"] == "SUCCEEDED"
    assert row["origin_references"]["conversation_context"] == run["conversation_context"]
    assert ref["recorded_version"] == ref["current_version"] == document["version"]
    assert ref["current_validity"] == "WITHDRAWN" and ref["reference_state"] == ref["adoption_state"] == "NEEDS_REVIEW"
    assert ref["source_metadata"] is None
    assert BossPageAPI(store).serve("BOSS", "/api/boss/ui/evidence", urlencode({"source": document["source_id"]}))[0] == 410
    assert runtime_records(store, "MAINTAINER")["runs"][0] == run


def test_current_source_version_never_replaces_recorded_runtime_version(store, tmp_path):
    original = source(store)
    payload = {"client_request_id": "n02-context-source-create", "source_id": "sim-doc-n02-context",
        "title": original["source_id"], "author_contact_id": original["author_contact_id"],
        "published_at": datetime.fromisoformat(original["published_at"]).date().isoformat(), "content": original["content"]}
    commands = BossCommandAPI(store)
    status, created = commands.execute("MAINTAINER", "boss.knowledge.source.create", payload)
    assert status == 200, created
    document = source(store, created["source_id"])
    run, context, _ = actual_conversation(store, tmp_path, document)
    status, revised = commands.execute("MAINTAINER", "boss.knowledge.source.revise",
        {**payload, "client_request_id": "n02-context-source-revise", "expected_version": created["version"]})
    assert status == 200, revised
    ref = ConversationAPI(store).read("BOSS", context)["runs"][0]["context_references"][0]
    assert ref["recorded_version"] == created["version"] and ref["current_version"] == revised["version"]
    assert ref["reference_state"] == "VERSION_CHANGED" and ref["adoption_state"] == "NEEDS_REVIEW"
    assert ref["source_metadata"] is None and ref["current_validity"] == "VALID"
    assert source(store, created["source_id"])["version"] == revised["version"]
    assert runtime_records(store, "MAINTAINER")["runs"][0] == run


def imported_source(store):
    definition = yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())
    result = SupplyQualityAPI(store).execute("MAINTAINER", IMPORT_ACTION, definition["initial_request"])
    assert result["state"] == "SUCCESS"
    with store.connect() as db:
        documents = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='document' "
            "AND json_extract(body,'$.simulation_definition')=? ORDER BY id", (DEFINITION,))]
        initial = store.get(db, "ui-check", "initial", "snapshot")
        from boss_supply_quality import external_adoption
        for document in documents:
            adoption = external_adoption(db, "ui-check", initial, store.get(db, "ui-check", "clock", "current")["at"], document)
            if adoption["state"] == "CURRENT" and any(row["source_id"] != document["source_id"] for row in adoption["dependencies"]):
                return document, adoption
    raise AssertionError("获准导入没有产生可核查的传递来源")


@pytest.mark.parametrize("change", ["EXPIRED", "DEPENDENCY_WITHDRAWN"])
def test_source_time_and_transitive_adoption_stop_current_use_without_hiding_run(store, tmp_path, change):
    document, adoption = imported_source(store)
    run, context, _ = actual_conversation(store, tmp_path, source(store, document["source_id"]))
    if change == "EXPIRED":
        store.control("ui-check", "clock", {"at": document["valid_until"]})
    else:
        dependency = next(row for row in adoption["dependencies"] if row["source_id"] != document["source_id"])
        store.control("ui-check", "withdraw", {"source_id": dependency["source_id"], "version": dependency["version"]})
    ref = ConversationAPI(store).read("BOSS", context)["runs"][0]["context_references"][0]
    assert ref["recorded_version"] == ref["current_version"] == document["version"]
    assert ref["reference_state"] == ref["adoption_state"] == "NEEDS_REVIEW"
    assert ref["source_metadata"] is None
    assert ref["current_validity"] == ("EXPIRED" if change == "EXPIRED" else "VALID")
    if change == "DEPENDENCY_WITHDRAWN":
        assert any(row["status"] == "WITHDRAWN" for row in ref["source_refs"])
    assert runtime_records(store, "MAINTAINER")["runs"][0] == run


def test_current_task_context_uses_formal_object_and_source_versions(store, tmp_path):
    from test_boss_command_api import create_input, send_input
    commands = BossCommandAPI(store)
    status, task = commands.execute("BOSS", "boss.assignment.create", create_input("n02-context-task"))
    assert status == 200, task
    document = source(store)
    run, context, _ = actual_conversation(store, tmp_path, document, references=(("task", task["task_id"], task["version"]),))
    api = ConversationAPI(store)
    ref = next(row for row in api.read("BOSS", context)["runs"][0]["context_references"] if row["kind"] == "task")
    assert ref["recorded_version"] == ref["current_version"] == task["version"]
    assert ref["reference_state"] == ref["adoption_state"] == "CURRENT" and ref["current_object_state"] == task["status"]
    assert ref["source_refs"][0]["source_id"] == document["source_id"] and ref["source_refs"][0]["status"] == "VALID"
    detail_request = {**context, "run_id": run["run_id"], "kind": "task", "id": task["task_id"]}
    assert api.artifact("BOSS", detail_request)["data"]["task_id"] == task["task_id"]
    assert api.read("BOSS", context)["runs"][0]["artifacts"] == []
    status, sent = commands.execute("BOSS", "boss.assignment.send", send_input(task, "n02-context-task-send"))
    assert status == 200, sent
    updated = next(row for row in api.read("BOSS", context)["runs"][0]["context_references"] if row["kind"] == "task")
    assert updated["recorded_version"] == task["version"] and updated["current_version"] != task["version"]
    assert updated["reference_state"] == "VERSION_CHANGED" and updated["adoption_state"] == "NEEDS_REVIEW"
    store.control("ui-check", "withdraw", {"source_id": document["source_id"], "version": document["version"]})
    updated = next(row for row in api.read("BOSS", context)["runs"][0]["context_references"] if row["kind"] == "task")
    assert updated["reference_state"] == "NEEDS_REVIEW" and updated["source_refs"][0]["status"] == "WITHDRAWN"
    with pytest.raises(web.HTTPGone):
        api.artifact("BOSS", detail_request)


def test_context_projection_rejects_roles_injection_and_other_session_or_run(store, tmp_path):
    document = source(store)
    run, context, question = actual_conversation(store, tmp_path / "current", document)
    other, other_context, _ = actual_conversation(store, tmp_path / "other", source(store, "meeting-minutes"), chat_id="n02-other")
    api = ConversationAPI(store)
    assert [row["run_id"] for row in api.read("BOSS", context)["runs"]] == [run["run_id"]]
    assert [row["run_id"] for row in api.read("BOSS", other_context)["runs"]] == [other["run_id"]]
    for role, error in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)):
        with pytest.raises(error):
            api.read(role, context)
    for field in ("source_id", "id", "run_id", "role", "owner_id", "namespace", "references"):
        with pytest.raises(web.HTTPBadRequest):
            api.read("BOSS", {**context, field: document["source_id"]})
    for run_id in (run["run_id"], other["run_id"]):
        with pytest.raises(web.HTTPForbidden):
            api.artifact("BOSS", {**context, "run_id": run_id, "kind": "task", "id": document["source_id"]})
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(SCHEMA)
    invalid = json.loads(json.dumps(api.read("BOSS", context)))
    invalid["runs"][0]["context_references"][0]["source_metadata"]["content"] = document["content"]
    assert not Draft202012Validator({**SCHEMA, "$ref": "#/$defs/View"}).is_valid(invalid)


def test_actual_tool_reference_and_unknown_object_version_keep_distinct_origins(store, tmp_path):
    contacts = SimulationAPI(store).query("BOSS", {"interface_id": "SI02", "object_ids": [], "filters": {}})["records"]
    contact = next(row for row in contacts if row["entity_type"] == "contact" and row["version"] is None)
    document = source(store)
    run, context, _ = actual_conversation(store, tmp_path, document,
        references=((contact["entity_type"], contact["object_id"], contact["version"]),))
    refs = ConversationAPI(store).read("BOSS", context)["runs"][0]["context_references"]
    source_ref = next(row for row in refs if row["kind"] == "document")
    assert source_ref["reference_state"] == "CURRENT"
    assert source_ref["support"] == [{"origin": "TOOL_RESULT", "tool_id": "bossEvidenceRead", "tool_call_id": run["tool_results"][0]["tool_call_id"]}]
    contact_ref = next(row for row in refs if row["kind"] == "contact")
    assert contact_ref["recorded_version"] is contact_ref["current_version"] is None
    assert contact_ref["reference_state"] == "VERSION_UNRECORDED" and contact_ref["adoption_state"] == "NEEDS_REVIEW"
    assert contact_ref["support"] == [{"origin": "CONVERSATION_CONTEXT", "tool_id": None, "tool_call_id": None}]


def test_generated_source_preserves_actual_author_scope_and_business_time(store, tmp_path):
    from test_fc02_bi_scenarios import load
    loaded = load(store, "weighted-ratios")
    assert loaded["source_type"] == "SIMULATED"
    with store.connect() as db:
        document = json.loads(db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='document' "
            "AND json_extract(body,'$.simulation_definition')='FC02-BI-1' ORDER BY id LIMIT 1").fetchone()[0])
    run, context, _ = actual_conversation(store, tmp_path, source(store, document["source_id"]))
    ref = ConversationAPI(store).read("BOSS", context)["runs"][0]["context_references"][0]
    assert ref["reference_state"] == "CURRENT"
    for field in ("author_contact_id", "author_kind", "author_display_name", "generator_version", "coverage", "business_basis",
                  "business_basis_description", "allowed_use", "observed_at", "valid_from", "valid_until"):
        assert ref["source_metadata"][field] == document[field]
    assert document["content"] not in json.dumps(ref) and document["original_locator"] not in json.dumps(ref)
