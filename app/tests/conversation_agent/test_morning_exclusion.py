import asyncio
from concurrent.futures import ThreadPoolExecutor
import inspect
from uuid import uuid4

import pytest
from aiohttp import web
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop

from conftest import ROOT
from business import checksum
from boss_conversation import ConversationAPI
from controls import ControlStore
from fc03_agent.formal import FormalMorningTool, FORMAL_TOOLS
from product_morning import ProductMorning
from product_fc01 import ProductFc01
from product_bi import FeatureProvider, FeatureRecorder, FeatureToolRegistry, ProductBI
from test_native import native, read, execute, CHAT as ORDINARY_CHAT
from test_business_consumer import bind_business, CHAT
from test_task_entry_consumer import create_task, bind_task


DAY = {"date": "2026-10-24", "timezone": "Asia/Shanghai"}


def morning(native):
    service = ProductMorning(native[0])
    assert inspect.getfile(type(service.native)) == str(ROOT / "validation/fc03_agent/native.py")
    service.native.bind_sessions(native[2].sessions)
    assert service.native.native_sessions is native[1].attachments.sessions
    return service


def bind(service, chat=CHAT, key="n03-morning-original"):
    return service.native.bind("BOSS", key, {"chat_id": chat, **DAY}, attached=lambda selected: selected == chat, active=lambda: True)


def objects(store):
    with store.connect() as db:
        return (db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall(),
            db.execute("SELECT * FROM audit ORDER BY rowid").fetchall(), db.execute("SELECT * FROM idempotency ORDER BY rowid").fetchall())


def test_new_morning_binding_rejects_formal_business_binding_without_any_mutation(native):
    entry, bound = bind_business(native)
    service = morning(native)
    before = objects(native[0])
    with pytest.raises(web.HTTPConflict):
        bind(service)
    assert objects(native[0]) == before and not read(native, "morning_native_binding")
    assert entry.read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})["entry"] == bound


def test_original_morning_same_key_is_readable_after_service_reopen(native):
    service = morning(native)
    original = bind(service)
    before = objects(native[0])
    reopened = ProductMorning(ControlStore(native[0].path))
    assert bind(reopened) == original
    assert reopened.native.binding_receipt("BOSS", "n03-morning-original", active=lambda: True) == original
    assert objects(native[0]) == before


def test_new_binding_requires_actual_session_manager_without_optional_skip(native):
    service = ProductMorning(native[0])
    before = objects(native[0])
    with pytest.raises(web.HTTPServiceUnavailable):
        bind(service)
    with pytest.raises(web.HTTPBadRequest):
        service.native.bind_sessions(None)
    assert objects(native[0]) == before
    service.native.bind_sessions(native[2].sessions)
    service.native.bind_sessions(native[2].sessions)
    assert bind(service)["outcome"] == "RECORDED"


def test_new_morning_binding_rejects_actual_task_binding(native):
    task = create_task(native, "n03-morning-task-owner")
    bind_task(native, task, chat=CHAT)
    service = morning(native)
    before = objects(native[0])
    with pytest.raises(web.HTTPConflict):
        bind(service)
    assert objects(native[0]) == before and not read(native, "morning_native_binding")


def test_new_morning_binding_rejects_real_admitted_intent(native):
    admitted = native[1].admit("BOSS", CHAT, str(uuid4()), "查看当前任务", media_sha256=checksum([]),
        attached=lambda chat: chat == CHAT, active=lambda: True)
    service = morning(native)
    before = objects(native[0])
    with pytest.raises(web.HTTPConflict):
        bind(service)
    assert objects(native[0]) == before and not read(native, "morning_native_binding")
    native[1].finish(admitted["client_request_id"], status="CANCELED")


def test_new_morning_binding_rejects_completed_actual_sdk_session(native):
    execute(native, ["查看当前任务"])
    snapshot = native[2].sessions.read_session_snapshot("websocket:" + ORDINARY_CHAT)
    assert any(row["role"] == "user" for row in snapshot.messages)
    service = morning(native)
    before = objects(native[0])
    with pytest.raises(web.HTTPConflict):
        bind(service, chat=ORDINARY_CHAT)
    assert objects(native[0]) == before and not read(native, "morning_native_binding")


def test_history_same_key_stays_readable_after_source_change_and_new_key_rejected(native):
    service = morning(native)
    original = bind(service)
    native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    before = objects(native[0])
    reopened = ProductMorning(ControlStore(native[0].path))
    assert bind(reopened) == original
    assert objects(native[0]) == before
    reopened.native.bind_sessions(native[2].sessions)
    with pytest.raises(web.HTTPConflict):
        bind(reopened, key="n03-morning-new-request")
    assert objects(native[0]) == before
    assert reopened.native.binding_receipt("BOSS", "n03-morning-unknown", active=lambda: True)["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"


def test_actual_morning_and_business_bindings_share_atomic_exclusion(native):
    store = native[0]
    service = morning(native)
    business_entry = ConversationAPI(store).business_entry(native[2].sessions)
    from boss_business_overview import BusinessOverviewAPI
    dimensions = BusinessOverviewAPI(store).dimensions("BOSS")
    current = next(row for row in dimensions["periods"] if row["id"] == "CURRENT")
    scope = {"legal_entity_id": dimensions["legal_entity_ids"][0], "region_id": None,
        "period_start": current["period_start"], "period_end": current["period_end"],
        "timezone": dimensions["timezones"][0], "attention": "ALL"}
    view = BusinessOverviewAPI(store).read("BOSS", scope)
    prepared = business_entry.prepare("BOSS", {"client_request_id": "n03-concurrent-business", "applied_scope": scope,
        "snapshot_sha256": view["snapshot_sha256"], "topic_reference": None})
    sessions = native[2].sessions
    sessions.save(sessions.get_or_create("websocket:" + CHAT))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(bind, service), executor.submit(business_entry.bind, "BOSS",
            {**{field: prepared[field] for field in ("client_request_id", "preparation_id", "preparation_sha256")}, "chat_id": CHAT})]
    assert sum(future.exception() is None for future in futures) == 1
    assert sum(isinstance(future.exception(), web.HTTPConflict) for future in futures) == 1
    assert len(read(native, "morning_native_binding")) + len(read(native, "conversation_business_binding")) == 1


def test_unoccupied_morning_two_actual_sdk_turns_preserve_existing_flow(native):
    store, ordinary_agent, _, config, _ = native
    service = morning(native)
    registry = FeatureToolRegistry()
    bi = ProductBI(store)
    provider = FeatureProvider(ProductFc01(store), bi, service)
    provider.generation = config.resolve_preset().to_generation_settings()
    recorder = FeatureRecorder(store, registry, ordinary_agent.recorder.runtime_snapshot, bi, service)
    loop = AgentLoop.from_config(config, session_manager=service.native.native_sessions, provider=provider,
        tool_registry=registry, hook_factories=[recorder.hook_factory, service.native.hook_factory])
    assert loop.sessions is service.native.native_sessions
    for name in list(registry.tool_names):
        registry.unregister(name)
    for name in sorted(FORMAL_TOOLS):
        registry.register(FormalMorningTool(store, service.context_provider, name))
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
        configuration["tool_scope"] = sorted(FORMAL_TOOLS)
        store.put(db, "ui-check", "configuration", "current", configuration)
    original = bind(service)
    questions = ["今天有哪些事情需要本人处理", "继续讨论当前清单，说明需要处理的事项"]
    async def check():
        async with Nanobot(loop, config=config) as bot:
            async def transport(request):
                request.metadata["webui_turn_id"] = request.turn_id
                admitted = service.native.admit("BOSS", request.chat_id, request.turn_id, request.original_user_text,
                    attached=lambda chat: chat == CHAT, active=lambda: True)
                assert admitted["enqueue"]
            removes = [bot.runtime.add_context_provider(provider) for provider in
                (transport, service.native.native_context, recorder.context)]
            try:
                return [await bot.run(question, channel="websocket", chat_id=CHAT, session_key="websocket:" + CHAT,
                    sender_id="boss-1") for question in questions]
            finally:
                for remove in reversed(removes):
                    remove()
    results = asyncio.run(check())
    assert all(not result.error and "当前模拟资料" in result.content for result in results)
    runs = read(native, "runtime_run")
    assert len(runs) == 2 and {row["session_id"] for row in runs} == {"websocket:" + CHAT}
    assert {row["feature_id"] for row in runs} == {"FC03"} and [len(row["tool_results"]) for row in runs] == [4, 3]
    assert len(read(native, "morning_list")) == 1 and not service.native.proofs
    assert not read(native, "authorization") and not read(native, "outbox")
    reopened = ProductMorning(ControlStore(store.path))
    current = bind(reopened)
    assert current["result"]["binding_id"] == original["result"]["binding_id"]
    assert current["result"]["last_request_id"] == runs[-1]["morning_context"]["client_request_id"]
