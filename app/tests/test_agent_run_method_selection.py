from pathlib import Path

import pytest
from aiohttp import web
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import save_config
from nanobot.config.schema import Config

from agent_run_broker import RunBroker, RunIdentity
from agent_run_api import VALIDATORS
from agent_run_method_selection import AgentRunMethodSelection
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from model_probe import BusinessTool
from test_agent_run_result import setup_result


ROOT = Path(__file__).resolve().parents[2]


def test_method_selection_requires_real_method_dependencies(tmp_path):
    store, runs, result, sink = setup_result(tmp_path, full_sources=True)
    config = Config()
    config.agents.defaults.workspace = str(ROOT / "agent")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    registry = ToolRegistry()
    envelope = {"request_id": "method-check", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1", "session_id": "result-check"}
    for operation in ("query_metrics", "read_evidence"):
        registry.register(BusinessTool(operation, store, envelope, {}, []))
    catalog = BossSkillCatalog(SkillsLoader(ROOT / "agent"), registry)
    drafts = BossSkillDrafts(store, catalog, config_path)
    selection_service = AgentRunMethodSelection(runs, result.scope, catalog, drafts, allow_migration=True)
    broker = RunBroker(runs, scope_service=result.scope, method_selection=selection_service)
    with drafts._locked(), runs.connect() as db:
        db.execute("BEGIN")
        methods = selection_service.catalog_in_transaction(db)
        meeting_method = next(item for item in methods if item["sop_id"] == "SOP04")
        assert meeting_method["status"] == "UNAVAILABLE" and "RUNTIME_TOOLS_MISSING" in meeting_method["reasons"]
        assert "boss.meeting.brief.prepare" in meeting_method["missing_runtime_tools"]
        assert VALIDATORS["method_catalog"].is_valid({"run_id": sink.config.run_id, "goal_revision": 1, "selection_allowed": False, "methods": methods})
    proof = result.scope.prove("result-check", ["simulation-meeting-material"])
    identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}), frozenset({"simulation-meeting-material"}))
    _, references = catalog.context("BOSS", ["SOP03"])
    method = references[0]
    selection = {key: method[key] for key in ("sop_id", "version", "content_sha256")}
    payload = {"conversation_id": proof.chat_id, "goal": "核查模拟会议资料", "selected_refs": ["simulation-meeting-material"], "request_key": "selected-method", "method_selection": selection}
    assert VALIDATORS["create"].is_valid(payload)
    assert not VALIDATORS["create"].is_valid({**payload, "method_selection": {"sop_id": "SOP03"}})
    unauthorized = RunIdentity(proof.owner_id, proof.namespace, "MAINTAINER", identity.conversation_ids, identity.source_refs)
    with pytest.raises(web.HTTPForbidden):
        broker.create(unauthorized, payload)
    with pytest.raises(web.HTTPUnauthorized) as missing:
        broker.create(identity, payload)
    assert "本人会话" in missing.value.text
    with pytest.raises(web.HTTPConflict) as changed:
        broker.create(identity, {**payload, "method_selection": {**selection, "content_sha256": "0" * 64}})
    assert "版本或摘要" in changed.value.text
    with pytest.raises(web.HTTPServiceUnavailable):
        RunBroker(runs, scope_service=result.scope).create(identity, payload)
    with pytest.raises(ValueError, match="缺少明确方法选择"):
        selection_service.require_current(sink)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="配置锁"):
            broker.create_in_transaction(db, identity, payload)
        assert db.execute("SELECT count(*) FROM agent_run_method_selections").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_api_requests WHERE request_key=?", ("selected-method",)).fetchone() == (0,)


def test_goal_supplements_and_reselection_require_current_context(tmp_path):
    store, runs, result, sink = setup_result(tmp_path, full_sources=True)
    config = Config()
    config.agents.defaults.workspace = str(ROOT / "agent")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    catalog = BossSkillCatalog(SkillsLoader(ROOT / "agent"), ToolRegistry())
    drafts = BossSkillDrafts(store, catalog, config_path)
    service = AgentRunMethodSelection(runs, result.scope, catalog, drafts, allow_migration=True)
    broker = RunBroker(runs, scope_service=result.scope, method_selection=service)
    proof = result.scope.prove("result-check", ["simulation-meeting-material"])
    identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}), frozenset({"simulation-meeting-material"}))
    added = runs.add_input(sink.config.run_id, 1, "meeting-input", "补充会议资料要求")
    payload = {"expected_goal_revision": 2, "request_key": "method-reselection", "method_selection": {"sop_id": "SOP04", "version": "0.1.0", "content_sha256": "0" * 64}}
    assert VALIDATORS["method_reselection"].is_valid(payload)
    assert not VALIDATORS["method_reselection"].is_valid({**payload, "actor_id": proof.owner_id})
    assert VALIDATORS["inputs"].is_valid({"expected_goal_revision": 1, "request_key": "meeting-input", "input": "补充会议资料要求"})
    with pytest.raises(web.HTTPUnauthorized):
        service.reselect(broker, identity, sink.config.run_id, payload, request=None)
    with pytest.raises(web.HTTPUnauthorized):
        service.request_receipt(broker, identity, sink.config.run_id, "method-reselection", request=None)
    with pytest.raises(web.HTTPUnauthorized):
        service.catalog_for_run(broker, identity, sink.config.run_id, request=None)
    assert "SELECT_METHOD" not in broker.read(identity, sink.config.run_id)["allowed_actions"]
    with runs.connect() as db:
        db.execute("BEGIN")
        goal, _ = service._goal_snapshot(db, sink.config.run_id, 2)
        assert goal["inputs"][-1] == [added["input_id"], 1, 2, "meeting-input", "补充会议资料要求"]
        assert service.read_in_transaction(db, sink.config.run_id) is None
        assert db.execute("SELECT count(*) FROM agent_run_method_reselections").fetchone() == (0,)
        with pytest.raises(ValueError, match="目标版本"):
            service._goal_snapshot(db, sink.config.run_id, 1)
    runs.apply_input(sink.config.run_id, 1, sink.lease_owner, sink.config.lease_epoch)
    runs.add_input(sink.config.run_id, 2, "later-input", "再次补充会议资料")
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="目标版本"):
            service._goal_snapshot(db, sink.config.run_id, 2)
        old_goal, _ = service._goal_snapshot(db, sink.config.run_id, 2, allow_historical=True)
        assert old_goal["inputs"][-1][0] == added["input_id"] and len(old_goal["inputs"]) == 1
        goal, _ = service._goal_snapshot(db, sink.config.run_id, 3)
        assert [item[3] for item in goal["inputs"]] == ["meeting-input", "later-input"]
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    with pytest.raises((ValueError, web.HTTPException)):
        broker.read(identity, sink.config.run_id)
    with pytest.raises(web.HTTPUnauthorized):
        service.reselect(broker, identity, sink.config.run_id, payload, request=None)
