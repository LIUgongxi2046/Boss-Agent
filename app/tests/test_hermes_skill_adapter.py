import asyncio
import shutil
from pathlib import Path

import pytest
import httpx
from aiohttp import web
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_run_broker import RunBroker, RunIdentity
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_context_tools import HermesContextTools
from hermes_memory_adapter import HermesMemoryAdapter
from hermes_skill_adapter import HermesSkillAdapter, HermesSkillMaintenance
from model_probe import BusinessTool
from role_channel import RoleChannel


ROOT = Path(__file__).resolve().parents[2]


def test_real_method_adoption_candidate_and_disabled_rejection(tmp_path):
    workspace = tmp_path / "workspace"
    shutil.copytree(ROOT / "agent/skills", workspace / "skills")
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(workspace, business_store=store, sessions_root=tmp_path / "sessions")
    sessions.save(sessions.get_or_create("websocket:skill-check"), fsync=True)
    scope = RunScopeService(store, sessions, "ui-check")
    runs = RunStore(store.path)
    identity = RunIdentity("boss-1", "ui-check", "BOSS", frozenset({"skill-check"}), frozenset())
    run_id = RunBroker(runs, scope_service=scope).create(identity, {"conversation_id": "skill-check", "goal": "核查经营指标", "selected_refs": [], "request_key": "skill-check"})["run_id"]
    lease = runs.acquire_lease(run_id, 0, "skill-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "skill-worker", lease["epoch"])
    run = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    registry = ToolRegistry()
    envelope = {"request_id": "skill-check", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1", "session_id": "skill-check"}
    for operation in ("query_metrics", "read_evidence"):
        registry.register(BusinessTool(operation, store, envelope, {}, []))
    loader = SkillsLoader(workspace)
    catalog = BossSkillCatalog(loader, registry)
    drafts = BossSkillDrafts(store, catalog, config_path)
    adapter = HermesSkillAdapter(store, scope, catalog, drafts, run_gate=EngineEventSink(runs, run, "skill-worker"), sop_id="SOP03")
    result = adapter.read()
    assert result["reference"]["method"]["sop_id"] == "SOP03"
    assert result["content"]
    meeting_adapter = HermesSkillAdapter(store, scope, catalog, drafts, run_gate=adapter.run_gate, sop_id="SOP04")
    memory = HermesMemoryAdapter(store, scope, run_gate=adapter.run_gate)
    with pytest.raises(web.HTTPConflict) as missing_tools:
        HermesContextTools.assemble(memory, meeting_adapter)
    assert "Hermes 运行工具缺少" in missing_tools.value.text
    with pytest.raises(web.HTTPConflict):
        meeting_adapter.read()
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_skill_adoption' AND id=?", ("ui-check", run_id + ":SOP04")).fetchone() is None
        assert db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_adoption' AND id=?", ("ui-check", run_id)).fetchone() is None
    items, _ = catalog._snapshot()
    meeting_method = next(item for item in items if item["sop_id"] == "SOP04")
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPConflict) as no_selection:
            HermesContextTools.require_selected_method_in_transaction(db, run_id, meeting_method)
        assert no_selection.value.text == "当前目标缺少明确方法选择"
    adapter.require_current(result["reference"])
    source = (workspace / "skills/boss-sop03/SKILL.md").read_text(encoding="utf-8")
    candidate = adapter.save_candidate(source)
    assert candidate["state"] == "DRAFT" and candidate["enabled"] is False and candidate["validation_status"] == "NOT_RUN"
    with ControlStore(store.path).connect() as db:
        stored = store.get(db, "ui-check", "hermes_skill_candidate", candidate["candidate_id"])
        assert stored["content"] == source and stored["base_method"] == result["reference"]["method"]
        with pytest.raises(web.HTTPForbidden):
            drafts.require_candidate_authorization(db, stored, "", source)
    with pytest.raises(ValueError, match="已经变化"):
        adapter.inspect_candidate(candidate["candidate_id"], "0" * 64)
    with pytest.raises(ValueError, match="候选版本"):
        adapter.inspect_candidate(candidate["candidate_id"], candidate["content_sha256"])
    registry.unregister("read_evidence")
    with pytest.raises(web.HTTPConflict):
        adapter.require_current(result["reference"])
    registry.register(BusinessTool("read_evidence", store, envelope, {}, []))
    adapter.require_current(result["reference"])
    current = load_config(config_path)
    current.agents.defaults.disabled_skills = ["boss-sop03"]
    save_config(current, config_path)
    loader.disabled_skills.add("boss-sop03")
    with pytest.raises(web.HTTPConflict):
        adapter.require_current(result["reference"])
    with pytest.raises(web.HTTPConflict):
        adapter.read()
    with pytest.raises(web.HTTPConflict):
        adapter.save_candidate(source)


def test_maintenance_http_requires_actual_authenticated_request(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")

    async def exercise():
        bus, config = MessageBus(), WebSocketConfig()
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        service = HermesSkillMaintenance(channel, store)

        async def publish(request):
            return web.json_response(service.publish(request, request.match_info["candidate_id"]))

        async def disable(request):
            return web.json_response(service.disable(request, {}))

        async def validate(request):
            return web.json_response(service.validate(request, request.match_info["candidate_id"], "0" * 64))

        async def preview(request):
            return web.json_response(service.preview(request, request.match_info["candidate_id"]))

        async def decide(request):
            return web.json_response(service.decide(request, request.match_info["candidate_id"], {}))

        async def status(request):
            return web.json_response(service.publication_status(request, request.match_info["candidate_id"], "current"))

        async def candidates(request):
            return web.json_response(service.list_candidates(request))

        async def detail(request):
            return web.json_response(service.maintenance_detail(request, request.match_info["candidate_id"]))

        async def decision_status(request):
            return web.json_response(service.decision_status(request, request.match_info["candidate_id"], "current"))

        app = web.Application()
        app.router.add_post("/candidate/{candidate_id}/publish", publish)
        app.router.add_post("/candidate/{candidate_id}/validate", validate)
        app.router.add_get("/candidate/{candidate_id}", preview)
        app.router.add_post("/candidate/{candidate_id}/decision", decide)
        app.router.add_get("/candidate/{candidate_id}/publication", status)
        app.router.add_get("/candidates", candidates)
        app.router.add_get("/candidate/{candidate_id}/maintenance", detail)
        app.router.add_get("/candidate/{candidate_id}/decision-status", decision_status)
        app.router.add_post("/disable", disable)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                url = "http://127.0.0.1:" + str(runner.addresses[0][1])
                assert (await client.post(url + "/candidate/current/publish")).status_code == 401
                assert (await client.post(url + "/candidate/current/validate")).status_code == 401
                assert (await client.get(url + "/candidate/current")).status_code == 401
                assert (await client.post(url + "/candidate/current/decision")).status_code == 401
                assert (await client.get(url + "/candidate/current/publication")).status_code == 401
                assert (await client.get(url + "/candidates")).status_code == 401
                assert (await client.get(url + "/candidate/current/maintenance")).status_code == 401
                assert (await client.get(url + "/candidate/current/decision-status")).status_code == 401
                assert (await client.post(url + "/disable")).status_code == 401
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
