import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from loguru import logger
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

import boss_memory
from business import checksum
from boss_admin_config import memory_technical_status
from boss_command_api import BossCommandAPI
from boss_memory_runtime import OwnerMemoryContext
from boss_runtime_records import RuntimeRecorder, runtime_records
from connection import RecordedProvider, settings
from controls import ControlStore

pytestmark = pytest.mark.skipif(os.environ.get("BOSS_RUN_LIVE") != "1", reason="需要显式启用获准样本记忆的真实采用检查")


def test_live_revoked_memory_confirmation_and_new_explicit_confirmation(tmp_path):
    connection = settings()
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    store = ControlStore(tmp_path / "memory-confirmation.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
    assert checksum(snapshot) == "75e5c19645f0e7cd1f5036a0a441de0a1a59c8eb1b9d1be5137ef0414eb2f345"
    original = snapshot["memory"]["text"]
    api = BossCommandAPI(store)
    stages = []

    def confirm(version):
        status, result = api.execute("BOSS", "boss.memory.confirm", {
            "client_request_id": str(uuid4()), "expected_version": version, "text": original,
        })
        assert status == 200
        return result

    async def read(stage, expected):
        reopened = ControlStore(store.path)
        config_data = {"agents": {"defaults": {"provider": "deepseek", "model": connection["model_id"],
            "workspace": str(tmp_path / "workspace"), "maxToolIterations": 12, "maxTokens": 512,
            "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}, "gateway": {"heartbeat": {"enabled": False}}}
        config = Config.model_validate(config_data)
        registry = ToolRegistry()
        recorder = RuntimeRecorder(reopened, "ui-check", registry, lambda: {
            "provider": "deepseek", "model_id": connection["model_id"], "api_type": "chat_completions",
            "max_tool_rounds": 12, "max_output_tokens": 512, "timeout": 120, "config_sha256": checksum(config_data),
        })
        provider = RecordedProvider(connection, tmp_path / (stage + "-transport.json"),
                                    redact_payload=True, transport_observer=recorder.observe_transport)
        provider.generation = config.resolve_preset().to_generation_settings()
        loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider, hook_factories=[recorder.hook_factory])
        for name in list(registry.tool_names):
            registry.unregister(name)
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(OwnerMemoryContext(reopened))
            bot.runtime.add_context_provider(recorder.context)
            async with asyncio.timeout(120):
                result = await bot.run("当前模拟资料的有效简报阅读要求是什么？仅依据当前提供的确认记录回答，缺少记录请明确说明。",
                                       session_key=stage, sender_id="boss-1")
        assert result.stop_reason == "completed" and not result.error
        if expected:
            assert "现金" in result.content and "本人承诺" in result.content
        else:
            assert "现金" not in result.content and "本人承诺" not in result.content
        technical = memory_technical_status(reopened, "MAINTAINER")
        assert technical["future_context_eligible"] is expected
        record = next(item for item in runtime_records(reopened, "MAINTAINER")["runs"] if item["session_id"] == stage)
        assert record["memory_reference"]["eligible"] is expected and record["status"] == "SUCCEEDED"
        assert len(record["model_requests"]) == 1
        assert original not in json.dumps(record, ensure_ascii=False)
        stages.append({"stage": stage, "eligible": expected, "runtime_record": record,
                       "approved_memory_adoption_verified": True, "answer_sha256": hashlib.sha256(result.content.encode()).hexdigest()})

    async def check():
        current = confirm("1")
        await read("before-confirmation-revocation", True)
        status, _ = api.execute("BOSS", "boss.authorization.revoke", {
            "client_request_id": str(uuid4()), "authorization_id": current["authorization_id"],
            "expected_version": "1", "reason": "本人撤销本次记忆确认",
        })
        assert status == 200
        await read("after-confirmation-revocation", False)
        newer = confirm(current["version"])
        assert newer["authorization_id"] != current["authorization_id"]
        await read("after-new-owner-confirmation", True)
        with store.connect() as db:
            assert store.get(db, "ui-check", "memory", "current")["text"] == original
            assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','outbox','message_outbox')").fetchone()[0] == 0
        files = ("validation/boss_memory_runtime.py", "validation/boss_runtime_records.py", "validation/boss_admin_config.py",
                 "validation/connection.py", "app/tests/test_boss_live_memory_confirmation.py")
        (tmp_path / "memory-confirmation-adoption.json").write_text(json.dumps({
            "status": "PASS", "source_type": "SIMULATED", "stages": stages,
            "new_runtime_and_session_per_stage": True, "business_task_created": False,
            "original_memory_body_preserved": True, "private_body_recorded": False,
            "w1_confirmed_memory_sha256": hashlib.sha256(Path(boss_memory.__file__).read_bytes()).hexdigest(),
            "source_code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
            "full_A15_accepted": False, "full_A19_accepted": False,
        }, ensure_ascii=False, indent=2))
    asyncio.run(check())
