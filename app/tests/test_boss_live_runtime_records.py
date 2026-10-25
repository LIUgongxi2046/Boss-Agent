import asyncio
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from loguru import logger
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from business import checksum
from boss_command_api import BossCommandAPI
from boss_runtime_records import RuntimeRecorder, runtime_records
from connection import RecordedProvider, settings
from controls import ControlStore
from model_probe import BusinessTool
from safe_diagnostics import RedactedEventList
from service import application

pytestmark = pytest.mark.skipif(os.environ.get("BOSS_RUN_LIVE") != "1", reason="需要显式启用获准原文的真实版本采用检查")


def activate(api, body, previous=None):
    identifier = previous["prompt_id"] if previous else None
    version = previous["prompt_version"] if previous else "0"
    status, saved = api.execute("MAINTAINER", "boss.prompt.save", {
        "client_request_id": secrets.token_hex(16), "prompt_id": identifier, "expected_version": version,
        "kind": "TASK_HINTS", "title": "获准原文引用要求", "instruction_text": body,
        "change_note": "检查当前启用版本的真实请求关联", "source_ids": ["finance-note"],
    })
    assert status == 200, saved
    status, checked = api.execute("MAINTAINER", "boss.prompt.validate", {
        "client_request_id": secrets.token_hex(16), "prompt_id": saved["prompt_id"],
        "expected_version": saved["version"], "expected_content_sha256": saved["content_sha256"],
    })
    assert status == 200, checked
    status, active = api.execute("MAINTAINER", "boss.prompt.activate", {
        "client_request_id": secrets.token_hex(16), "prompt_id": saved["prompt_id"],
        "expected_version": checked["version"], "expected_content_sha256": saved["content_sha256"],
        "expected_active_version": previous["active_version"] if previous else "0",
    })
    assert status == 200, active
    return active


def test_live_next_turn_adopts_current_prompt_configuration_and_tool_schema(tmp_path):
    connection = settings()
    source_files = (
        "validation/boss_runtime_records.py", "validation/connection.py", "validation/model_probe.py",
        "validation/boss_prompt_config.py", "app/tests/test_boss_live_runtime_records.py",
    )
    input_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files}
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    store = ControlStore(tmp_path / "runtime.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        assert checksum(store.get(db, "ui-check", "initial", "snapshot")) == "75e5c19645f0e7cd1f5036a0a441de0a1a59c8eb1b9d1be5137ef0414eb2f345"
        original = store.get(db, "ui-check", "document", "finance-note")["content"]
    api = BossCommandAPI(store)
    first_prompt = activate(api, original)
    os.environ["BOSS_PROBE_TOKEN"] = secrets.token_urlsafe(32)
    os.environ["MAINTAINER_PROBE_TOKEN"] = secrets.token_urlsafe(32)
    evidence = []

    async def run(stage, prompt, rounds, operation):
        reopened = ControlStore(store.path)
        config_data = {
            "agents": {"defaults": {"provider": "deepseek", "model": connection["model_id"],
                "workspace": str(tmp_path / "workspace"), "maxToolIterations": rounds, "maxTokens": 700,
                "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
            "gateway": {"heartbeat": {"enabled": False}},
        }
        config = Config.model_validate(config_data)
        registry = ToolRegistry()
        snapshot = {"provider": "deepseek", "model_id": connection["model_id"], "api_type": "chat_completions",
                    "max_tool_rounds": rounds, "max_output_tokens": 700, "timeout": 120,
                    "config_sha256": checksum(config_data)}
        recorder = RuntimeRecorder(reopened, "ui-check", registry, lambda: snapshot)
        provider = RecordedProvider(connection, tmp_path / (stage + "-transport.json"),
                                    redact_payload=True, transport_observer=recorder.observe_transport)
        provider.generation = config.resolve_preset().to_generation_settings()
        loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider,
                                     hook_factories=[recorder.hook_factory])
        for name in list(registry.tool_names):
            registry.unregister(name)
        registry.register(BusinessTool(operation, reopened, {
            "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection",
            "dataset_version": "1", "session_id": stage, "request_id": stage,
        }, {}, RedactedEventList()))
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(recorder.context)
            async with asyncio.timeout(120):
                result = await bot.run(
                    "请读取当前Runtime提供的maintained_prompts，仅输出JSON对象，字段prompt_id、prompt_version、active_version、quote。"
                    "quote逐字引用当前提示词中的财务公式。不要调用工具或产生业务动作。不要输出Markdown。",
                    session_key=stage, sender_id="boss-1",
                )
        assert result.stop_reason == "completed" and not result.error
        answer = json.loads(result.content)
        assert {key: answer[key] for key in ("prompt_id", "prompt_version", "active_version")} == {
            key: prompt[key] for key in ("prompt_id", "prompt_version", "active_version")
        }
        assert answer["quote"] and answer["quote"] in original
        row = next(item for item in runtime_records(ControlStore(store.path), "MAINTAINER")["runs"]
                   if item["session_id"] == stage)
        assert row["status"] == "SUCCEEDED" and row["model_completion_observed"]
        assert row["usage_coverage"] == "COMPLETE_OBSERVED_REQUESTS"
        assert row["configuration_version"] == ("1" if stage == "first" else "2")
        assert row["dataset_id"] == "selection" and row["dataset_version"] == "1"
        assert row["usage"]["prompt_cache_hit_tokens"] >= 0 and row["usage"]["prompt_cache_miss_tokens"] >= 0
        assert row["runtime"]["max_tool_rounds"] == rounds
        assert row["prompt_versions"][0]["prompt_version"] == prompt["prompt_version"]
        assert [item["tool_id"] for item in row["tool_configuration"]] == [operation]
        assert len(row["model_requests"]) == 1 and row["model_requests"][0]["response_ids"]
        assert row["tool_results"] == []
        assert all(item["run_id"] == row["run_id"] for item in provider.requests)
        assert all(item["configuration_version"] == row["configuration_version"] for item in provider.requests)
        assert original not in json.dumps(row, ensure_ascii=False)
        evidence.append({"stage": stage, "runtime_record": row, "prompt_version_adoption_verified": True,
                         "tool_schema_transport_matches": True, "answer_sha256": hashlib.sha256(result.content.encode()).hexdigest()})

    async def check():
        await run("first", first_prompt, 12, "query_metrics")
        async with TestServer(application(store.path)) as server, aiohttp.ClientSession() as client:
            async with client.put(server.make_url("/spaces/ui-check/configuration"),
                                  headers={"Authorization": "Bearer " + os.environ["MAINTAINER_PROBE_TOKEN"]},
                                  json={"version": "1", "max_tool_rounds": 2}) as response:
                assert response.status == 200
                updated = await response.json()
                assert updated["version"] == "2" and updated["max_tool_rounds"] == 2
        second_prompt = activate(api, original, first_prompt)
        await run("second", second_prompt, 2, "read_evidence")
        assert evidence[0]["runtime_record"]["tool_config_sha256"] != evidence[1]["runtime_record"]["tool_config_sha256"]
        with store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','outbox','message_outbox')").fetchone()[0] == 0
        assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in input_hashes.items())
        (tmp_path / "runtime-version-adoption.json").write_text(json.dumps({
            "status": "PASS", "source_type": "SIMULATED", "stages": evidence,
            "new_runtime_and_session_per_stage": True, "business_mutation_performed": False,
            "full_A16_accepted": False, "full_A19_accepted": False,
            "source_code_sha256": input_hashes,
        }, ensure_ascii=False, indent=2))
    asyncio.run(check())
