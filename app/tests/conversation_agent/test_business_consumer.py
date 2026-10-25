import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
import yaml
from aiohttp import web
from nanobot import Nanobot

from business import checksum
from boss_business_overview import BusinessOverviewAPI
from boss_conversation import ConversationAPI
from product_conversation import ProductConversation
from controls import ControlStore
from conftest import ROOT
from boss_supply_quality import SupplyQualityAPI, IMPORT_ACTION
from test_task_entry_schema import current_validator
from test_native import native, read
from test_cancel_deadline import arguments, run_for


CHAT = "n03-bound-consumer"
pytestmark = pytest.mark.parametrize("native", [ProductConversation], indirect=True)


@asynccontextmanager
async def session(native, *, selection_current=None):
    _, agent, loop, config, _ = native
    async with Nanobot(loop, config=config) as bot:
        async def transport(request):
            request.metadata["webui_turn_id"] = request.turn_id
            current = agent.business_entry.read("BOSS", {"session_id": request.session_key, "chat_id": request.chat_id})["entry"]
            selected = (current["preparation_id"], current["preparation_sha256"])
            accepted = agent.admit_business("BOSS", request.chat_id, request.turn_id, request.original_user_text,
                media_sha256=checksum([]), attached=lambda chat: chat == request.chat_id, active=lambda: True,
                selection_current=selection_current if selection_current is not None else lambda: selected)
            assert accepted is not None and accepted["enqueue"]
        providers = (transport, agent.native_context, agent.guard_context(agent.scope_context), agent.guard_context(agent.recorder.context))
        removes = [bot.runtime.add_context_provider(provider) for provider in providers]
        try:
            yield bot, None
        finally:
            for remove in reversed(removes):
                remove()


def bind_business(native, topic=None, **changes):
    store, agent = native[:2]
    api = BusinessOverviewAPI(store)
    dimensions = api.dimensions("BOSS")
    period = next(row for row in dimensions["periods"] if row["id"] == "CURRENT")
    scope = {"legal_entity_id": dimensions["legal_entity_ids"][0], "region_id": None,
        "period_start": period["period_start"], "period_end": period["period_end"],
        "timezone": dimensions["timezones"][0], "attention": "ALL", **changes}
    view = api.read("BOSS", scope)
    entry = ConversationAPI(store).business_entry(agent.attachments.sessions)
    prepared = entry.prepare("BOSS", {"client_request_id": "n03-consumer-original", "applied_scope": scope,
        "snapshot_sha256": view["snapshot_sha256"], "topic_reference": topic})
    sessions = agent.attachments.sessions
    sessions.save(sessions.get_or_create("websocket:" + CHAT))
    bound = entry.bind("BOSS", {**{field: prepared[field] for field in ("client_request_id", "preparation_id", "preparation_sha256")}, "chat_id": CHAT})
    return entry, bound


def enable_business(native):
    native[1].registry.conversation = native[1]
    for tool in native[1].business_tools():
        native[1].registry.register(tool)
    with native[0].connect() as db:
        config = native[0].get(db, "ui-check", "configuration", "current")
        config["tool_scope"] = sorted(native[1].registry.configured_tool_names)
        native[0].put(db, "ui-check", "configuration", "current", config)


def test_native_business_binding_drives_exact_query_parameters_and_followup(native):
    entry, bound = bind_business(native)
    enable_business(native)
    async def check():
        async with session(native) as (bot, _):
            return [await bot.run(text, **arguments(CHAT)) for text in ("查询毛利", "继续，指标改为收入")]
    results = asyncio.run(check())
    assert all(not result.error and "查询编号" in result.content for result in results)
    queries = read(native, "query")
    assert len(queries) == 2
    for query in queries:
        scope = query["context_snapshot"]
        assert scope["legal_entity_id"] == bound["applied_scope"]["legal_entity_id"]
        assert scope["period_start"] == bound["applied_scope"]["period_start"]
        assert scope["source_ids"] == ["finance-note"]
    assert queries[0]["context_snapshot"]["metric_ids"] == ["gross_profit"]
    assert queries[1]["context_snapshot"]["metric_ids"] == ["revenue"]
    assert queries[1]["context_snapshot"]["parent_query_id"] == queries[0]["query_id"]
    for run in read(native, "runtime_run"):
        current_validator().validate(run)
        assert run["conversation_context"]["business_entry"]["preparation_sha256"] == bound["preparation_sha256"]
        assert run["tool_results"][0]["tool_id"] == "businessOverviewRead"
    assert entry.read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})["entry"] == bound
    assert not read(native, "task") and not read(native, "authorization")


def test_missing_topic_does_not_query_unrelated_sales(native):
    entry, bound = bind_business(native, {"page_id": "F19", "use": "EGG"})
    enable_business(native)
    async def check():
        async with session(native) as (bot, _):
            return await bot.run("查询收入并查看当前专题", **arguments(CHAT))
    result = asyncio.run(check())
    assert "待补充" in result.content and "F19" in result.content and "EGG" in result.content
    assert not read(native, "query")
    run = run_for(native, CHAT)
    assert run["status"] == "WAITING_INPUT" and len(run["tool_results"]) == 1
    assert run["conversation_context"]["business_entry"]["topic_reference"] == bound["topic_reference"]


def test_business_native_admission_precedes_morning_candidate_and_task_entry(native):
    entry, bound = bind_business(native)
    enable_business(native)
    agent = native[1]
    assert agent.business_admission("BOSS", CHAT, attached=lambda chat: chat == CHAT, active=lambda: True)
    turn = str(uuid4())
    accepted = agent.admit_business("BOSS", CHAT, turn, "请继续晨间经营讨论", media_sha256=checksum([]),
        attached=lambda chat: chat == CHAT, active=lambda: True,
        selection_current=lambda: (bound["preparation_id"], bound["preparation_sha256"]))
    assert accepted["enqueue"] and not agent.morning_claimed(CHAT)
    assert not read(native, "morning_native_binding") and not read(native, "conversation_task_binding")
    agent.finish(accepted["client_request_id"], status="CANCELED")
    assert entry.read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})["entry"] == bound
    assert agent.admit_business("BOSS", CHAT, None, "/stop", media_sha256=None, attached=None, active=None) is None


@pytest.mark.parametrize("text", ["查询毛利，法人改为entity-unavailable", "查询毛利，关注条件改为任意条件", "查询指标改为未支持指标", "查询收入，仅看未支持条件", "查询海外收入", "查询收入，scenario-unavailable"])
def test_unsupported_supplement_waits_without_query_or_scope_replacement(native, text):
    entry, bound = bind_business(native)
    enable_business(native)
    async def check():
        async with session(native) as (bot, _):
            return await bot.run(text, **arguments(CHAT))
    result = asyncio.run(check())
    assert "待补充" in result.content and not read(native, "query")
    assert run_for(native, CHAT)["status"] == "WAITING_INPUT"
    assert entry.read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})["entry"] == bound


@pytest.mark.parametrize("change", ["SOURCE", "SESSION"])
def test_bound_model_step_rechecks_actual_entry_after_saved_query(native, change):
    entry, bound = bind_business(native)
    enable_business(native)
    agent = native[1]
    original = agent.provider.event_producer
    async def check():
        waiting, release = asyncio.Event(), asyncio.Event()
        async def delayed(messages, tools):
            start = max(index for index, row in enumerate(messages) if row["role"] == "user")
            if len([row for row in messages[start + 1:] if row["role"] == "tool"]) == 2:
                waiting.set()
                await release.wait()
            return await original(messages, tools)
        agent.provider.event_producer = delayed
        async with session(native) as (bot, _):
            stream = await bot.run_streamed("查询毛利", **arguments(CHAT))
            await asyncio.wait_for(waiting.wait(), 20)
            before = run_for(native, CHAT)
            assert len(before["tool_results"]) == 2 and len(read(native, "query")) == 1
            if change == "SOURCE":
                native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
            else:
                sessions = agent.attachments.sessions
                assert sessions.delete_session("websocket:" + CHAT)
                sessions.save(sessions.get_or_create("websocket:" + CHAT))
            release.set()
            with pytest.raises(web.HTTPConflict):
                await asyncio.wait_for(stream.wait(), 20)
            after = run_for(native, CHAT)
            assert after["status"] == "FAILED" and after["tool_results"] == before["tool_results"]
    asyncio.run(check())
    assert len(read(native, "query")) == 1 and not agent.proofs and not agent.recorder.deadlines
    receipt = entry.receipt("BOSS", {"client_request_id": bound["client_request_id"]})
    assert receipt["entry"]["current_use_verified"] is False
    assert receipt["entry"]["preparation_sha256"] == bound["preparation_sha256"]
    reopened = ProductConversation(ControlStore(native[0].path), agent.registry, agent.recorder.runtime_snapshot, agent.attachments)
    requests = reopened.requests("BOSS", CHAT, attached=lambda chat: chat == CHAT, active=lambda: True)
    assert requests[0]["request_state"] == "FAILED" and not reopened.proofs


def test_actual_business_stream_cancel_preserves_binding_and_can_continue(native):
    entry, bound = bind_business(native)
    enable_business(native)
    agent = native[1]
    original = agent.provider.event_producer
    async def check():
        waiting = asyncio.Event()
        async def delayed(messages, tools):
            if any(row["role"] == "tool" for row in messages):
                waiting.set()
                await asyncio.Event().wait()
            return await original(messages, tools)
        agent.provider.event_producer = delayed
        async with session(native) as (bot, _):
            stream = await bot.run_streamed("查询毛利", **arguments(CHAT))
            await asyncio.wait_for(waiting.wait(), 20)
            before = run_for(native, CHAT)
            await stream.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stream.wait()
            assert run_for(native, CHAT)["status"] == "CANCELED"
            assert run_for(native, CHAT)["tool_results"] == before["tool_results"]
            agent.provider.event_producer = original
            result = await bot.run("查询收入", **arguments(CHAT))
            assert not result.error and "查询编号" in result.content
    asyncio.run(check())
    assert entry.read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})["entry"] == bound
    assert len(read(native, "query")) == 1 and not agent.proofs


@pytest.mark.parametrize("stage", ["BEFORE", "AFTER"])
def test_business_tool_rechecks_actual_source_before_and_after_delegate(native, stage):
    bind_business(native)
    enable_business(native)
    delegate = next(tool for tool in native[1].delegates if tool.name == "businessOverviewRead")
    original = delegate.execute
    finished = []
    async def controlled(**params):
        if stage == "BEFORE":
            native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
        result = await original(**params)
        finished.append(checksum(result))
        if stage == "AFTER":
            native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
        return result
    delegate.execute = controlled
    async def check():
        async with session(native) as (bot, _):
            with pytest.raises(RuntimeError):
                await bot.run("查看当前范围", **arguments(CHAT))
    asyncio.run(check())
    assert len(finished) == (1 if stage == "AFTER" else 0)
    run = run_for(native, CHAT)
    assert run["status"] == "FAILED" and run["tool_results"] == []
    assert run["tool_errors"][0]["error_type"] == "HTTPConflict"


@pytest.mark.parametrize("role,attached,active", [(None, True, True), ("MAINTAINER", True, True), ("BOSS", False, True), ("BOSS", True, False)])
def test_business_admission_requires_actual_owner_attach_and_active(native, role, attached, active):
    bind_business(native)
    with pytest.raises(web.HTTPException):
        native[1].admit_business(role, CHAT, str(uuid4()), "查看范围", media_sha256=checksum([]),
            attached=lambda chat: attached, active=lambda: active)
    assert not read(native, "conversation_intent") and not read(native, "runtime_run")


def test_business_runtime_schema_rejects_private_fields_and_authority(native):
    bind_business(native)
    enable_business(native)
    async def check():
        async with session(native) as (bot, _):
            await bot.run("查看范围", **arguments(CHAT))
    asyncio.run(check())
    run = run_for(native, CHAT)
    validator = current_validator()
    validator.validate(run)
    for field in ("question", "path", "body", "confirmed", "authorization_id", "role"):
        candidate = deepcopy(run)
        candidate["conversation_context"]["business_entry"][field] = True
        assert list(validator.iter_errors(candidate))


@pytest.mark.parametrize("change", ["REVISION", "EXPIRED"])
def test_actual_imported_source_change_rejects_next_native_admission(native, change):
    store = native[0]
    service = SupplyQualityAPI(store)
    manifest = yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())["initial_request"]
    assert service.execute("MAINTAINER", IMPORT_ACTION, manifest)["state"] == "SUCCESS"
    entry, bound = bind_business(native, {"page_id": "F14", "use": None}, region_id=None)
    enable_business(native)
    async def check():
        async with session(native) as (bot, _):
            assert not (await bot.run("查看当前专题", **arguments(CHAT))).error
            original = read(native, "runtime_run")[0]
            if change == "REVISION":
                assert service.execute("MAINTAINER", IMPORT_ACTION, {**manifest, "client_request_id": "n03-native-source-revision",
                    "records": [{**record, "expected_version": "1"} for record in manifest["records"]]})["state"] == "SUCCESS"
            else:
                reference = next(row for row in bound["source_references"] if row["id"] != "finance-note")
                with store.connect() as db:
                    document = store.get(db, "ui-check", "document", reference["id"])
                store.control("ui-check", "clock", {"at": document["valid_until"]})
            with pytest.raises(web.HTTPConflict):
                await bot.run("查看当前专题", **arguments(CHAT))
            assert read(native, "runtime_run") == [original]
    asyncio.run(check())
    receipt = entry.receipt("BOSS", {"client_request_id": bound["client_request_id"]})
    assert receipt["entry"]["source_references"] == bound["source_references"]
    assert not receipt["entry"]["current_use_verified"]


def test_actual_business_model_sees_only_scoped_tools_and_rejects_unplanned_parameters(native):
    bind_business(native)
    enable_business(native)
    agent = native[1]
    original = agent.provider.event_producer
    observed = []
    async def inspected(messages, tools):
        names = {tool["function"]["name"] for tool in tools}
        assert names == {"businessOverviewRead", "query_metrics", "bossEvidenceRead"}
        tool = agent.registry.get("businessOverviewRead")
        with pytest.raises(web.HTTPForbidden):
            await tool.execute(projection="topic")
        with pytest.raises(web.HTTPBadRequest):
            await tool.execute(projection="overview", owner_id="unapproved")
        observed.append(names)
        return await original(messages, tools)
    agent.provider.event_producer = inspected
    async def check():
        async with session(native) as (bot, _):
            assert not (await bot.run("查看当前范围", **arguments(CHAT))).error
    asyncio.run(check())
    assert observed and not read(native, "authorization") and not read(native, "task")


def test_business_namespace_change_stops_original_admission(native):
    bind_business(native)
    native[0].initialize("n03-other-namespace")
    with pytest.raises(web.HTTPException):
        native[1].admit_business("BOSS", CHAT, str(uuid4()), "查看范围", media_sha256=checksum([]),
            attached=lambda chat: chat == CHAT, active=lambda: True)
    assert not read(native, "runtime_run") and not read(native, "query")


def test_actual_new_applied_selection_stops_inflight_original_turn(native):
    entry, bound = bind_business(native)
    enable_business(native)
    selected = [(bound["preparation_id"], bound["preparation_sha256"])]
    agent = native[1]
    original = agent.provider.event_producer
    async def check():
        waiting, release = asyncio.Event(), asyncio.Event()
        async def delayed(messages, tools):
            if any(row["role"] == "tool" for row in messages):
                waiting.set()
                await release.wait()
            return await original(messages, tools)
        agent.provider.event_producer = delayed
        async with session(native, selection_current=lambda: selected[0]) as (bot, _):
            stream = await bot.run_streamed("查询毛利", **arguments(CHAT))
            await asyncio.wait_for(waiting.wait(), 20)
            scope = {**bound["applied_scope"], "attention": "SOURCE_REVIEW"}
            view = BusinessOverviewAPI(native[0]).read("BOSS", scope)
            prepared = entry.prepare("BOSS", {"client_request_id": "n03-new-explicit-scope", "applied_scope": scope,
                "snapshot_sha256": view["snapshot_sha256"], "topic_reference": None})
            selected[0] = (prepared["preparation_id"], prepared["preparation_sha256"])
            release.set()
            with pytest.raises(web.HTTPForbidden):
                await asyncio.wait_for(stream.wait(), 20)
    asyncio.run(check())
    assert run_for(native, CHAT)["status"] == "FAILED" and not read(native, "query")
    assert entry.read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})["entry"] == bound


def test_applied_scope_supplements_narrow_actual_region_and_keep_original_request_on_duplicate(native):
    _, bound = bind_business(native)
    enable_business(native)
    handoff = BusinessOverviewAPI(native[0]).read("BOSS", bound["applied_scope"])["query_handoff"]
    selected = handoff["region_ids"][0]
    text = "查询收入，只看" + selected
    async def check():
        async with session(native) as (bot, _):
            return await bot.run(text, **arguments(CHAT))
    assert not asyncio.run(check()).error
    query = read(native, "query")[0]
    assert query["context_snapshot"]["region_ids"] == [selected]
    original = read(native, "conversation_intent")[0]
    again = native[1].admit_business("BOSS", CHAT, original["turn_id"], text, media_sha256=checksum([]),
        attached=lambda chat: chat == CHAT, active=lambda: True,
        selection_current=lambda: (bound["preparation_id"], bound["preparation_sha256"]))
    assert not again["enqueue"] and again["run_id"] == original["run_id"]
    assert len(read(native, "query")) == 1 and read(native, "conversation_intent") == [original]
    assert not native[1].proofs
