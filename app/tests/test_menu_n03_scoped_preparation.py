import asyncio
import json
import sys

import pytest
from aiohttp import web
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.session.manager import SessionManager

from boss_command_api import BossCommandAPI
from business import checksum
from connection import settings
from product_assignment import ProductAssignment, AssignmentReadTool
from product_bi import ProductBI, FeatureProvider, FeatureRecorder, FeatureToolRegistry
from product_fc01 import ProductFc01
from product_runtime import ProductRuntime
from runtime_assignment_source_tool import BossAssignmentSourcesReadTool
from sop_write_tools.fc01 import Fc01Tool, TOOLS
from test_menu_n03_preparation import preparation, create_task, selection


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("经营准备实际SDK检查禁止外部连接")


sys.addaudithook(prohibit_network)


def business_state(store):
    with store.connect() as db:
        return db.execute("SELECT namespace,kind,id,body FROM objects WHERE kind NOT IN "
            "('runtime_run','assignment_public_request','overview_assignment_preparation') ORDER BY namespace,kind,id").fetchall()


def test_scoped_preparation_runs_actual_sdk_and_same_key_never_repeats(preparation, tmp_path):
    settings()
    store, api, bridge = preparation
    task = create_task(store, "n03-scoped-public-task")
    original = selection(api, task, {"page_id": "F14", "use": None})
    code, current = BossCommandAPI(store).execute("BOSS", "boss.business_overview.preparation", original)
    assert code == 200 and current["current_use_verified"]
    assert BossCommandAPI(store).execute("BOSS", "boss.business_overview.preparation.verify",
        {"input": original, "context_sha256": current["context_sha256"]})[0] == 200
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(tmp_path / "workspace"), "provider": "deepseek",
        "model": "deepseek-flash", "maxToolIterations": 6, "maxTokens": 700, "maxToolResultChars": 200000,
        "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
        "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com"}}})
    path = tmp_path / "config.json"
    save_config(config, path)
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "native-sessions")
    service, fc01, bi = ProductAssignment(store), ProductFc01(store), ProductBI(store)
    registry = FeatureToolRegistry()
    provider = FeatureProvider(fc01, bi, assignment=service)
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi, assignment=service)
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry,
        session_manager=sessions, hook_factories=[recorder.hook_factory])
    tools = [AssignmentReadTool(Fc01Tool(store, fc01.context_provider, name), service) if name == "read_assignment"
        else Fc01Tool(store, fc01.context_provider, name) for name in sorted(TOOLS)]
    tools.append(AssignmentReadTool(BossAssignmentSourcesReadTool(store, "BOSS"), service))
    runtime = ProductRuntime(store, path, loop, registry, tools, provider)
    service.runtime = fc01.runtime = bi.runtime = runtime
    commands, state = BossCommandAPI(store, runtime), runtime.read()
    code, draft = commands.execute("MAINTAINER", "boss.runtime.save", {"client_request_id": "n03-scoped-runtime-save",
        "expected_version": state["draft"]["version"] if state["draft"] else "0", "values": {"max_tool_rounds": 6,
        "max_output_tokens": 700, "tool_scope": ["read_assignment", "assignmentSourcesRead"]}})
    assert code == 200, draft
    code, checked = commands.execute("MAINTAINER", "boss.runtime.validate", {"client_request_id": "n03-scoped-runtime-validate",
        "expected_version": draft["version"], "expected_content_sha256": draft["content_sha256"]})
    assert code == 200, checked
    code, enabled = commands.execute("MAINTAINER", "boss.runtime.activate", {"client_request_id": "n03-scoped-runtime-activate",
        "expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"], "expected_active_version": state["current"]["version"]})
    assert code == 200, enabled
    before = business_state(store)
    payload = {"client_request_id": "n03-scoped-original-request", "input": original, "context_sha256": current["context_sha256"]}
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            service.bot = bot
            for context in (runtime.context, service.scope_context, recorder.context):
                bot.runtime.add_context_provider(context)
            result = await service.prepare_overview("BOSS", payload, lambda: True)
            assert result["current_use_verified"] is False and result["write_performed_by_lookup"] is False
            receipt = result["assignment_receipt"]
            assert receipt["request_state"] == "SUCCEEDED" and receipt["adoption_state"] == "CURRENT"
            assert receipt["preparation"]["task"]["task_id"] == task["id"]
            assert receipt["preparation"]["source_review"]["review_sha256"] == current["assignment_context"]["review_sha256"]
            with store.connect() as db:
                runs = db.execute("SELECT body FROM objects WHERE kind='runtime_run'").fetchall()
                assert len(runs) == 1
                saved = json.loads(runs[0][0])
                assert [row["tool_id"] for row in saved["tool_results"]] == ["read_assignment", "assignmentSourcesRead"]
            assert await service.prepare_overview("BOSS", payload, lambda: True) == result
            alternative = selection(api, task)
            other = bridge.read("BOSS", alternative)
            with pytest.raises(web.HTTPConflict):
                await service.prepare_overview("BOSS", {**payload, "input": alternative, "context_sha256": other["context_sha256"]}, lambda: True)
            with store.connect() as db:
                assert db.execute("SELECT body FROM objects WHERE kind='runtime_run'").fetchall() == runs
            assert service.overview_receipt("BOSS", payload["client_request_id"], lambda: True) == result
            bridge.verify("BOSS", original, current["context_sha256"])
            return result
    result = asyncio.run(execute())
    assert business_state(store) == before
    with store.connect() as db:
        record = store.get(db, "ui-check", "overview_assignment_preparation", payload["client_request_id"])
        assert record["input_sha256"] == checksum(payload) and record["input"] == original
        assert len(db.execute("SELECT 1 FROM objects WHERE kind='overview_assignment_preparation'").fetchall()) == 1
    assert result["business_authorization_granted"] is False and result["business_mutation_performed"] is False


def test_scoped_public_input_roles_and_old_context_reject_without_writes(preparation):
    store, api, bridge = preparation
    task = create_task(store, "n03-scoped-refusal-task")
    original = selection(api, task)
    current = bridge.read("BOSS", original)
    payload = {"client_request_id": "n03-scoped-refusal-original", "input": original, "context_sha256": current["context_sha256"]}
    service = ProductAssignment(store)
    with store.connect() as db:
        before = db.execute("SELECT * FROM objects ORDER BY namespace,kind,id").fetchall()
    for role in (None, "MAINTAINER"):
        with pytest.raises(web.HTTPForbidden):
            asyncio.run(service.prepare_overview(role, payload, lambda: True))
    for value in ({**payload, "owner_id": "other"}, {**payload, "context_sha256": "0" * 64}):
        with pytest.raises(web.HTTPException):
            asyncio.run(service.prepare_overview("BOSS", value, lambda: True))
    assert BossCommandAPI(store).execute("MAINTAINER", "boss.business_overview.preparation", original)[0] == 403
    assert BossCommandAPI(store).execute(None, "boss.business_overview.preparation", original)[0] == 401
    with store.connect() as db:
        assert db.execute("SELECT * FROM objects ORDER BY namespace,kind,id").fetchall() == before
