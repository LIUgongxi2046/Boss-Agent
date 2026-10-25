import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from loguru import logger
from nanobot import Nanobot, RuntimeContextBlock
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from business import Store, checksum, encode
from boss_command_api import BossCommandAPI
from connection import RecordedProvider, settings
from controls import ControlStore
from boss_runtime_records import runtime_records
from fault_probe import CONTENT, QUERY, objects, runtime

pytestmark = pytest.mark.skipif(
    os.environ.get("BOSS_RUN_LIVE") != "1",
    reason="需要显式启用真实 DeepSeek 检查和本地凭据引用",
)


def prepare_output(tmp_path):
    settings()
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    output = tmp_path / "runtime"
    output.mkdir()
    return output


def test_live_written_state_survives_model_transport_failure(tmp_path):
    output = prepare_output(tmp_path)

    async def check():
        async with runtime("w2-written-client-closed", output, close_after_write=True, record_runtime=True) as case:
            authorization = case["store"].authorize(case["ns"], "create_assignment", CONTENT)
            binding = {"authorization_id": authorization, "idempotency_key": "w2-written-result"}
            case["bindings"]["create_assignment"] = binding
            result = await case["bot"].run(
                "本人授权创建以下交办：" + encode(CONTENT),
                session_key=case["ns"], sender_id="boss-1", hooks=[case["trace"]],
            )
            assert result.stop_reason == "error" and result.error
            tasks = objects(case, "task")
            assert len(tasks) == 1 and tasks[0]["status"] == "OPEN"
            assert objects(case, "outbox") == []
            reopened = Store(case["store"].path)
            replay = reopened.invoke("create_assignment", {
                **CONTENT, **binding, "envelope": case["envelope"],
            })
            with reopened.connect() as db:
                original = json.loads(db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation='create_assignment' AND key=?",
                                                (case["ns"], binding["idempotency_key"])).fetchone()[0])
            assert replay == original
            assert replay["task_id"] == tasks[0]["task_id"]
            assert reopened.invoke("read_assignment", {
                "envelope": case["envelope"], "task_id": replay["task_id"],
            }) == tasks[0]
            assert len(objects(case, "task")) == 1
            row = runtime_records(reopened, "MAINTAINER", case["ns"])["runs"][0]
            assert row["status"] == "FAILED" and row["stop_reason"] == "error"
            assert next(item for item in row["tool_results"] if item["tool_id"] == "create_assignment")["task_id"] == tasks[0]["task_id"]
            assert row["model_requests"] and row["cost_total"] is None

    asyncio.run(check())


def test_live_explicit_cancellation_stops_pending_runtime(tmp_path):
    output = prepare_output(tmp_path)

    async def check():
        async with runtime("w2-explicit-cancel", output, record_runtime=True) as case:
            run = await case["bot"].run_streamed(
                QUERY, session_key=case["ns"], sender_id="boss-1", hooks=[case["trace"]],
            )
            stream = run.stream_events()
            async for event in stream:
                if event.type == "text.delta":
                    break
            assert not run.done
            await run.cancel()
            await stream.aclose()
            assert run.done
            with pytest.raises(asyncio.CancelledError):
                await run.wait()
            assert objects(case, "task") == objects(case, "outbox") == []
            assert runtime_records(case["store"], "BOSS", case["ns"])["runs"][0]["status"] == "CANCELED"

    asyncio.run(check())


def test_live_timeout_after_real_request_has_started(tmp_path):
    output = prepare_output(tmp_path)

    async def check():
        async with runtime("w2-request-timeout", output, record_runtime=True) as case:
            started = asyncio.Event()
            observe = case["provider"].transport_observer

            def observe_request(event):
                binding = observe(event)
                if event["type"] == "request":
                    started.set()
                return binding

            case["provider"].transport_observer = observe_request
            pending = asyncio.create_task(case["bot"].run(
                QUERY, session_key=case["ns"], sender_id="boss-1", hooks=[case["trace"]],
            ))
            admission = asyncio.create_task(started.wait())
            # 从真实 HTTP request Hook 取得开始信号，界限继承 Provider 的120秒配置。
            async with asyncio.timeout(120):
                await asyncio.wait({pending, admission}, return_when=asyncio.FIRST_COMPLETED)
            if not started.is_set():
                admission.cancel()
                await pending
                raise AssertionError("Runtime结束前没有实际模型请求")
            await admission
            with pytest.raises(TimeoutError):
                deadline = asyncio.timeout(0.5)
                case["runtime_recorder"].deadline_expired = deadline.expired
                async with deadline:
                    await pending
            assert objects(case, "task") == objects(case, "outbox") == []
            row = runtime_records(case["store"], "BOSS", case["ns"])["runs"][0]
            assert row["status"] == "TIMED_OUT" and row["termination_source"] == "CALLER_DEADLINE_EXPIRED"

    asyncio.run(check())


def test_live_iteration_budget_stops_further_model_turns(tmp_path):
    output = prepare_output(tmp_path)

    async def check():
        async with runtime("w2-iteration-budget", output, rounds=1, record_runtime=True) as case:
            result = await case["bot"].run(
                QUERY, session_key=case["ns"], sender_id="boss-1", hooks=[case["trace"]],
            )
            assert result.stop_reason == "max_iterations"
            assert any(row["type"] == "request" for row in case["provider"].requests)
            assert objects(case, "task") == objects(case, "outbox") == []
            row = runtime_records(case["store"], "BOSS", case["ns"])["runs"][0]
            assert row["status"] == "FAILED" and row["stop_reason"] == "max_iterations"

    asyncio.run(check())


def test_live_approved_sample_memory_deletion_after_restart(tmp_path):
    connection = settings()
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    store = ControlStore(tmp_path / "approved-selection.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
    # 用户明确授权向 DeepSeek 发送这条既有模拟样本，校验来源后执行。
    assert snapshot["source_type"] == "SIMULATED"
    assert checksum(snapshot) == "75e5c19645f0e7cd1f5036a0a441de0a1a59c8eb1b9d1be5137ef0414eb2f345"
    approved_text = snapshot["memory"]["text"]

    async def read_sample_memory(current_store, session):
        config = Config.model_validate({
            "agents": {"defaults": {
                "provider": "deepseek", "model": connection["model_id"],
                "workspace": str(tmp_path / "workspace"),
                "maxToolIterations": 2, "maxTokens": 512,
                "dream": {"enabled": False}, "idleCompactAfterMinutes": 0,
            }},
            "gateway": {"heartbeat": {"enabled": False}},
        })
        registry = ToolRegistry()
        provider = RecordedProvider(connection, tmp_path / (session + ".json"), redact_payload=True)
        provider.generation = config.resolve_preset().to_generation_settings()
        loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider)
        for name in list(registry.tool_names):
            registry.unregister(name)
        async with Nanobot(loop, config=config) as bot:
            async def context(request):
                memory = current_store.context("ui-check")["memory"]
                if memory is not None:
                    assert memory["text"] == approved_text
                return RuntimeContextBlock(
                    source="approved-simulated-memory",
                    content=encode({"source_type": "SIMULATED", "memory": memory}),
                )
            bot.runtime.add_context_provider(context)
            async with asyncio.timeout(120):
                result = await bot.run(
                    "当前模拟资料的有效简报阅读要求是什么？仅依据当前确认记录回答，缺少记录请明确说明。",
                    session_key=session, sender_id="boss-1",
                )
            assert result.stop_reason == "completed" and not result.error
            return result

    async def check():
        before = await read_sample_memory(store, "before-sample-deletion")
        assert "现金" in before.content and "本人承诺" in before.content
        status, receipt = BossCommandAPI(store).execute("BOSS", "boss.memory.delete", {
            "client_request_id": "w2-live-sample-delete", "expected_version": "1",
        })
        assert status == 200 and receipt["confirmation_state"] == "DELETED"
        reopened = ControlStore(store.path)
        assert reopened.context("ui-check")["memory"] is None
        after = await read_sample_memory(reopened, "after-sample-deletion")
        assert "现金" not in after.content and "本人承诺" not in after.content
        (tmp_path / "sample-memory-adoption-result.json").write_text(json.dumps({
            "status": "PASS", "source_type": "SIMULATED",
            "approved_sample_observed_before": True,
            "deleted_sample_reintroduced_after_restart": False,
            "memory_version": receipt["version"], "private_body_recorded": False,
        }, ensure_ascii=False))

    asyncio.run(check())
