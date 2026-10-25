import asyncio
from contextlib import asynccontextmanager
import json
import os

import pytest
from aiohttp import web
from nanobot import (Nanobot, STREAM_EVENT_RUN_STARTED, STREAM_EVENT_RUN_COMPLETED, STREAM_EVENT_RUN_FAILED,
    STREAM_EVENT_TOOL_STARTED, STREAM_EVENT_TOOL_COMPLETED, STREAM_EVENT_TOOL_FAILED,
    STREAM_EVENT_TEXT_DELTA, STREAM_EVENT_TEXT_COMPLETED)

from business import checksum
from boss_conversation import ConversationAPI
from controls import ControlStore
from conversation_agent.native import NativeConversationAgent
from product_runtime import RuntimeValues
from test_cancel_deadline import arguments, run_for
from test_native import complete_query_text, native, read


PAYLOAD_FIELDS = {"reasoning_content"}
EVENT_TYPES = {STREAM_EVENT_RUN_STARTED, STREAM_EVENT_RUN_COMPLETED, STREAM_EVENT_RUN_FAILED, STREAM_EVENT_TOOL_STARTED,
    STREAM_EVENT_TOOL_COMPLETED, STREAM_EVENT_TOOL_FAILED, STREAM_EVENT_TEXT_DELTA, STREAM_EVENT_TEXT_COMPLETED}


def observable(value):
    if isinstance(value, dict):
        has_payload = any(bool(value.get(field)) for field in PAYLOAD_FIELDS)
        assert has_payload is False
        for field, item in value.items():
            if field not in PAYLOAD_FIELDS:
                observable(item)
    elif isinstance(value, list):
        for item in value:
            observable(item)


@asynccontextmanager
async def session(native):
    _, agent, loop, config, _ = native
    admitted = []
    async with Nanobot(loop, config=config) as bot:
        async def transport(request):
            request.metadata["webui_turn_id"] = request.turn_id
            result = agent.admit("BOSS", request.chat_id, request.turn_id, request.original_user_text,
                media_sha256=checksum([]), attached=lambda chat: chat == request.chat_id, active=lambda: True)
            assert result is not None and result["enqueue"]
            admitted.append(result)
        providers = [transport, agent.native_context, agent.guard_context(agent.scope_context), agent.guard_context(agent.recorder.context)]
        remove = [bot.runtime.add_context_provider(provider) for provider in providers]
        try:
            yield bot, admitted
        finally:
            for unsubscribe in reversed(remove):
                unsubscribe()


def current_artifact(native, chat_id, run):
    store, agent = native[:2]
    reopened = ControlStore(store.path)
    service = NativeConversationAgent(reopened, agent.registry, agent.recorder.runtime_snapshot, agent.attachments)
    receipts = service.requests("BOSS", chat_id, attached=lambda chat: chat == chat_id, active=lambda: True)
    original = [item for item in receipts if item["run_id"] == run["run_id"]]
    assert len(original) == 1 and original[0]["request_state"] == run["status"]
    result = ConversationAPI(reopened).artifact("BOSS", {"session_id": "websocket:" + chat_id, "chat_id": chat_id,
        "run_id": run["run_id"], "kind": "query", "id": run["tool_results"][0]["query_id"]})
    assert not service.proofs and not service.pending_media
    return result


def test_actual_sdk_stream_history_and_tools_contain_observable_fields(native, record_property):
    chat = "n02-observable-events"
    agent = native[1]
    original = agent.provider.event_producer
    responses = []
    async def observed(messages, tools):
        response = await original(messages, tools)
        has_payload = bool(response.reasoning_content)
        assert has_payload is False
        responses.append(has_payload)
        return response
    agent.provider.event_producer = observed
    types, progress_steps, text_seen = [], [], []
    async def progress(content, **metadata):
        has_payload = bool(metadata.get("reasoning") or metadata.get("reasoning_end"))
        assert has_payload is False
        observable(metadata)
        progress_steps.extend((item["phase"], item["name"]) for item in metadata.get("tool_events", []))
    async def text(delta):
        text_seen.append(bool(delta))
    async def check():
        async with session(native) as (bot, _):
            stream = await bot.run_streamed(complete_query_text(native), **arguments(chat))
            async for event in stream.stream_events():
                event_type = event.type
                assert event_type in EVENT_TYPES
                types.append(event_type)
            result = await stream.wait()
            assert not result.error
            result = await native[2].process_direct("读取 meeting-minutes", **arguments(chat), on_progress=progress, on_stream=text)
            assert result is not None
    asyncio.run(check())
    assert {STREAM_EVENT_TOOL_STARTED, STREAM_EVENT_TOOL_COMPLETED, STREAM_EVENT_TEXT_DELTA, STREAM_EVENT_RUN_COMPLETED} <= set(types)
    assert ("start", "bossEvidenceRead") in progress_steps and ("end", "bossEvidenceRead") in progress_steps
    assert any(text_seen)
    assert responses and not any(responses)
    snapshot = agent.attachments.sessions.read_session_snapshot("websocket:" + chat)
    for message in snapshot.messages:
        observable(message)
        if message["role"] == "tool":
            observable(json.loads(message["content"]))
    row = run_for(native, chat)
    observable(row["tool_results"])
    assert row["status"] == "SUCCEEDED" and len(row["tool_results"]) == 1
    current_artifact(native, chat, row)
    record_property("observed_event_types", ",".join(sorted(set(types))))


def test_actual_output_pipe_failure_preserves_saved_query_and_failed_state(native):
    chat = "n02-output-failure"
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    attempts = []
    async def closed_output(delta):
        row = run_for(native, chat)
        assert len(row["tool_results"]) == 1 and len(read(native, "query")) == 1
        attempts.append("text_delta")
        os.write(write_fd, delta.encode("utf-8"))
    async def check():
        async with session(native):
            with pytest.raises(BrokenPipeError):
                await native[2].process_direct(complete_query_text(native), **arguments(chat), on_stream=closed_output)
    try:
        asyncio.run(check())
    finally:
        os.close(write_fd)
    row = run_for(native, chat)
    assert attempts == ["text_delta"] and row["status"] == "FAILED" and row["stop_reason"] == "error"
    assert len(row["tool_results"]) == 1 and not row.get("tool_errors")
    assert len(read(native, "query")) == 1 and not read(native, "authorization")
    assert not native[1].proofs and not native[1].recorder.deadlines
    assert current_artifact(native, chat, row)["data"]["query_id"] == row["tool_results"][0]["query_id"]


def test_actual_formal_query_failure_preserves_earlier_result_and_no_new_query(native):
    chat = "n02-formal-tool-failure"
    with native[0].connect() as db:
        initial = native[0].get(db, "ui-check", "initial", "snapshot")
    start, end = initial["periods"]["CURRENT"]
    invalid = complete_query_text(native).replace(start + "至" + end, end + "至" + start)
    async def check():
        async with session(native) as (bot, _):
            result = await bot.run(complete_query_text(native), **arguments(chat))
            assert not result.error
            original = run_for(native, chat)
            with pytest.raises(RuntimeError):
                await bot.run(invalid, **arguments(chat))
            return original
    original = asyncio.run(check())
    row = read(native, "runtime_run")[-1]
    assert row["status"] == "FAILED" and row["stop_reason"] == "error" and not row["tool_results"]
    assert len(row["tool_errors"]) == 1 and row["tool_errors"][0]["tool_id"] == "query_metrics"
    assert row["tool_errors"][0]["error_type"] == "HTTPBadRequest"
    assert read(native, "runtime_run")[0] == original and len(read(native, "query")) == 1
    assert not native[1].proofs and not native[1].recorder.deadlines
    result = ConversationAPI(ControlStore(native[0].path)).artifact("BOSS", {"session_id": "websocket:" + chat, "chat_id": chat,
        "run_id": original["run_id"], "kind": "query", "id": original["tool_results"][0]["query_id"]})
    assert result["data"]["query_id"] == original["tool_results"][0]["query_id"]


def test_actual_insufficient_round_configuration_rejects_before_runtime_and_keeps_original(native):
    chat = "n02-round-admission"
    store, agent, loop = native[:3]
    async def check():
        async with session(native) as (bot, _):
            first = await bot.run(complete_query_text(native), **arguments(chat))
            assert not first.error
            original = run_for(native, chat)
            snapshot = agent.recorder.runtime_snapshot()
            values = RuntimeValues(max_tool_rounds=1, max_output_tokens=snapshot["max_output_tokens"],
                tool_scope=agent.registry.configured_tool_names)
            native[3].agents.defaults.max_tool_iterations = values.max_tool_rounds
            snapshot["max_tool_rounds"] = values.max_tool_rounds
            snapshot["config_sha256"] = checksum(native[3].model_dump(mode="json"))
            loop.max_iterations = values.max_tool_rounds
            with store.connect() as db:
                configuration = store.get(db, "ui-check", "configuration", "current")
                store.put(db, "ui-check", "configuration_revision", configuration["version"], dict(configuration))
                configuration.update(max_tool_rounds=values.max_tool_rounds, version=str(int(configuration["version"]) + 1))
                store.put(db, "ui-check", "configuration", "current", configuration)
            with pytest.raises(web.HTTPConflict):
                await bot.run("查看当前任务", **arguments(chat))
            return original
    original = asyncio.run(check())
    assert read(native, "runtime_run") == [original] and len(read(native, "query")) == 1
    rejected = read(native, "conversation_intent")[-1]
    assert rejected["status"] == "FAILED" and rejected["run_id"] is None
    assert not agent.proofs and not agent.recorder.deadlines
    current_artifact(native, chat, original)
