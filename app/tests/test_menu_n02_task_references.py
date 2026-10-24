import asyncio
import inspect
import json
import os
from pathlib import Path

import pytest

# 准确提交的原始依赖使用独立目录，Runtime继续核查真实源码指纹。
DEPENDENCY = Path(os.environ["MENU_N02_CONVERSATION_ROOT"]).resolve()
assert (DEPENDENCY / "validation/conversation_agent/native.py").is_file()

from test_menu_n02_context_references import (
    ROOT, BossCommandAPI, Config, ControlStore, ConversationAPI, Nanobot, SessionManager, AgentLoop,
    checksum, source,
)
from boss_conversation_attachments import ConversationAttachments
from boss_conversation_references import ConversationReferences
from conversation_agent.native import NativeConversationAgent
from conversation_agent.domain import ConversationPlanner
from conversation_agent.runtime import ConversationRuntimeRecorder
from product_bi import FeatureToolRegistry
from test_boss_command_api import create_input


CHAT = "n02-task-reference"
CONTEXT = {"session_id": "websocket:" + CHAT, "chat_id": CHAT}


def business_snapshot(store):
    with store.connect() as db:
        return (db.execute("SELECT namespace,kind,id,body FROM objects WHERE kind NOT IN "
            "('runtime_run','conversation_intent') ORDER BY namespace,kind,id").fetchall(),
            db.execute("SELECT * FROM audit ORDER BY rowid").fetchall(),
            db.execute("SELECT * FROM idempotency ORDER BY rowid").fetchall())


def actual_native_task(store, tmp_path, task):
    for implementation in (NativeConversationAgent, ConversationPlanner, ConversationRuntimeRecorder):
        assert Path(inspect.getfile(implementation)).resolve().is_relative_to(DEPENDENCY)
    assert Path(inspect.getfile(ConversationAPI)).resolve() == ROOT / "validation/boss_conversation.py"
    assert Path(inspect.getfile(ConversationReferences)).resolve() == ROOT / "validation/boss_conversation_references.py"
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(tmp_path / "workspace"),
        "provider": "deepseek", "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "native-sessions")
    media_root = tmp_path / "media"
    media_root.mkdir()
    registry = FeatureToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions",
        "max_tool_rounds": 12, "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    agent = NativeConversationAgent(store, registry, lambda: snapshot, ConversationAttachments(sessions, media_root))
    agent.provider.generation = config.resolve_preset().to_generation_settings()
    loop = AgentLoop.from_config(config, session_manager=sessions, provider=agent.provider, tool_registry=registry,
        hook_factories=[agent.recorder.hook_factory])
    for name in list(registry.tool_names):
        registry.unregister(name)
    for tool in agent.tools():
        registry.register(tool)
    assert len(registry.tool_names) == 7
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
        configuration["tool_scope"] = sorted(registry.tool_names)
        store.put(db, "ui-check", "configuration", "current", configuration)
    before = business_snapshot(store)
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            async def transport(request):
                request.metadata["webui_turn_id"] = request.turn_id
                admitted = agent.admit("BOSS", CHAT, request.turn_id, request.original_user_text,
                    media_sha256=checksum([]), attached=lambda chat: chat == CHAT, active=lambda: True)
                assert admitted is not None and admitted["enqueue"]
            async def recorder(request):
                assert agent.handles(request)
                return await agent.recorder.context(request)
            for provider in (transport, agent.native_context, agent.scope_context, recorder):
                bot.runtime.add_context_provider(provider)
            return await bot.run("读取任务 " + task["task_id"], channel="websocket", chat_id=CHAT,
                session_key=CONTEXT["session_id"], sender_id="boss-1")
    result = asyncio.run(execute())
    assert not result.error
    assert business_snapshot(store) == before
    with store.connect() as db:
        runs = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run'")]
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "SUCCEEDED" and run["conversation_context"]["references"] == []
    assert len(run["tool_results"]) == 1
    step = run["tool_results"][0]
    assert step["tool_id"] == "conversationRead" and step["task_id"] == task["task_id"] and step["task_version"] == task["version"]
    return run


@pytest.fixture
def native_task(tmp_path):
    store = ControlStore(tmp_path / "task-reference.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    original = source(store)
    status, task = commands.execute("BOSS", "boss.assignment.create", create_input("n02-task-reference-create"))
    assert status == 200, task
    run = actual_native_task(store, tmp_path, task)
    return store, commands, task, original, run


def task_reference(store, task):
    before = business_snapshot(store)
    view = ConversationAPI(ControlStore(store.path)).read("BOSS", CONTEXT)
    assert business_snapshot(store) == before
    refs = [ref for ref in view["runs"][0]["context_references"] if ref["kind"] == "task" and ref["id"] == task["task_id"]]
    assert len(refs) == 1
    return refs[0], view


def test_actual_native_task_read_has_tool_support_and_current_formal_sources(native_task):
    store, commands, task, source_input, run = native_task
    ref, view = task_reference(store, task)
    assert ref["recorded_version"] == ref["current_version"] == task["version"]
    assert ref["current_object_state"] == task["status"]
    assert ref["reference_state"] == ref["adoption_state"] == "CURRENT"
    assert ref["support"] == [{"origin": "TOOL_RESULT", "tool_id": "conversationRead", "tool_call_id": run["tool_results"][0]["tool_call_id"]}]
    assert ref["source_refs"] == [{"source_id": source_input["source_id"], "version": "1", "current_version": "1", "status": "VALID"}]
    assert "读取任务 " not in json.dumps(view, ensure_ascii=False)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert store.get(db, "ui-check", "task", task["task_id"])["version"] == task["version"]


def test_actual_task_read_keeps_history_after_formal_source_withdrawal(native_task):
    store, commands, task, source_input, run = native_task
    store.control("ui-check", "withdraw", {"source_id": source_input["source_id"], "version": source_input["version"]})
    ref, view = task_reference(store, task)
    assert view["runs"][0]["run_id"] == run["run_id"] and view["runs"][0]["status"] == "SUCCEEDED"
    assert ref["recorded_version"] == ref["current_version"] == task["version"]
    assert ref["reference_state"] == ref["adoption_state"] == "NEEDS_REVIEW"
    assert ref["source_refs"][0]["version"] == ref["source_refs"][0]["current_version"] == source_input["version"]
    assert ref["source_refs"][0]["status"] == "WITHDRAWN"
    assert ref["support"][0]["tool_call_id"] == run["tool_results"][0]["tool_call_id"]
    with store.connect() as db:
        assert store.get(db, "ui-check", "runtime_run", run["run_id"]) == run


def test_actual_coordination_task_keeps_history_after_formal_source_revision(tmp_path):
    from boss_supply_quality import IMPORT_ACTION, COORDINATE_ACTION, SupplyQualityAPI
    from test_boss_supply_quality import coordination_payload, definition
    store = ControlStore(tmp_path / "task-revision.sqlite")
    store.initialize("ui-check")
    service = SupplyQualityAPI(store)
    manifest = definition()["initial_request"]
    imported = service.execute("MAINTAINER", IMPORT_ACTION, manifest)
    assert imported["state"] == "SUCCESS"
    task = service.execute("BOSS", COORDINATE_ACTION, coordination_payload(service, "n02-task-source-coordinate"))
    run = actual_native_task(store, tmp_path, task)
    ref, _ = task_reference(store, task)
    assert ref["reference_state"] == "CURRENT"
    link = task["coordination_link"]
    record = next(row for row in manifest["records"] if row["entity_type"] == link["origin_entity_type"]
        and row["data"]["event_id"] == link["origin_record_id"])
    revised = service.execute("MAINTAINER", IMPORT_ACTION, {**manifest,
        "client_request_id": "n02-task-source-reimport", "records": [{**record, "expected_version": link["origin_version"]}]})
    assert revised["state"] == "SUCCESS"
    ref, view = task_reference(store, task)
    assert view["runs"][0]["status"] == "SUCCEEDED"
    assert ref["recorded_version"] == ref["current_version"] == task["version"]
    assert ref["reference_state"] == ref["adoption_state"] == "NEEDS_REVIEW"
    assert any(row["version"] == "1" and row["current_version"] == "2" and row["status"] == "CHANGED" for row in ref["source_refs"])
    with store.connect() as db:
        assert store.get(db, "ui-check", "runtime_run", run["run_id"]) == run
