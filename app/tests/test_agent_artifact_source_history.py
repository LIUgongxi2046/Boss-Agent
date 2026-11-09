import asyncio
import json
import sqlite3
import socket
from dataclasses import asdict
from uuid import uuid4

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_artifact_api import OwnerArtifactReader
from agent_artifact_source_history_routes import VALIDATOR, install_artifact_source_history_routes
from agent_artifacts import ArtifactPreparation
from agent_source_history import AgentSourceHistory
from boss_command_api import BossCommandAPI
from business import checksum
from role_channel import RoleChannel
from test_agent_run_dispatcher import services_for
from test_agent_run_result import setup_result


def set_binding(store, results, document):
    session_id = results.scope.sources.sessions.get_or_create("websocket:result-check").key
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        binding = store.get(db, "ui-check", "conversation_source_binding", session_id)
        selection = {"source_id": document["source_id"], "version": document["version"]}
        binding["source_refs"] = [selection]
        binding["source_pins"] = [{**selection, "content_sha256": checksum(document)}]
        store.put(db, "ui-check", "conversation_source_binding", session_id, binding)


def test_artifact_source_history_tracks_original_source_and_withdrawal(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    commands = BossCommandAPI(store)
    source = {"client_request_id": "artifact-history-create", "source_id": "sim-doc-artifact-history", "title": "模拟会议资料", "author_contact_id": "finance-1", "published_at": "2020-01-01", "content": "模拟会议资料记录会议议题、负责人和需要确认的讨论事项，以及会议准备材料。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.create", source)[0] == 200
    with store.connect() as db:
        original = store.get(db, "ui-check", "document", source["source_id"])
    set_binding(store, results, original)
    proof = results.scope.prove("result-check", [source["source_id"]])
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", (json.dumps([source["source_id"]]), json.dumps(asdict(proof)), sink.config.run_id))
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 2, 200000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=2, max_bytes=200000)
    artifact = preparation.create_meeting_brief(sink.config.run_id, [source["source_id"]], request_key="artifact-history", format_name="MARKDOWN")
    history = AgentSourceHistory(runs, results.scope)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert store.get(db, "ui-check", "document_revision", source["source_id"] + ":v1") == original
        current = history.read_artifact_in_transaction(db, sink.config.run_id, artifact["artifact_id"], 1, source["source_id"], "1")
        VALIDATOR.validate(current)
        assert current["historical"] is False and current["artifact_sha256"] == artifact["sha256"]
        assert current["content"] == source["content"]
        with pytest.raises(web.HTTPNotFound):
            history.read_artifact_in_transaction(db, sink.config.run_id, artifact["artifact_id"], 2, source["source_id"], "1")
    revised = {**source, "client_request_id": "artifact-history-revise", "expected_version": "1", "content": "模拟会议资料更新了会议议题、负责人和需要确认的讨论事项，以及会议准备材料。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.revise", revised)[0] == 200
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", source["source_id"])
    set_binding(store, results, document)
    bus, config = MessageBus(), WebSocketConfig()
    sessions = results.scope.sources.sessions
    gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / "config.json", runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
    reader = OwnerArtifactReader(channel, results.scope, workspace)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.row_factory = sqlite3.Row
        record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact["artifact_id"],)).fetchone()
        db.row_factory = None
        scope = {key: getattr(proof, key) for key in ("owner_id", "namespace", "dataset_id", "dataset_version")}
        metadata, _ = reader._verify_record(db, record, [source["source_id"]], scope, 1)
        assert metadata["source_refs"][0]["revision"] == "1"
        with pytest.raises(ValueError, match="来源版本已经变化"):
            reader._verify_record(db, record, [source["source_id"]], scope, 1, require_current_source=True)
        old = history.read_artifact_in_transaction(db, sink.config.run_id, artifact["artifact_id"], 1, source["source_id"], "1")
        VALIDATOR.validate(old)
        assert old["historical"] is True and old["current_version"] == "2"
        assert old["content"] == source["content"] and old["sha256"] == checksum(original)
        assert old["locator_verification"] == "NOT_VERIFIED"
        store.put(db, "ui-check", "document_history", source["source_id"] + ":1", {**original, "content": revised["content"]})
        with pytest.raises(web.HTTPConflict):
            history.read_artifact_in_transaction(db, sink.config.run_id, artifact["artifact_id"], 1, source["source_id"], "1")
        db.rollback()
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM objects WHERE namespace=? AND kind=? AND id=?", ("ui-check", "document_revision", source["source_id"] + ":v1"))
        with pytest.raises(web.HTTPNotFound) as error:
            history.read_artifact_in_transaction(db, sink.config.run_id, artifact["artifact_id"], 1, source["source_id"], "1")
        assert error.value.text == "历史来源正文未保存"
        db.rollback()
    with store.connect() as db:
        other = store.get(db, "ui-check", "document", "finance-note")
    set_binding(store, results, other)
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPForbidden):
            history.read_artifact_in_transaction(db, sink.config.run_id, artifact["artifact_id"], 1, source["source_id"], "1")
    set_binding(store, results, document)
    store.hermes_source_sessions = results.scope.sources.sessions
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", {"client_request_id": "artifact-history-withdraw", "source_id": source["source_id"], "expected_version": "2"})[0] == 200
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises((web.HTTPGone, web.HTTPConflict)):
            history.read_artifact_in_transaction(db, sink.config.run_id, artifact["artifact_id"], 1, source["source_id"], "1")


def test_artifact_history_route_rejects_unauthenticated_and_cross_origin(tmp_path):
    services = services_for(tmp_path)

    async def exercise():
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        app = web.Application()
        install_artifact_source_history_routes(app, services.recovery.channel, services.store, services.scope, public_port=port)
        with pytest.raises(ValueError, match="已经注册"):
            install_artifact_source_history_routes(app, services.recovery.channel, services.store, services.scope, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        base = "http://127.0.0.1:" + str(port)
        path = "/api/v2/runs/" + str(uuid4()) + "/artifacts/" + str(uuid4()) + "/source-history?source_id=finance-note&version=1&artifact_version=1"
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                assert (await client.get(base + path)).status_code == 401
                assert (await client.get(base + path, headers={"X-Boss-Role": "BOSS"})).status_code == 401
                assert (await client.get(base + path, headers={"Origin": "https://example.invalid"})).status_code == 403
                assert (await client.post(base + path)).status_code == 405
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
