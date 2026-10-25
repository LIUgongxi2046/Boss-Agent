import asyncio

import pytest
import yaml
from aiohttp import web

from conftest import DOMAIN
from business import checksum
from boss_command_api import BossCommandAPI
from boss_conversation import ConversationAPI
from boss_supply_quality import SupplyQualityAPI, IMPORT_ACTION, COORDINATE_ACTION
from controls import ControlStore
from conversation_agent.native import NativeConversationAgent
from test_cancel_deadline import arguments, run_for
from test_native import complete_query_text, native, read
from test_observable_failure import session


CHAT = "n02-bound-task-consumer"
CONTEXT = {"session_id": "websocket:" + CHAT, "chat_id": CHAT}


def create_task(native, key):
    store = native[0]
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
    status, task = BossCommandAPI(store).execute("BOSS", "boss.assignment.create", {
        "client_request_id": key, "purpose": document["content"], "coordinator_id": "coordinator-1",
        "due_at": "2026-10-24T17:00:00+08:00", "timezone": "Asia/Shanghai",
        "evidence_requirements": [document["source_id"]], "related_meeting_id": "meeting-1",
        "related_event_ids": ["event-1"], "source_refs": [document["source_id"]], "content_version": "1"})
    assert status == 200, task
    return task


def bind_task(native, task, *, chat=CHAT, key="n02-consumer-task-entry"):
    sessions = native[1].attachments.sessions
    sessions.save(sessions.get_or_create("websocket:" + chat))
    entry = ConversationAPI(native[0]).task_entry(sessions)
    prepared = entry.prepare("BOSS", {"client_request_id": key, "task_id": task["task_id"], "task_version": task["version"]})
    bound = entry.bind("BOSS", {**{field: prepared[field] for field in
        ("client_request_id", "preparation_id", "preparation_sha256")}, "chat_id": chat})
    return entry, bound


def pinned(bound):
    return {field: bound[field] for field in ("preparation_id", "client_request_id", "preparation_sha256",
        "task_reference", "source_references", "return_reference")}


def test_bound_current_task_consumes_exact_formal_selection_and_original_hash(native):
    selected = create_task(native, "n02-consumer-selected-task")
    other = create_task(native, "n02-consumer-other-task")
    entry, bound = bind_task(native, selected)
    original_tasks, original_authorizations = read(native, "task"), read(native, "authorization")
    async def check():
        async with session(native) as (bot, _):
            return [await bot.run(text, **arguments(CHAT)) for text in ("查看当前任务", "查看这个事项")]
    results = asyncio.run(check())
    assert all(not result.error and selected["task_id"] in result.content for result in results)
    assert all(other["task_id"] not in result.content for result in results)
    for run in read(native, "runtime_run"):
        context = run["conversation_context"]
        assert context["task_entry"] == pinned(bound)
        assert context["references"] == entry.read("BOSS", CONTEXT)["references"]
        assert len(run["tool_results"]) == 1
        step = run["tool_results"][0]
        assert step["tool_id"] == "conversationRead" and step["task_id"] == selected["task_id"]
        assert step["task_version"] == selected["version"]
        assert step["parameters_sha256"] == checksum({"projection": "record", "kind": "task", "id": selected["task_id"]})
    assert all(row["task_entry"] == pinned(bound) for row in read(native, "conversation_intent"))
    assert read(native, "task") == original_tasks and read(native, "authorization") == original_authorizations
    assert entry.read("BOSS", CONTEXT)["entry"] == bound


def send_task(native, task):
    with native[0].connect() as db:
        document = native[0].get(db, "ui-check", "document", "finance-note")
    status, result = BossCommandAPI(native[0]).execute("BOSS", "boss.assignment.send", {
        "client_request_id": "n02-consumer-owner-version", "task_id": task["task_id"],
        "task_version": task["version"], "recipient_id": "coordinator-1", "body": document["content"], "content_version": "1"})
    assert status == 200, result
    assert result["task_version"] != task["version"]


def change_binding_input(native, task, change):
    if change == "TASK_VERSION":
        send_task(native, task)
    elif change == "SOURCE_WITHDRAWN":
        native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    else:
        sessions = native[1].attachments.sessions
        assert sessions.delete_session(CONTEXT["session_id"])
        if change == "SESSION_RECREATED":
            sessions.save(sessions.get_or_create(CONTEXT["session_id"]))


@pytest.mark.parametrize("change,error", [("TASK_VERSION", web.HTTPConflict), ("SOURCE_WITHDRAWN", web.HTTPGone),
    ("SESSION_REMOVED", web.HTTPNotFound), ("SESSION_RECREATED", web.HTTPConflict)])
def test_next_actual_turn_rechecks_original_preparation_without_rebinding(native, change, error):
    task = create_task(native, "n02-consumer-change-task")
    entry, bound = bind_task(native, task)
    async def check():
        async with session(native) as (bot, _):
            assert not (await bot.run("查看当前任务", **arguments(CHAT))).error
            original = read(native, "runtime_run")[0]
            original_intent = read(native, "conversation_intent")[0]
            change_binding_input(native, task, change)
            with pytest.raises(error):
                await bot.run("查看当前任务", **arguments(CHAT))
            assert read(native, "runtime_run") == [original]
            assert read(native, "conversation_intent")[0] == original_intent
    asyncio.run(check())
    assert read(native, "conversation_intent")[-1]["status"] == "FAILED"
    assert read(native, "conversation_intent")[-1]["run_id"] is None
    receipt = entry.receipt("BOSS", {"client_request_id": bound["client_request_id"]})
    assert receipt["entry"]["current_use_verified"] is False and pinned(receipt["entry"]) == pinned(bound)
    assert len(read(native, "conversation_task_binding")) == len(read(native, "conversation_task_preparation")) == 1
    assert not native[1].proofs and not native[1].recorder.deadlines


def test_bound_request_for_another_actual_task_stops_without_listing_or_replacing(native):
    selected = create_task(native, "n02-consumer-fixed-selection")
    other = create_task(native, "n02-consumer-other-selection")
    entry, bound = bind_task(native, selected)
    async def check():
        async with session(native) as (bot, _):
            with pytest.raises(web.HTTPConflict):
                await bot.run("查看任务 " + other["task_id"], **arguments(CHAT))
    asyncio.run(check())
    assert not read(native, "runtime_run")
    assert read(native, "conversation_intent")[-1]["status"] == "FAILED"
    assert entry.read("BOSS", CONTEXT)["entry"] == bound


@pytest.mark.parametrize("change", ["TASK_VERSION", "SOURCE_WITHDRAWN", "SESSION_RECREATED"])
def test_model_step_rechecks_binding_after_saved_actual_query(native, change):
    task = create_task(native, "n02-consumer-model-task")
    entry, bound = bind_task(native, task)
    original = native[1].provider.event_producer
    async def check():
        waiting, release = asyncio.Event(), asyncio.Event()
        async def delayed(messages, tools):
            if any(item["role"] == "tool" for item in messages):
                waiting.set()
                await release.wait()
            return await original(messages, tools)
        native[1].provider.event_producer = delayed
        async with session(native) as (bot, _):
            stream = await bot.run_streamed(complete_query_text(native) + "，查看当前任务", **arguments(CHAT))
            await asyncio.wait_for(waiting.wait(), 20)
            before = run_for(native, CHAT)
            assert len(before["tool_results"]) == 1 and before["tool_results"][0]["tool_id"] == "query_metrics"
            change_binding_input(native, task, change)
            release.set()
            with pytest.raises(web.HTTPGone if change == "SOURCE_WITHDRAWN" else web.HTTPConflict):
                await asyncio.wait_for(stream.wait(), 20)
            after = run_for(native, CHAT)
            assert after["status"] == "FAILED" and after["tool_results"] == before["tool_results"]
    asyncio.run(check())
    run = run_for(native, CHAT)
    assert len(read(native, "query")) == 1 and run["conversation_context"]["task_entry"] == pinned(bound)
    assert pinned(entry.receipt("BOSS", {"client_request_id": bound["client_request_id"]})["entry"]) == pinned(bound)
    assert not native[1].proofs and not native[1].recorder.deadlines


@pytest.mark.parametrize("change", ["EXPIRED", "SOURCE_REVISION"])
def test_actual_imported_source_rechecks_hash_and_expiry_in_bound_consumer(native, change):
    store = native[0]
    service = SupplyQualityAPI(store)
    manifest = yaml.safe_load((DOMAIN / "data/simulation/supply-quality-v1.yaml").read_text())["initial_request"]
    assert service.execute("MAINTAINER", IMPORT_ACTION, manifest)["state"] == "SUCCESS"
    view = service.read("BOSS", "SI10")
    task = service.execute("BOSS", COORDINATE_ACTION, {"client_request_id": "n02-consumer-source-task", "interface_id": "SI10",
        "origin_entity_type": "production_event", "origin_record_id": "sim-production-event-1", "origin_version": "1",
        "review_sha256": view["review_sha256"], "purpose": "核查当前SIMULATED批次资料", "coordinator_id": "coordinator-1",
        "due_at": "2026-10-24T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["当前明确的模拟来源"]})
    entry, bound = bind_task(native, task)
    async def check():
        async with session(native) as (bot, _):
            assert not (await bot.run("查看当前任务", **arguments(CHAT))).error
            original = read(native, "runtime_run")[0]
            if change == "EXPIRED":
                with store.connect() as db:
                    document = store.get(db, "ui-check", "document", bound["source_references"][0]["id"])
                store.control("ui-check", "clock", {"at": document["valid_until"]})
            else:
                link = task["coordination_link"]
                record = next(row for row in manifest["records"] if row["entity_type"] == link["origin_entity_type"]
                    and row["data"]["event_id"] == link["origin_record_id"])
                assert service.execute("MAINTAINER", IMPORT_ACTION, {**manifest, "client_request_id": "n02-consumer-source-revision",
                    "records": [{**record, "expected_version": link["origin_version"]}]})["state"] == "SUCCESS"
            with pytest.raises(web.HTTPGone if change == "EXPIRED" else web.HTTPConflict):
                await bot.run("查看当前任务", **arguments(CHAT))
            assert read(native, "runtime_run") == [original]
    asyncio.run(check())
    assert pinned(entry.receipt("BOSS", {"client_request_id": bound["client_request_id"]})["entry"]) == pinned(bound)
    assert len(read(native, "conversation_task_binding")) == 1


def test_actual_sdk_cancellation_preserves_binding_history_and_selected_result(native):
    task = create_task(native, "n02-consumer-cancel-task")
    entry, bound = bind_task(native, task)
    original = native[1].provider.event_producer
    async def check():
        waiting = asyncio.Event()
        async def delayed(messages, tools):
            if any(item["role"] == "tool" for item in messages):
                waiting.set()
                await asyncio.Event().wait()
            return await original(messages, tools)
        native[1].provider.event_producer = delayed
        async with session(native) as (bot, _):
            stream = await bot.run_streamed("查看当前任务", **arguments(CHAT))
            await asyncio.wait_for(waiting.wait(), 20)
            before = run_for(native, CHAT)
            await stream.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stream.wait()
            after = run_for(native, CHAT)
            assert after["status"] == "CANCELED" and after["tool_results"] == before["tool_results"]
    asyncio.run(check())
    assert entry.read("BOSS", CONTEXT)["entry"] == bound
    assert not native[1].proofs and not native[1].pending_media and not native[1].recorder.deadlines
    store = ControlStore(native[0].path)
    reopened = NativeConversationAgent(store, native[1].registry, native[1].recorder.runtime_snapshot, native[1].attachments)
    receipts = reopened.requests("BOSS", CHAT, attached=lambda chat: chat == CHAT, active=lambda: True)
    run = run_for(native, CHAT)
    assert receipts[0]["run_id"] == run["run_id"] and receipts[0]["request_state"] == "CANCELED"
    result = ConversationAPI(store).artifact("BOSS", {**CONTEXT, "run_id": run["run_id"], "kind": "task", "id": task["task_id"]})
    assert result["data"]["version"] == task["version"]
    snapshot = reopened.attachments.sessions.read_session_snapshot(CONTEXT["session_id"])
    assert any(message["role"] == "user" for message in snapshot.messages)
    assert not reopened.proofs


@pytest.mark.parametrize("stage", ["BEFORE_TOOL", "AFTER_TOOL"])
def test_formal_tool_checks_task_entry_before_and_after_actual_delegate(native, stage):
    task = create_task(native, "n02-consumer-tool-task")
    entry, bound = bind_task(native, task)
    delegate = native[1].registry.get("conversationRead").delegate
    actual = delegate.execute
    completed = []
    async def controlled(**params):
        if stage == "BEFORE_TOOL":
            native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
        output = await actual(**params)
        completed.append(checksum(output))
        if stage == "AFTER_TOOL":
            native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
        return output
    delegate.execute = controlled
    async def check():
        async with session(native) as (bot, _):
            with pytest.raises(RuntimeError):
                await bot.run("查看当前任务", **arguments(CHAT))
    asyncio.run(check())
    assert len(completed) == (1 if stage == "AFTER_TOOL" else 0)
    run = run_for(native, CHAT)
    assert run["status"] == "FAILED" and run["tool_results"] == []
    assert run["tool_errors"][0]["error_type"] == "HTTPGone"
    assert run["conversation_context"]["task_entry"] == pinned(bound)
    assert pinned(entry.receipt("BOSS", {"client_request_id": bound["client_request_id"]})["entry"]) == pinned(bound)
    assert not native[1].proofs and not native[1].recorder.deadlines


def test_bound_source_followup_keeps_task_and_source_versions_without_duplicate_references(native):
    task = create_task(native, "n02-consumer-followup-task")
    entry, bound = bind_task(native, task)
    async def check():
        async with session(native) as (bot, _):
            for text in ("读取 finance-note", "继续核查这份资料的版本", "读取 meeting-minutes", "查看当前任务"):
                assert not (await bot.run(text, **arguments(CHAT))).error
    asyncio.run(check())
    runs = read(native, "runtime_run")
    for run in runs:
        context = run["conversation_context"]
        assert context["task_entry"] == pinned(bound)
        refs = context["references"]
        assert len(refs) == len({(ref["kind"], ref["id"], ref["version"]) for ref in refs})
        assert all(ref in refs for ref in entry.read("BOSS", CONTEXT)["references"])
    assert runs[1]["tool_results"][0]["source_id"] == "finance-note"
    assert runs[2]["tool_results"][0]["source_id"] == "meeting-minutes"
    assert runs[3]["tool_results"][0]["task_id"] == task["task_id"]


def test_unbound_chat_does_not_consume_other_chat_or_unbound_preparation(native):
    selected = create_task(native, "n02-consumer-unbound-selected")
    entry, bound = bind_task(native, selected)
    entry.prepare("BOSS", {"client_request_id": "n02-consumer-prepared-only", "task_id": selected["task_id"], "task_version": selected["version"]})
    chat = "n02-consumer-unbound"
    async def check():
        async with session(native) as (bot, _):
            return await bot.run("查看当前任务", **arguments(chat))
    result = asyncio.run(check())
    assert not result.error
    run = run_for(native, chat)
    assert run["conversation_context"]["references"] == [] and "task_entry" not in run["conversation_context"]
    assert run["tool_results"][0]["tool_id"] == "bossTasksRead"
    assert read(native, "conversation_intent")[-1]["task_entry"] is None
    assert entry.read("BOSS", CONTEXT)["entry"] == bound
