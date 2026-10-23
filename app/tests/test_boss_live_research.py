import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from loguru import logger
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from business import checksum
from boss_command_api import BossCommandAPI
from boss_agent_read_tools import BossResearchSourcesTool
from connection import RecordedProvider, settings
from controls import ControlStore

pytestmark = pytest.mark.skipif(
    os.environ.get("BOSS_RUN_LIVE") != "1",
    reason="需要显式启用获准 SIMULATED 资料的真实 DeepSeek 引用检查",
)


def test_live_current_citations_after_revision_conflict_and_withdrawal(tmp_path):
    connection = settings()
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    store = ControlStore(tmp_path / "approved-research.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        original = store.get(db, "ui-check", "document", "finance-note")
    assert initial["source_type"] == "SIMULATED"
    assert checksum(initial) == "75e5c19645f0e7cd1f5036a0a441de0a1a59c8eb1b9d1be5137ef0414eb2f345"
    status, _ = BossCommandAPI(store).execute("BOSS", "boss.research.prepare", {
        "client_request_id": "w2-live-source-research", "expected_version": "0",
        "question": original["content"].split("；", 1)[0],
        "period": "", "country": "", "business_relation": "", "cutoff_date": "2026-10-22",
    })
    assert status == 200
    evidence = []

    async def read_current(stage):
        reopened = ControlStore(store.path)
        config = Config.model_validate({
            "agents": {"defaults": {
                "provider": "deepseek", "model": connection["model_id"],
                "workspace": str(tmp_path / "workspace"),
                "maxToolIterations": 3, "maxTokens": 700,
                "dream": {"enabled": False}, "idleCompactAfterMinutes": 0,
            }}, "gateway": {"heartbeat": {"enabled": False}},
        })
        observations = []
        registry = ToolRegistry()
        provider = RecordedProvider(connection, tmp_path / (stage + "-transport.json"), redact_payload=True)
        provider.generation = config.resolve_preset().to_generation_settings()
        loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider)
        for name in list(registry.tool_names):
            registry.unregister(name)
        registry.register(BossResearchSourcesTool(reopened, "BOSS", observation_sink=observations.append))
        async with Nanobot(loop, config=config) as bot:
            async with asyncio.timeout(120):
                result = await bot.run(
                    "调用 bossWorkspaceRead 读取当前研究来源。只依据可作为当前依据的来源返回一项准确原文引用。"
                    "仅输出 JSON 对象，字段 source_id、version、quote、usable_as_current_evidence。"
                    "没有可采用引用时，前三项为 null，usable_as_current_evidence 为 false。"
                    "冲突资料供核查，不能选择其中一项作为已确认事实。不要输出 Markdown。",
                    session_key="research-" + stage, sender_id="boss-1",
                )
        assert result.stop_reason == "completed" and not result.error
        assert observations
        answer = json.loads(result.content)
        assert set(answer) == {"source_id", "version", "quote", "usable_as_current_evidence"}
        evidence.append({
            "stage": stage, "stop_reason": result.stop_reason,
            "tool_observations": observations,
            "usable_as_current_evidence": answer["usable_as_current_evidence"],
            "source_id": answer["source_id"], "source_version": answer["version"],
            "answer_sha256": hashlib.sha256(result.content.encode()).hexdigest(),
            "response_ids": sorted({item["response_id"] for item in provider.requests if item.get("response_id")}),
            "private_body_recorded": False,
        })
        return answer

    async def check():
        before = await read_current("original")
        assert before["usable_as_current_evidence"] is True
        assert before["source_id"] == original["source_id"] and before["version"] == "1"
        assert before["quote"] and before["quote"] in original["content"]
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revised = {**original, "version": "2"}
            store.put(db, "ui-check", "document", "finance-note", revised)
        after_revision = await read_current("revised")
        assert after_revision["usable_as_current_evidence"] is True
        assert after_revision["source_id"] == original["source_id"] and after_revision["version"] == "2"
        assert after_revision["quote"] and after_revision["quote"] in original["content"]
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conflicted = {**revised, "version": "3", "validity_state": "CONFLICTED"}
            store.put(db, "ui-check", "document", "finance-note", conflicted)
        conflict = await read_current("conflicted")
        assert conflict == {"source_id": None, "version": None, "quote": None, "usable_as_current_evidence": False}
        store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "3"})
        withdrawn = await read_current("withdrawn")
        assert withdrawn == {"source_id": None, "version": None, "quote": None, "usable_as_current_evidence": False}
        with store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','outbox','message_outbox')").fetchone()[0] == 0
        (tmp_path / "source-citation-result.json").write_text(json.dumps({
            "status": "PASS", "source_type": "SIMULATED", "stages": evidence,
            "source_body_unchanged": True, "new_runtime_and_session_per_stage": True,
            "business_write_performed": False, "full_A15_accepted": False,
            "source_code_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in ("validation/boss_research.py", "validation/boss_source_policy.py",
                             "validation/boss_agent_read_tools.py",
                             "app/tests/test_boss_live_research.py")
            },
        }, ensure_ascii=False, indent=2))

    asyncio.run(check())
