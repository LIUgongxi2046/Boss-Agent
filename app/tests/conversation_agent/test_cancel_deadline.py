import asyncio
from contextlib import asynccontextmanager
import time

import pytest
from nanobot import Nanobot
from nanobot.agent.tools.context import current_request_context

from business import checksum
from boss_conversation import ConversationAPI
from controls import ControlStore
from conversation_agent.native import NativeConversationAgent
from test_native import complete_query_text, native, read


@asynccontextmanager
async def session(native):
    _, agent, loop, config, _ = native
    admitted = {}
    async with Nanobot(loop, config=config) as bot:
        async def transport(request):
            request.metadata["webui_turn_id"] = request.turn_id
            value = agent.admit("BOSS", request.chat_id, request.turn_id, request.original_user_text,
                media_sha256=checksum([]), attached=lambda chat: chat == request.chat_id, active=lambda: True)
            assert value is not None and value["enqueue"]
            admitted[request.chat_id] = value
        remove = [bot.runtime.add_context_provider(provider) for provider in
            (transport, agent.native_context, agent.scope_context, agent.recorder.context)]
        try:
            yield bot, admitted
        finally:
            for unsubscribe in reversed(remove):
                unsubscribe()


def arguments(chat_id):
    return {"channel": "websocket", "chat_id": chat_id, "session_key": "websocket:" + chat_id, "sender_id": "boss-1"}


def run_for(native, chat_id):
    return next(row for row in read(native, "runtime_run") if row["chat_id"] == chat_id)


def assert_original_result_after_reopen(native, chat_id, status):
    store, agent = native[:2]
    row = run_for(native, chat_id)
    assert row["status"] == status and row["finished_at"] is not None
    assert len(row["tool_results"]) == 1 and row["tool_results"][0]["tool_id"] == "query_metrics"
    query_id = row["tool_results"][0]["query_id"]
    reopened_store = ControlStore(store.path)
    reopened = NativeConversationAgent(reopened_store, agent.registry, agent.recorder.runtime_snapshot, agent.attachments)
    actual = ConversationAPI(reopened_store).artifact("BOSS", {"session_id": "websocket:" + chat_id,
        "chat_id": chat_id, "run_id": row["run_id"], "kind": "query", "id": query_id})
    assert actual["data"]["query_id"] == query_id
    receipts = reopened.requests("BOSS", chat_id, attached=lambda chat: chat == chat_id, active=lambda: True)
    assert len(receipts) == 1 and receipts[0]["run_id"] == row["run_id"] and receipts[0]["request_state"] == status
    assert not reopened.proofs and not reopened.pending_media
    assert not read(native, "authorization") and not read(native, "task") and len(read(native, "query")) == 1
    return row


def test_sdk_cancel_targets_one_actual_turn_after_tool_without_affecting_other_chat(native, record_property):
    agent = native[1]
    original = agent.provider.event_producer
    async def check():
        waiting = {name: asyncio.Event() for name in ("n02-sdk-cancel", "n02-sdk-other")}
        release = {name: asyncio.Event() for name in waiting}
        async def delayed(messages, tools):
            chat_id = current_request_context().chat_id
            if any(item["role"] == "tool" for item in messages):
                waiting[chat_id].set()
                await release[chat_id].wait()
            return await original(messages, tools)
        agent.provider.event_producer = delayed
        async with session(native) as (bot, admitted):
            target = await bot.run_streamed(complete_query_text(native) + "，读取 meeting-minutes", **arguments("n02-sdk-cancel"))
            other = await bot.run_streamed("读取 meeting-minutes", **arguments("n02-sdk-other"))
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in waiting.values())), 20)
            before = run_for(native, "n02-sdk-cancel")
            other_before = run_for(native, "n02-sdk-other")
            assert before["status"] == other_before["status"] == "RUNNING"
            assert len(before["tool_results"]) == len(other_before["tool_results"]) == 1
            started = time.monotonic()
            await target.cancel()
            record_property("sdk_cancel_elapsed_seconds", round(time.monotonic() - started, 3))
            with pytest.raises(asyncio.CancelledError):
                await target.wait()
            assert target.done and not other.done
            stopped = run_for(native, "n02-sdk-cancel")
            assert stopped["status"] == "CANCELED" and stopped["stop_reason"] == "cancelled"
            assert stopped["tool_results"] == before["tool_results"]
            assert run_for(native, "n02-sdk-other")["tool_results"] == other_before["tool_results"]
            assert run_for(native, "n02-sdk-other")["status"] == "RUNNING"
            assert set(agent.proofs) == {admitted["n02-sdk-other"]["client_request_id"]}
            assert set(agent.recorder.deadlines) == {other_before["run_id"]}
            release["n02-sdk-other"].set()
            result = await asyncio.wait_for(other.wait(), 20)
            assert not result.error and "来源：meeting-minutes" in result.content
            assert run_for(native, "n02-sdk-other")["status"] == "SUCCEEDED"
            assert len(read(native, "runtime_run")) == len(read(native, "conversation_intent")) == 2
            assert not agent.proofs and not agent.recorder.deadlines
    asyncio.run(check())
    assert_original_result_after_reopen(native, "n02-sdk-cancel", "CANCELED")


def test_actual_configured_deadline_stops_waiting_after_saved_query(native, record_property):
    store, agent = native[:2]
    with store.connect() as db:
        configured = store.get(db, "ui-check", "configuration", "current")["timeout"]
    assert configured == agent.recorder.runtime_snapshot()["timeout"] == 120
    original = agent.provider.event_producer
    async def check():
        waiting = asyncio.Event()
        async def delayed(messages, tools):
            chat_id = current_request_context().chat_id
            start = max(index for index, item in enumerate(messages) if item["role"] == "user")
            outputs = [item for item in messages[start + 1:] if item["role"] == "tool"]
            if chat_id == "n02-sdk-deadline" and len(outputs) == 1:
                waiting.set()
                await asyncio.sleep(configured + 0.5)
            return await original(messages, tools)
        agent.provider.event_producer = delayed
        async with session(native) as (bot, admitted):
            started = time.monotonic()
            target = await bot.run_streamed(complete_query_text(native) + "，读取 meeting-minutes", **arguments("n02-sdk-deadline"))
            await asyncio.wait_for(waiting.wait(), 20)
            before = run_for(native, "n02-sdk-deadline")
            assert before["status"] == "RUNNING" and len(before["tool_results"]) == 1
            other = await bot.run("读取 meeting-minutes", **arguments("n02-deadline-other"))
            assert not other.error and run_for(native, "n02-deadline-other")["status"] == "SUCCEEDED"
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(target.wait(), configured + 15)
            elapsed = time.monotonic() - started
            record_property("configured_timeout_seconds", configured)
            record_property("actual_deadline_elapsed_seconds", round(elapsed, 3))
            assert configured - 0.1 <= elapsed < configured + 10
            row = run_for(native, "n02-sdk-deadline")
            assert row["runtime"]["timeout"] == configured and row["status"] == "TIMED_OUT"
            assert row["stop_reason"] == "error" and row["tool_results"] == before["tool_results"]
            assert all(event["state"] != "REQUESTED" for event in row["simulated_model_events"])
            assert not agent.proofs and not agent.recorder.deadlines and len(admitted) == len(read(native, "runtime_run")) == 2
    asyncio.run(check())
    assert_original_result_after_reopen(native, "n02-sdk-deadline", "TIMED_OUT")
