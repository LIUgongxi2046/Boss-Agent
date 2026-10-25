import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from loguru import logger
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_admin_config import memory_technical_status
from boss_command_api import BossCommandAPI
from boss_memory_runtime import OwnerMemoryContext
from boss_runtime_records import RuntimeRecorder
from business import checksum
from connection import RecordedProvider, settings
from controls import ControlStore

parser = argparse.ArgumentParser()
parser.add_argument("--database", type=Path, required=True)
parser.add_argument("--action", choices=("prepare", "confirm", "revoke", "delete", "observe", "status"), required=True)
arguments = parser.parse_args()
database = arguments.database.resolve()
assert database.is_relative_to(ROOT / ".work")
if arguments.action == "prepare":
    assert not database.exists()
    source = ROOT / ".work/w2-checks/live-memory-confirmation/test_live_revoked_memory_confi0/memory-confirmation.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(database) as destination:
        original.backup(destination)
store = ControlStore(database)
with store.connect() as db:
    initial = store.get(db, "ui-check", "initial", "snapshot")
    current = store.get(db, "ui-check", "memory", "current")
assert checksum(initial) == "75e5c19645f0e7cd1f5036a0a441de0a1a59c8eb1b9d1be5137ef0414eb2f345"
api = BossCommandAPI(store)
receipt = None
if arguments.action in {"prepare", "confirm"}:
    status, receipt = api.execute("BOSS", "boss.memory.confirm", {
        "client_request_id": str(uuid4()), "expected_version": current["version"], "text": initial["memory"]["text"],
    })
    assert status == 200
elif arguments.action == "revoke":
    with store.connect() as db:
        confirmations = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='authorization'")]
    matches = [item for item in confirmations if item.get("action") == "memory.confirm"
               and item.get("target_id") == current["memory_id"]
               and int(item["content_version"]) + 1 == int(current["version"])]
    assert len(matches) == 1
    confirmation = matches[0]
    status, receipt = api.execute("BOSS", "boss.authorization.revoke", {
        "client_request_id": str(uuid4()), "authorization_id": confirmation["authorization_id"],
        "expected_version": confirmation["version"], "reason": "本人停止该模拟记忆的后续采用",
    })
    assert status == 200
elif arguments.action == "delete":
    status, receipt = api.execute("BOSS", "boss.memory.delete", {
        "client_request_id": str(uuid4()), "expected_version": current["version"],
    })
    assert status == 200
elif arguments.action == "observe":
    assert memory_technical_status(store, "MAINTAINER")["future_context_eligible"] is False
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
    connection = settings()
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    config_data = {"agents": {"defaults": {"provider": "deepseek", "model": connection["model_id"],
        "workspace": str(database.parent / "workspace"), "maxToolIterations": configuration["max_tool_rounds"],
        "maxTokens": 512, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
        "gateway": {"heartbeat": {"enabled": False}}}
    config = Config.model_validate(config_data)
    registry = ToolRegistry()
    recorder = RuntimeRecorder(store, "ui-check", registry, lambda: {
        "provider": configuration["provider"], "model_id": configuration["model_id"],
        "api_type": configuration["api_type"], "max_tool_rounds": configuration["max_tool_rounds"],
        "max_output_tokens": 512, "timeout": configuration["timeout"], "config_sha256": checksum(config_data),
    })
    transport_path = database.with_name("memory-context-" + str(uuid4()) + ".json")
    provider = RecordedProvider(connection, transport_path, redact_payload=True, transport_observer=recorder.observe_transport)
    provider.generation = config.resolve_preset().to_generation_settings()
    loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider, hook_factories=[recorder.hook_factory])
    for name in list(registry.tool_names):
        registry.unregister(name)

    async def observe():
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(OwnerMemoryContext(store))
            bot.runtime.add_context_provider(recorder.context)
            async with asyncio.timeout(120):
                result = await bot.run("当前模拟资料的有效简报阅读要求是什么？仅依据当前提供的确认记录回答，缺少记录请明确说明。",
                                       session_key="memory-ui-" + str(uuid4()), sender_id="boss-1")
        assert result.stop_reason == "completed" and not result.error
        assert "现金" not in result.content and "本人承诺" not in result.content
        return {"runtime_stop_reason": result.stop_reason,
                "answer_sha256": hashlib.sha256(result.content.encode()).hexdigest(),
                "transport_evidence": str(transport_path.relative_to(ROOT)),
                "model_request_count": sum(item["type"] == "request" for item in provider.requests)}

    receipt = asyncio.run(observe())
projection = memory_technical_status(ControlStore(database), "MAINTAINER")
assert initial["memory"]["text"] not in json.dumps(projection, ensure_ascii=False)
print(json.dumps({"status": "PASS", "action": arguments.action, "receipt": receipt, "projection": projection,
                  "external_request_sent": arguments.action == "observe", "source_database_modified": False}, ensure_ascii=False))
