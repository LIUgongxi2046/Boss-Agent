import hashlib
import asyncio
import json
import multiprocessing
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from uuid import uuid4

import pytest
import httpx
from aiohttp import web
from docx import Document
from jsonschema.exceptions import ValidationError
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_artifact_api import ArtifactService, HermesMeetingBriefTool, OwnerArtifactReader, closed_artifact_application, propagate_withdrawn_source_in_transaction, require_meeting_brief_boundary, withdrawn_pending_receipt_in_transaction, withdrawn_pending_requests_in_transaction
from agent_artifacts import ArtifactPreparation, read_verified_file, store_exact_file
from agent_artifact_workspace import ArtifactWorkspace
from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_artifact_formats import FORMATS, create_format
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_comprehensive_simulation import populate
from boss_memory_sessions import MemorySessionManager
from boss_simulation_api import _context
from business import checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_process_manager import IsolationBoundaryUnavailable
from role_channel import RoleChannel


@pytest.fixture
def prepared(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    populate(store, "2026-10-28T10:00:00+08:00")
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "brief-request", "brief-digest")
    lease = runs.acquire_lease(run_id, 0, "artifact-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "artifact-worker", lease["epoch"])
    runs.configure_file_budget(run_id, "artifact-worker", lease["epoch"], 1, 200000)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    gate = EngineEventSink(runs, config, "artifact-worker")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    service = ArtifactPreparation(store, workspace, run_gate=gate, scope_service=scope, max_files=1, max_bytes=200000)
    return store, workspace, service, runs, run_id, gate, scope


def test_unbound_source_cannot_create_or_register_artifact(prepared):
    store, workspace, service, _, run_id, _, _ = prepared
    with pytest.raises(ValueError, match="范围证明"):
        service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="brief")
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_artifacts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM agent_file_reservations").fetchone()[0] == 0
    assert list(workspace.glob("*.docx")) == []


def test_mapped_services_use_same_run_directory_and_reject_other_run(prepared, tmp_path):
    store, _, _, _, run_id, gate, scope = prepared
    root = tmp_path / "mapped"
    root.mkdir()
    mapping = ArtifactWorkspace(root.resolve())
    directory = mapping.create(run_id)
    preparation = ArtifactPreparation.for_run_workspace(store, mapping, run_gate=gate,
        scope_service=scope, max_files=1, max_bytes=200000)
    bus, config = MessageBus(), WebSocketConfig()
    gateway = build_gateway_services(config=config, bus=bus, session_manager=scope.sources.sessions,
        static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
        config_path=tmp_path / "config.json", runtime_model_name=None, runtime_surface="webui",
        runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
    reader = OwnerArtifactReader.for_run_workspace(channel, scope, mapping, run_id)
    assert preparation.workspace == reader.workspace == directory
    with pytest.raises(ValueError, match="范围证明"):
        preparation.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="mapped")
    with store.connect() as db, pytest.raises(ValueError, match="目录不符"):
        reader._verify_run(db, None, str(uuid4()))
    assert not list(directory.iterdir())


def test_meeting_brief_tool_rejects_unbound_scope_and_cancellation(prepared):
    store, workspace, preparation, runs, run_id, _, _ = prepared
    tool = HermesMeetingBriefTool(preparation)
    payload = {"source_ids": ["simulation-meeting-material"], "request_key": "brief-tool"}
    with pytest.raises(ValidationError):
        tool._execute_checked_scope({**payload, "path": str(workspace / "outside.docx")})
    with pytest.raises(ValidationError):
        tool._execute_checked_scope({**payload, "source_ids": []})
    with pytest.raises(ValueError, match="范围证明"):
        tool._execute_checked_scope(payload)
    runs.cancel(run_id, runs.read_run(run_id)["revision"])
    with pytest.raises(ValueError, match="取消"):
        tool._execute_checked_scope(payload)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_file_reservations").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM agent_artifacts").fetchone()[0] == 0
    assert not list(workspace.iterdir())


def test_meeting_brief_boundary_rejects_unverified_isolation():
    with pytest.raises(IsolationBoundaryUnavailable):
        require_meeting_brief_boundary()


@pytest.mark.parametrize("format_name", ["MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"])
def test_real_file_version_reservation_rejects_duplicate_and_changes(prepared, format_name):
    store, workspace, service, runs, run_id, gate, _ = prepared
    with store.connect() as db:
        db.execute("BEGIN")
        _, _, documents = service._sources(db, ["simulation-meeting-material"])
    content = create_format(format_name, documents)
    artifact_id = str(uuid4())
    storage_key = artifact_id + FORMATS[format_name][0]
    (workspace / storage_key).write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    assert read_verified_file(workspace, storage_key, len(content), digest) == content
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "version-check", digest, artifact_id, len(content)) is None
        db.execute("INSERT INTO agent_artifact_versions VALUES (?,?,1,NULL)", (artifact_id, artifact_id))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="尚待核查"):
            runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "version-check", digest, str(uuid4()), len(content))
        assert runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "version-check", digest, str(uuid4()), len(content), allow_reserved=True) == artifact_id
        with pytest.raises(ValueError, match="已经变化"):
            runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "version-check", "changed", str(uuid4()), len(content))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE agent_artifact_versions SET version=2 WHERE artifact_id=?", (artifact_id,))
    (workspace / storage_key).write_bytes(content + b"changed")
    with pytest.raises(ValueError, match="摘要"):
        read_verified_file(workspace, storage_key, len(content), digest)


def test_version_arguments_require_actual_predecessor(prepared):
    _, _, service, _, run_id, _, _ = prepared
    with pytest.raises(ValueError, match="前一版本"):
        service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="version", expected_version=1)
    with pytest.raises(ValueError, match="前一版本"):
        service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="version", previous_artifact_id=str(uuid4()), expected_version=0)


def test_unbound_reservation_release_preserves_file_and_budget(prepared):
    store, workspace, service, runs, run_id, gate, _ = prepared
    with store.connect() as db:
        db.execute("BEGIN")
        _, _, documents = service._sources(db, ["simulation-meeting-material"])
    content = create_format("MARKDOWN", documents)
    artifact_id = str(uuid4())
    path = workspace / (artifact_id + ".md")
    path.write_bytes(content)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "release-check", hashlib.sha256(content).hexdigest(), artifact_id, len(content))
    with pytest.raises(ValueError, match="运行范围"):
        service.release_unwritten_reservation(run_id, artifact_id, "release-check")
    runs.cancel(run_id, runs.read_run(run_id)["revision"])
    with pytest.raises(ValueError, match="运行范围"):
        service.release_unwritten_reservation(run_id, artifact_id, "release-check")
    assert path.read_bytes() == content
    with store.connect() as db:
        assert db.execute("SELECT status,size_bytes FROM agent_file_reservations WHERE artifact_id=?", (artifact_id,)).fetchone() == ("RESERVED", len(content))


def test_missing_source_and_path_traversal_are_rejected(prepared):
    store, workspace, service, _, run_id, _, _ = prepared
    with pytest.raises(ValueError):
        service.create_meeting_brief(run_id, [], request_key="brief")
    with store.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPException):
            service._sources(db, ["missing-source"])
    with pytest.raises(ValueError, match="运行编号"):
        service.create_meeting_brief(str(uuid4()), ["simulation-meeting-material"], request_key="brief")
    with pytest.raises(ValueError):
        service.read_meeting_brief("../business.sqlite")
    with pytest.raises(ValueError):
        service._read_bytes("../business.sqlite")
    assert list(workspace.glob("*.docx")) == []


def test_withdrawn_source_and_cancelled_run_are_rejected(prepared):
    store, _, service, runs, run_id, _, _ = prepared
    runs.cancel(run_id, runs.read_run(run_id)["revision"])
    with pytest.raises(ValueError, match="取消"):
        service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="brief")
    with store.connect() as db:
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPGone):
            service._sources(db, ["simulation-meeting-material"])


def test_expired_and_incorrect_leases_are_rejected(prepared):
    store, _, service, runs, run_id, gate, _ = prepared
    runs.release_lease(run_id, gate.lease_owner, gate.config.lease_epoch)
    with pytest.raises(ValueError, match="租约"):
        service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="brief")
    second = runs.create_run("boss-1", "ui-check", "another-request", "another-digest")
    lease = runs.acquire_lease(second, 0, "short-worker", 5)
    runs.transition(second, lease["revision"], "RUNNING", "short-worker", lease["epoch"])
    config = EngineRunConfig(second, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    service.run_gate = EngineEventSink(runs, config, "short-worker")
    time.sleep(5.1)
    with pytest.raises(ValueError, match="租约"):
        service.create_meeting_brief(second, ["simulation-meeting-material"], request_key="brief")


def test_other_run_owner_and_symbolic_link_are_rejected(prepared):
    _, workspace, service, runs, _, _, _ = prepared
    other = runs.create_run("different-owner", "ui-check", "other-request", "other-digest")
    lease = runs.acquire_lease(other, 0, "other-worker", 60)
    runs.transition(other, lease["revision"], "RUNNING", "other-worker", lease["epoch"])
    config = EngineRunConfig(other, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    service.run_gate = EngineEventSink(runs, config, "other-worker")
    with pytest.raises(ValueError, match="主体"):
        service.create_meeting_brief(other, ["simulation-meeting-material"], request_key="brief")
    other_space = runs.create_run("boss-1", "other-space", "space-request", "space-digest")
    lease = runs.acquire_lease(other_space, 0, "space-worker", 60)
    runs.transition(other_space, lease["revision"], "RUNNING", "space-worker", lease["epoch"])
    config = EngineRunConfig(other_space, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    service.run_gate = EngineEventSink(runs, config, "space-worker")
    with pytest.raises(ValueError, match="空间"):
        service.create_meeting_brief(other_space, ["simulation-meeting-material"], request_key="brief")
    storage_key = str(uuid4()) + ".docx"
    (workspace / storage_key).symlink_to(workspace.parent / "business.sqlite")
    with pytest.raises(OSError):
        service._read_bytes(storage_key)


def test_budget_is_persistent_and_rejects_excess(prepared):
    store, _, service, runs, run_id, gate, _ = prepared
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="预算不足"):
            runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "large", "digest", str(uuid4()), 200001)
        service.max_files = 2
        with pytest.raises(ValueError, match="预算尚未配置或已经变化"):
            service._require_budget(db, run_id)


def test_released_reservation_budget_accounting_in_sqlite(prepared):
    store, _, _, runs, run_id, gate, _ = prepared
    artifact_id = str(uuid4())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "released", "digest", artifact_id, 100)
        db.execute("UPDATE agent_file_reservations SET status='RELEASED' WHERE artifact_id=?", (artifact_id,))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="已经终止"):
            runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "released", "digest", str(uuid4()), 100, allow_reserved=True)
        runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "next", "digest", str(uuid4()), 100)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE agent_file_reservations SET status='RESERVED' WHERE artifact_id=?", (artifact_id,))


def test_same_request_reserves_once_with_concurrent_transactions(prepared):
    store, _, service, runs, run_id, gate, _ = prepared
    with store.connect() as db:
        db.execute("BEGIN")
        _, refs, _ = service._sources(db, ["simulation-meeting-material"])
    digest = refs[0]["sha256"]

    def reserve():
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "same-request", digest, str(uuid4()), 100)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(reserve) for _ in range(2)]
    assert sum(item.exception() is None for item in attempts) == 1
    assert sum(isinstance(item.exception(), ValueError) and "待核查" in str(item.exception()) for item in attempts) == 1
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT count(*) FROM agent_file_reservations").fetchone()[0] == 1
        with pytest.raises(ValueError, match="内容已经变化"):
            runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "same-request", "other-digest", str(uuid4()), 100)
        with pytest.raises(ValueError, match="预算不足"):
            runs.reserve_file_in_transaction(db, run_id, gate.lease_owner, gate.config.lease_epoch, "another-request", digest, str(uuid4()), 100)


def test_parent_and_child_share_budget_and_parent_cancellation(prepared, tmp_path):
    store, _, _, runs, root, gate, scope = prepared
    child = runs.create_child_run(root, gate.lease_owner, gate.config.lease_epoch, "child-request", "child-digest")
    assert runs.create_child_run(root, gate.lease_owner, gate.config.lease_epoch, "child-request", "child-digest") == child
    lease = runs.acquire_lease(child, 0, "child-worker", 60)
    runs.transition(child, lease["revision"], "RUNNING", "child-worker", lease["epoch"])
    config = EngineRunConfig(child, lease["epoch"], gate.config.engine_commit, gate.config.provider_url, 3)
    child_gate = EngineEventSink(runs, config, "child-worker")
    child_workspace = tmp_path / "child-artifacts"
    child_workspace.mkdir()
    ArtifactPreparation(store, child_workspace, run_gate=child_gate, scope_service=scope, max_files=1, max_bytes=200000)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        runs.reserve_file_in_transaction(db, root, gate.lease_owner, gate.config.lease_epoch, "root-file", "root-digest", str(uuid4()), 100)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="预算不足"):
            runs.reserve_file_in_transaction(db, child, child_gate.lease_owner, child_gate.config.lease_epoch, "child-file", "child-digest", str(uuid4()), 100)
    runs.cancel(root, runs.read_run(root)["revision"])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="父运行"):
            runs.reserve_file_in_transaction(db, child, child_gate.lease_owner, child_gate.config.lease_epoch, "child-file", "child-digest", str(uuid4()), 100)


def test_parent_child_concurrent_reservations_share_one_limit(prepared):
    store, _, _, runs, root, gate, _ = prepared
    child = runs.create_child_run(root, gate.lease_owner, gate.config.lease_epoch, "child-concurrent", "child-digest")
    child_lease = runs.acquire_lease(child, 0, "child-concurrent-worker", 60)
    runs.transition(child, child_lease["revision"], "RUNNING", "child-concurrent-worker", child_lease["epoch"])

    def reserve(run_id, owner, epoch):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return runs.reserve_file_in_transaction(db, run_id, owner, epoch, "file", "digest", str(uuid4()), 100)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(reserve, root, gate.lease_owner, gate.config.lease_epoch),
                 pool.submit(reserve, child, "child-concurrent-worker", child_lease["epoch"])]
    assert sum(item.exception() is None for item in tasks) == 1
    assert sum(isinstance(item.exception(), ValueError) and "预算不足" in str(item.exception()) for item in tasks) == 1
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_file_reservations WHERE root_run_id=?", (root,)).fetchone()[0] == 1


def test_failed_reservation_transaction_preserves_budget(prepared):
    store, _, _, runs, root, gate, _ = prepared
    with pytest.raises(ValueError, match="预算不足"):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            runs.reserve_file_in_transaction(db, root, gate.lease_owner, gate.config.lease_epoch, "first", "digest", str(uuid4()), 100)
            runs.reserve_file_in_transaction(db, root, gate.lease_owner, gate.config.lease_epoch, "second", "digest", str(uuid4()), 100)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_file_reservations WHERE root_run_id=?", (root,)).fetchone()[0] == 0


def test_actual_docx_reopens_and_rejects_content_changes(prepared):
    store, workspace, service, _, _, _, _ = prepared
    with store.connect() as db:
        db.execute("BEGIN")
        _, _, documents = service._sources(db, ["simulation-meeting-material"])
    document = Document()
    document.add_heading(documents[0]["title"], 0)
    document.add_paragraph(documents[0]["content"])
    storage_key = str(uuid4()) + ".docx"
    path = workspace / storage_key
    document.save(path)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    assert service._read_verified_bytes(storage_key, len(content), digest) == content
    document.add_paragraph("资料已变化")
    document.save(path)
    with pytest.raises(ValueError, match="摘要"):
        service._read_verified_bytes(storage_key, len(content), digest)


def test_artifact_service_rejects_unbound_and_missing_records(prepared):
    store, _, preparation, _, run_id, _, _ = prepared
    service = ArtifactService(preparation)
    with pytest.raises(ValueError, match="范围证明"):
        service.create(run_id, ["simulation-meeting-material"], "request")
    with pytest.raises(ValueError, match="成果不存在"):
        service.revoke(str(uuid4()), 1)
    with pytest.raises(ValueError, match="成果版本或状态不可发布"):
        service.publish(str(uuid4()), 1)
    with pytest.raises(ValueError, match="成果版本无效"):
        service.publish(str(uuid4()), 0)
    with pytest.raises(ValueError):
        service.read("../business.sqlite")
    with store.connect() as db:
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": "1"})
    with pytest.raises(ValueError, match="来源范围"):
        service.revoke_withdrawn_source("simulation-meeting-material")


def test_closed_artifact_api_rejects_unauthenticated_requests(tmp_path):
    async def exercise():
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=None,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl")
        runner = web.AppRunner(closed_artifact_application(channel))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = "http://127.0.0.1:" + str(runner.addresses[0][1])
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for method, path in (("POST", "/api/v2/artifacts"), ("GET", "/api/v2/runs/unknown/artifacts"), ("GET", "/api/v2/runs/unknown/artifact-pending-requests"), ("GET", "/api/v2/tasks/unknown/artifacts"), ("POST", "/api/v2/tasks/unknown/artifacts"), ("GET", "/api/v2/artifacts/unknown"), ("GET", "/api/v2/artifacts/unknown/file"), ("POST", "/api/v2/artifacts/unknown/export"), ("POST", "/api/v2/artifacts/unknown/revoke")):
                    response = await client.request(method, url + path)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
        finally:
            await runner.cleanup()
    asyncio.run(exercise())


def test_terminal_owner_reader_rejects_unauthenticated_requests(prepared, tmp_path):
    store, workspace, preparation, _, _, _, scope = prepared

    async def exercise():
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=scope.sources.sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        reader = OwnerArtifactReader(channel, scope, workspace)

        async def read(request):
            return web.Response(body=reader.read(request, str(uuid4()), 1))

        async def file_response(request):
            return reader.file_response(request, str(uuid4()), 1)

        async def metadata(request):
            return web.json_response(reader.metadata(request, str(uuid4()), 1))

        async def listing(request):
            return web.json_response(reader.list_for_run(request, str(uuid4())))

        async def receipt(request):
            return web.json_response(reader.request_receipt(request, str(uuid4()), "original-request"))

        async def versions(request):
            return web.json_response(reader.list_versions(request, str(uuid4()), 1))

        async def export(request):
            return web.json_response(reader.export(request, str(uuid4()), 1, "untrusted"))

        async def parsed(request):
            return web.json_response(reader.parsed(request, str(uuid4()), 1))

        async def task_listing(request):
            return web.json_response(reader.list_for_task(request, "historical-1"))

        async def task_binding(request):
            return web.json_response(reader.bind_to_task(request, "historical-1", str(uuid4()), 1, str(uuid4())))

        async def meeting_brief(request):
            tool = HermesMeetingBriefTool(preparation)
            return web.json_response(tool.execute_authenticated(request, channel, {"source_ids": ["simulation-meeting-material"], "request_key": "brief-tool"}))

        app = web.Application()
        app.router.add_get("/artifact", read)
        app.router.add_get("/file", file_response)
        app.router.add_get("/metadata", metadata)
        app.router.add_get("/list", listing)
        app.router.add_get("/receipt", receipt)
        app.router.add_get("/versions", versions)
        app.router.add_post("/export", export)
        app.router.add_get("/parsed", parsed)
        app.router.add_get("/task-list", task_listing)
        app.router.add_post("/task-bind", task_binding)
        app.router.add_post("/meeting-brief", meeting_brief)
        app.router.add_get("/api/v2/artifacts/{artifact_id}", reader.metadata_http)
        app.router.add_get("/api/v2/artifacts/{artifact_id}/file", reader.file_http)
        app.router.add_get("/api/v2/artifacts/{artifact_id}/versions", reader.versions_http)
        app.router.add_get("/api/v2/runs/{run_id}/artifact-requests/{request_key}", reader.receipt_http)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                url = "http://127.0.0.1:" + str(runner.addresses[0][1])
                for method, path in (("GET", "/artifact"), ("GET", "/file"), ("GET", "/metadata"), ("GET", "/list"), ("GET", "/receipt"), ("GET", "/versions"), ("POST", "/export"), ("GET", "/parsed"), ("GET", "/task-list"), ("POST", "/task-bind"), ("POST", "/meeting-brief"), ("GET", "/api/v2/artifacts/unknown?version=1"), ("GET", "/api/v2/artifacts/unknown/file?version=1"), ("GET", "/api/v2/artifacts/unknown/versions?version=1"), ("GET", "/api/v2/runs/unknown/artifact-requests/original-request")):
                    for headers in ({}, {"X-Boss-Role": "BOSS"}):
                        response = await client.request(method, url + path, headers=headers)
                        assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_source_withdrawal_propagation_requires_actual_withdrawal(prepared):
    store, _, _, _, _, _, _ = prepared
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="未撤销"):
            propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material")
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": "1"})
        assert propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material") == []
        assert propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material") == []


@pytest.fixture
def series_prepared(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    populate(store, "2026-10-28T10:00:00+08:00")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    session = sessions.get_or_create("websocket:series-check")
    sessions.save(session, fsync=True)
    scope = RunScopeService(store, sessions, "ui-check")
    sources = ["simulation-meeting-material", "simulation-business-directory"]
    with store.connect() as db:
        context = _context(db)
        pins = []
        for source_id in sources:
            document = store.get(db, "ui-check", "document", source_id)
            pins.append({"source_id": source_id, "version": document["version"], "content_sha256": checksum(document)})
        binding = {key: context[key] for key in ("namespace", "owner_id", "dataset_id", "dataset_version")}
        binding.update({"chat_id": "series-check", "session_id": session.key, "native_session_created_at": session.created_at.isoformat(),
                        "binding_id": "technical-series-binding", "context_version": "1",
                        "source_refs": [{"source_id": pin["source_id"], "version": pin["version"]} for pin in pins], "source_pins": pins})
        store.put(db, "ui-check", "conversation_source_binding", session.key, binding)
    proof = scope.prove("series-check", sources)
    runs = RunStore(store.path)
    run_id = runs.create_run(proof.owner_id, proof.namespace, "technical-series", "technical-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?",
                   ("series-check", "技术成果版本传播", json.dumps(sources), json.dumps(asdict(proof)), run_id))
    lease = runs.acquire_queued_for_execution(run_id, 0, "series-worker", 60)
    runs.configure_file_budget(run_id, "series-worker", lease["epoch"], 3, 500000)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 2)
    gate = EngineEventSink(runs, config, "series-worker")
    workspace = tmp_path / "series-artifacts"
    workspace.mkdir()
    service = ArtifactPreparation(store, workspace, run_gate=gate, scope_service=scope, max_files=3, max_bytes=500000)
    return store, service, run_id


def test_withdrawn_source_revokes_later_series_versions(series_prepared):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="series-v1", format_name="MARKDOWN")
    second = service.create_meeting_brief(run_id, ["simulation-business-directory"], request_key="series-v2", format_name="MARKDOWN",
                                          previous_artifact_id=first["artifact_id"], expected_version=1)
    unrelated = service.create_meeting_brief(run_id, ["simulation-business-directory"], request_key="series-other", format_name="MARKDOWN")
    assert (first["version"], second["version"], unrelated["version"]) == (1, 2, 1)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "simulation-meeting-material")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": document["version"]})
        assert propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material") == [first["artifact_id"], second["artifact_id"]]
        assert propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material") == []
    with store.connect() as db:
        rows = dict(db.execute("SELECT artifact_id,status FROM agent_artifacts").fetchall())
        assert rows == {first["artifact_id"]: "REVOKED", second["artifact_id"]: "REVOKED", unrelated["artifact_id"]: "VERIFIED"}
        expected = sorted([(first["artifact_id"], "SOURCE_WITHDRAWN", "simulation-meeting-material"),
                           (second["artifact_id"], "SOURCE_WITHDRAWN", "simulation-meeting-material")])
        assert db.execute("SELECT artifact_id,reason,source_id FROM agent_artifact_revocations ORDER BY artifact_id").fetchall() == expected


def test_mapped_cross_run_versions_use_original_directories(series_prepared, tmp_path):
    from agent_source_history import AgentSourceHistory
    store, original, first_run = series_prepared
    scope, runs = original.scope_service, original.run_gate.store
    root = tmp_path / "mapped-series"
    root.mkdir()
    mapping = ArtifactWorkspace(root.resolve())
    mapping.create(first_run)
    first_service = ArtifactPreparation.for_run_workspace(store, mapping, run_gate=original.run_gate,
        scope_service=scope, max_files=3, max_bytes=500000)
    first = first_service.create_meeting_brief(first_run, ["simulation-meeting-material"], request_key="mapped-v1", format_name="MARKDOWN")
    selected = ["simulation-meeting-material", "simulation-business-directory"]
    proof = scope.prove("series-check", selected)
    second_run = runs.create_run(proof.owner_id, proof.namespace, "mapped-series-v2", "technical-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?",
                   ("series-check", "技术成果版本传播", json.dumps(selected), json.dumps(asdict(proof)), second_run))
    lease = runs.acquire_queued_for_execution(second_run, 0, "series-worker", 60)
    runs.configure_file_budget(second_run, "series-worker", lease["epoch"], 3, 500000)
    config = EngineRunConfig(second_run, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 2)
    mapping.create(second_run)
    second_service = ArtifactPreparation.for_run_workspace(store, mapping, run_gate=EngineEventSink(runs, config, "series-worker"),
        scope_service=scope, max_files=3, max_bytes=500000)
    second = second_service.create_meeting_brief(second_run, selected, request_key="mapped-v2", format_name="MARKDOWN",
        previous_artifact_id=first["artifact_id"], expected_version=1)
    history = AgentSourceHistory(runs, scope)
    with store.connect() as db:
        db.execute("BEGIN")
        assert history.read_artifact_in_transaction(db, second_run, second["artifact_id"], 2, "simulation-meeting-material", "1")["content"]
    assert second["version"] == 2
    assert read_verified_file(mapping.open(first_run), first["storage_key"], first["size_bytes"], first["sha256"])
    assert read_verified_file(mapping.open(second_run), second["storage_key"], second["size_bytes"], second["sha256"])
    with pytest.raises(FileNotFoundError):
        read_verified_file(mapping.open(second_run), first["storage_key"], first["size_bytes"], first["sha256"])
    with store.connect() as db:
        assert db.execute("SELECT run_id,workspace FROM agent_artifacts WHERE artifact_id IN (?,?) ORDER BY version", (first["artifact_id"], second["artifact_id"])).fetchall() == [(first_run, str(mapping.open(first_run))), (second_run, str(mapping.open(second_run)))]
    bus, web_config = MessageBus(), WebSocketConfig()
    gateway = build_gateway_services(config=web_config, bus=bus, session_manager=scope.sources.sessions,
        static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
        config_path=tmp_path / "config.json", runtime_model_name=None, runtime_surface="webui",
        runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(web_config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
    reader = OwnerArtifactReader.for_workspace_mapping(channel, scope, mapping)
    with store.connect() as db:
        db.execute("BEGIN")
        context = _context(db)
        current_scope = {key: context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")}
        db.row_factory = sqlite3.Row
        records = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id IN (?,?) ORDER BY version", (first["artifact_id"], second["artifact_id"])).fetchall()
        db.row_factory = None
        assert [reader._verify_record(db, record, selected, current_scope, record["version"])[0]["run_id"] for record in records] == [first_run, second_run]
    third_run = runs.create_run(proof.owner_id, proof.namespace, "mapped-series-v3", "technical-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?",
                   ("series-check", "技术成果版本传播", json.dumps(selected), json.dumps(asdict(proof)), third_run))
    third_lease = runs.acquire_queued_for_execution(third_run, 0, "series-worker", 60)
    runs.configure_file_budget(third_run, "series-worker", third_lease["epoch"], 3, 500000)
    third_directory = mapping.create(third_run)
    third_directory.chmod(0o500)
    try:
        process = multiprocessing.get_context("spawn").Process(target=create_with_unwritable_workspace,
            args=(store.path, third_directory, tmp_path / "workspace", tmp_path / "sessions", third_run,
                  third_lease["epoch"], "simulation-business-directory", "mapped-v3", second["artifact_id"], 2, root.resolve()))
        process.start()
        process.join(30)
        assert process.exitcode != 0
    finally:
        third_directory.chmod(0o700)
    with store.connect() as db:
        pending = db.execute("SELECT p.artifact_id,p.content FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id WHERE f.request_key='mapped-v3'").fetchone()
        assert pending is not None and pending[1]
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN")
        with pytest.raises((ValueError, web.HTTPException)):
            history.read_artifact_in_transaction(db, second_run, second["artifact_id"], 2, "simulation-meeting-material", "1")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material") == []
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (b"",)
        assert withdrawn_pending_requests_in_transaction(scope, db, third_run, third_directory)["requests"][0]["status"] == "RECONCILING"


def test_withdrawal_of_one_source_blocks_multisource_artifact_history(series_prepared):
    from agent_source_history import AgentSourceHistory
    store, service, run_id = series_prepared
    source_a = "simulation-meeting-material"
    source_b = "simulation-business-directory"
    combined = service.create_meeting_brief(run_id, [source_a, source_b], request_key="history-multiple-sources", format_name="MARKDOWN")
    separate = service.create_meeting_brief(run_id, [source_a], request_key="history-separate-source", format_name="MARKDOWN")
    history = AgentSourceHistory(service.run_gate.store, service.scope_service)
    with store.connect() as db:
        db.execute("BEGIN")
        before = history.read_artifact_in_transaction(db, run_id, combined["artifact_id"], combined["version"], source_a, "1")
        assert before["source_id"] == source_a and before["content"]
    store.control("ui-check", "withdraw", {"source_id": source_b, "version": "1"})
    with store.connect() as db:
        assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (combined["artifact_id"],)).fetchone() == ("REVOKED",)
        assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (separate["artifact_id"],)).fetchone() == ("VERIFIED",)
        db.execute("BEGIN")
        with pytest.raises((web.HTTPGone, web.HTTPConflict, web.HTTPNotFound, web.HTTPForbidden)):
            history.read_artifact_in_transaction(db, run_id, combined["artifact_id"], combined["version"], source_a, "1")


def test_source_withdrawal_races_actual_artifact_generation(series_prepared):
    store, service, run_id = series_prepared
    barrier = threading.Barrier(2, timeout=10)

    def generate():
        barrier.wait()
        return service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="race-source", format_name="MARKDOWN")

    def withdraw():
        barrier.wait()
        return store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        generated = pool.submit(generate)
        withdrawn = pool.submit(withdraw)
        withdrawn.result(timeout=30)
        error = generated.exception(timeout=30)
        result = None if error is not None else generated.result()
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "simulation-meeting-material")
        assert document["withdrawn"] is True
        assert db.execute("SELECT count(*) FROM agent_artifacts WHERE status IN ('VERIFIED','PUBLISHED')").fetchone() == (0,)
        if result is not None:
            assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (result["artifact_id"],)).fetchone() == ("REVOKED",)
            assert db.execute("SELECT source_id FROM agent_artifact_revocations WHERE artifact_id=?", (result["artifact_id"],)).fetchone() == ("simulation-meeting-material",)
            assert read_verified_file(service.workspace, result["storage_key"], result["size_bytes"], result["sha256"])
        else:
            assert isinstance(error, (ValueError, web.HTTPException))


def test_source_withdrawal_races_multiversion_file_creation(series_prepared):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="race-series-v1", format_name="MARKDOWN")
    second = service.create_meeting_brief(run_id, ["simulation-business-directory"], request_key="race-series-v2", format_name="MARKDOWN", previous_artifact_id=first["artifact_id"], expected_version=1)
    barrier = threading.Barrier(2, timeout=10)

    def generate():
        barrier.wait()
        return service.create_meeting_brief(run_id, ["simulation-business-directory"], request_key="race-series-v3", format_name="MARKDOWN", previous_artifact_id=second["artifact_id"], expected_version=2)

    def withdraw():
        barrier.wait()
        return store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        generated = pool.submit(generate)
        withdrawn = pool.submit(withdraw)
        withdrawn.result(timeout=30)
        error = generated.exception(timeout=30)
        result = None if error is not None else generated.result()
    with store.connect() as db:
        assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id IN (?,?) ORDER BY version", (first["artifact_id"], second["artifact_id"])).fetchall() == [("REVOKED",), ("REVOKED",)]
        assert db.execute("SELECT count(*) FROM agent_artifacts WHERE status IN ('VERIFIED','PUBLISHED')").fetchone() == (0,)
        pending = db.execute("SELECT p.artifact_id,p.content,f.status FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id WHERE f.request_key=?", ("race-series-v3",)).fetchone()
        if pending is not None:
            assert pending[1:] == (b"", "RESERVED")
        if result is not None:
            assert pending is None
            assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (result["artifact_id"],)).fetchone() == ("REVOKED",)
            assert read_verified_file(service.workspace, result["storage_key"], result["size_bytes"], result["sha256"])
        else:
            assert isinstance(error, (ValueError, web.HTTPException))


def create_with_unwritable_workspace(database, workspace, session_workspace, sessions_root, run_id, epoch, source_id="simulation-meeting-material", request_key="pending-withdrawal", previous_artifact_id=None, expected_version=1, mapping_root=None):
    store = ControlStore(database)
    sessions = MemorySessionManager(session_workspace, business_store=store, sessions_root=sessions_root)
    scope = RunScopeService(store, sessions, "ui-check")
    runs = RunStore(database, allow_migration=False)
    config = EngineRunConfig(run_id, epoch, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 2)
    gate = EngineEventSink(runs, config, "series-worker")
    service = (ArtifactPreparation.for_run_workspace(store, ArtifactWorkspace(mapping_root), run_gate=gate, scope_service=scope, max_files=3, max_bytes=500000)
               if mapping_root is not None else ArtifactPreparation(store, workspace, run_gate=gate, scope_service=scope, max_files=3, max_bytes=500000))
    service.create_meeting_brief(run_id, [source_id], request_key=request_key, format_name="MARKDOWN", previous_artifact_id=previous_artifact_id, expected_version=expected_version if previous_artifact_id else None)


def test_withdrawal_reaches_pending_later_version_in_new_run(series_prepared):
    from agent_simulation_recovery import AgentSimulationRecovery
    from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
    from agent_simulation_snapshot import AgentSimulationSnapshot
    store, service, first_run = series_prepared
    first = service.create_meeting_brief(first_run, ["simulation-meeting-material"], request_key="cross-v1", format_name="MARKDOWN")
    second = service.create_meeting_brief(first_run, ["simulation-business-directory"], request_key="cross-v2", format_name="MARKDOWN", previous_artifact_id=first["artifact_id"], expected_version=1)
    scope = service.scope_service
    selected = ["simulation-business-directory"]
    proof = scope.prove("series-check", selected)
    runs = service.run_gate.store
    second_run = runs.create_run(proof.owner_id, proof.namespace, "technical-cross-series", "technical-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("series-check", "技术成果版本传播", json.dumps(selected), json.dumps(asdict(proof)), second_run))
    lease = runs.acquire_queued_for_execution(second_run, 0, "series-worker", 60)
    runs.configure_file_budget(second_run, "series-worker", lease["epoch"], 3, 500000)
    service.workspace.chmod(0o500)
    try:
        process = multiprocessing.get_context("spawn").Process(target=create_with_unwritable_workspace, args=(store.path, service.workspace, service.workspace.parent / "workspace", service.workspace.parent / "sessions", second_run, lease["epoch"], "simulation-business-directory", "cross-v3", second["artifact_id"], 2))
        process.start()
        process.join(30)
        assert process.exitcode != 0
    finally:
        service.workspace.chmod(0o700)
    with store.connect() as db:
        pending = db.execute("SELECT p.artifact_id,p.content FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id WHERE f.request_key=?", ("cross-v3",)).fetchone()
        assert pending is not None and pending[1]
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, service.workspace.parent, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, AgentSimulationRecoveryJournal(snapshots, allow_migration=True))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "cross-pending") ["checkpoint_id"]
    snapshots.create("cross-pending", "cross-pending", checkpoint_id)
    assert recovery.inspect_withdrawal_replay("cross-pending")["affected_pending"] == 0
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": "1"})
        propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material")
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (b"",)
        db.rollback()
    with store.connect() as db:
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (pending[1],)
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    replay = recovery.inspect_withdrawal_replay("cross-pending")
    assert (replay["affected_pending"], replay["affected_pending_with_content"], replay["current_pending_cleared"]) == (1, 1, 1)
    assert replay["restore_state"] == replay["artifact_backup_cleanup"] == "BLOCKED"
    with store.connect() as db:
        assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id IN (?,?) ORDER BY version", (first["artifact_id"], second["artifact_id"])).fetchall() == [("REVOKED",), ("REVOKED",)]
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (b"",)
        assert db.execute("SELECT status FROM agent_file_reservations WHERE artifact_id=?", (pending[0],)).fetchone() == ("RESERVED",)
        db.execute("BEGIN")
        result = withdrawn_pending_requests_in_transaction(scope, db, second_run, service.workspace)
        assert result["requests"] == [{"run_id": second_run, "request_key": "cross-v3", "artifact_id": pending[0], "status": "RECONCILING", "artifact": None}]
        assert withdrawn_pending_requests_in_transaction(scope, db, first_run, service.workspace)["requests"] == []
        with pytest.raises(ValueError):
            withdrawn_pending_requests_in_transaction(scope, db, second_run, service.workspace.parent)


@pytest.mark.parametrize("file_exists", [False, True])
def test_withdrawal_propagates_to_pending_successor(series_prepared, file_exists):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="pending-series-v1", format_name="MARKDOWN")
    unrelated = service.create_meeting_brief(run_id, ["simulation-business-directory"], request_key="pending-series-other", format_name="MARKDOWN")
    service.workspace.chmod(0o500)
    try:
        process = multiprocessing.get_context("spawn").Process(target=create_with_unwritable_workspace, args=(store.path, service.workspace, service.workspace.parent / "workspace", service.workspace.parent / "sessions", run_id, service.run_gate.config.lease_epoch, "simulation-business-directory", "pending-series-v2", first["artifact_id"]))
        process.start()
        process.join(30)
        assert process.exitcode != 0
    finally:
        service.workspace.chmod(0o700)
    with store.connect() as db:
        pending = db.execute("SELECT p.artifact_id,p.content FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id WHERE f.request_key=?", ("pending-series-v2",)).fetchone()
        assert pending is not None and pending[1]
    path = service.workspace / (pending[0] + ".md")
    if file_exists:
        store_exact_file(service.workspace, path.name, pending[1])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": "1"})
        propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material")
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (b"",)
        db.rollback()
    with store.connect() as db:
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (pending[1],)
        assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (first["artifact_id"],)).fetchone() == ("VERIFIED",)
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    with store.connect() as db:
        assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (first["artifact_id"],)).fetchone() == ("REVOKED",)
        assert db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (unrelated["artifact_id"],)).fetchone() == ("VERIFIED",)
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (b"",)
        assert db.execute("SELECT status FROM agent_file_reservations WHERE artifact_id=?", (pending[0],)).fetchone() == ("RESERVED",)
        db.execute("BEGIN")
        result = withdrawn_pending_requests_in_transaction(service.scope_service, db, run_id, service.workspace)
        assert result["requests"] == [{"run_id": run_id, "request_key": "pending-series-v2", "artifact_id": pending[0], "status": "RECONCILING", "artifact": None}]
    assert path.exists() is file_exists
    if file_exists:
        assert path.read_bytes() == pending[1]


@pytest.mark.parametrize("file_exists", [False, True])
def test_withdrawal_after_real_file_failure_preserves_pending_safely(series_prepared, file_exists):
    store, service, run_id = series_prepared
    service.workspace.chmod(0o500)
    try:
        process = multiprocessing.get_context("spawn").Process(target=create_with_unwritable_workspace, args=(store.path, service.workspace, service.workspace.parent / "workspace", service.workspace.parent / "sessions", run_id, service.run_gate.config.lease_epoch))
        process.start()
        process.join(30)
        assert process.exitcode != 0
    finally:
        service.workspace.chmod(0o700)
    with store.connect() as db:
        pending = db.execute("SELECT p.artifact_id,p.content,r.status FROM agent_artifact_pending p JOIN agent_file_reservations r ON r.artifact_id=p.artifact_id").fetchone()
        assert pending is not None and pending[1] and pending[2] == "RESERVED"
    path = service.workspace / (pending[0] + ".md")
    if file_exists:
        store_exact_file(service.workspace, path.name, pending[1])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": "1"})
        propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material")
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (b"",)
        db.rollback()
    with store.connect() as db:
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (pending[1],)
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    with store.connect() as db:
        assert db.execute("SELECT status FROM agent_file_reservations WHERE artifact_id=?", (pending[0],)).fetchone() == ("RESERVED",)
        saved = db.execute("SELECT workspace,format_name,content,sha256 FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone()
        assert saved == (str(service.workspace), "MARKDOWN", b"", hashlib.sha256(b"").hexdigest())
        assert db.execute("SELECT 1 FROM agent_artifact_versions WHERE artifact_id=?", (pending[0],)).fetchone() is not None
        assert db.execute("SELECT 1 FROM agent_artifacts WHERE artifact_id=?", (pending[0],)).fetchone() is None
        db.execute("BEGIN")
        result = withdrawn_pending_receipt_in_transaction(service.scope_service, db, run_id, "pending-withdrawal", service.workspace)
        assert result == {"run_id": run_id, "request_key": "pending-withdrawal", "artifact_id": pending[0], "status": "RECONCILING", "artifact": None}
        assert withdrawn_pending_requests_in_transaction(service.scope_service, db, run_id, service.workspace) == {"run_id": run_id, "requests": [result]}
        assert withdrawn_pending_requests_in_transaction(service.scope_service, db, run_id, service.workspace) == {"run_id": run_id, "requests": [result]}
        with pytest.raises(ValueError):
            withdrawn_pending_receipt_in_transaction(service.scope_service, db, run_id, "other-request", service.workspace)
        with pytest.raises(ValueError):
            withdrawn_pending_requests_in_transaction(service.scope_service, db, str(uuid4()), service.workspace)
        with pytest.raises(ValueError):
            withdrawn_pending_requests_in_transaction(service.scope_service, db, run_id, service.workspace.parent)
        assert db.execute("SELECT status FROM agent_file_reservations WHERE artifact_id=?", (pending[0],)).fetchone() == ("RESERVED",)
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (b"",)
    assert path.exists() is file_exists
    if file_exists:
        assert path.read_bytes() == pending[1]


def test_pending_artifact_withdrawal_changes_simulated_backup(series_prepared):
    from agent_simulation_recovery import AgentSimulationRecovery
    from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
    from agent_simulation_snapshot import AgentSimulationSnapshot
    store, service, run_id = series_prepared
    service.workspace.chmod(0o500)
    try:
        process = multiprocessing.get_context("spawn").Process(target=create_with_unwritable_workspace, args=(store.path, service.workspace, service.workspace.parent / "workspace", service.workspace.parent / "sessions", run_id, service.run_gate.config.lease_epoch))
        process.start()
        process.join(30)
        assert process.exitcode != 0
        unrelated = multiprocessing.get_context("spawn").Process(target=create_with_unwritable_workspace, args=(store.path, service.workspace, service.workspace.parent / "workspace", service.workspace.parent / "sessions", run_id, service.run_gate.config.lease_epoch, "simulation-business-directory", "unrelated-pending"))
        unrelated.start()
        unrelated.join(30)
        assert unrelated.exitcode != 0
    finally:
        service.workspace.chmod(0o700)
    with store.connect() as db:
        pending = db.execute("SELECT p.artifact_id,p.content FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id WHERE f.request_key='pending-withdrawal'").fetchone()
        assert pending is not None and pending[1]
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, service.workspace.parent, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "pending-before-withdrawal")["checkpoint_id"]
    saved = snapshots.create("pending-before-withdrawal", "pending-before-withdrawal", checkpoint_id)
    mapping = ArtifactWorkspace(service.workspace.parent.resolve())
    with pytest.raises(ValueError, match="待登记成果文件尚未核查"):
        recovery.create_artifact_backup("pending-before-withdrawal", mapping, max_age_seconds=300)
    assert not (service.workspace.parent / (saved["snapshot_name"] + ".artifacts")).exists()
    assert recovery.inspect_withdrawal_replay("pending-before-withdrawal")["affected_pending"] == 0
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    delta = recovery.inspect_privacy_delta("pending-before-withdrawal")
    replay = recovery.inspect_withdrawal_replay("pending-before-withdrawal")
    assert (replay["affected_pending"], replay["affected_pending_with_content"], replay["current_pending_cleared"]) == (1, 1, 1)
    assert delta["artifact_state_available"] is True
    assert delta["artifact_state_matches_current"] is False
    assert delta["artifact_changed_records"] >= 1
    assert delta["restore_state"] == "BLOCKED"
    with store.connect() as db:
        assert db.execute("SELECT content FROM agent_artifact_pending WHERE artifact_id=?", (pending[0],)).fetchone() == (b"",)
        assert db.execute("SELECT status FROM agent_file_reservations WHERE artifact_id=?", (pending[0],)).fetchone() == ("RESERVED",)
        assert db.execute("SELECT length(p.content) FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id WHERE f.request_key='unrelated-pending'").fetchone()[0] > 0


def test_recovery_checkpoint_tracks_series_revocation(series_prepared):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="checkpoint-v1", format_name="MARKDOWN")
    service.create_meeting_brief(run_id, ["simulation-business-directory"], request_key="checkpoint-v2", format_name="MARKDOWN",
                                 previous_artifact_id=first["artifact_id"], expected_version=1)
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before = preflight.current_state_in_transaction(db)
        checkpoint_id = checkpoint.capture_in_transaction(db, "series-checkpoint")["checkpoint_id"]
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "simulation-meeting-material")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": document["version"]})
        propagate_withdrawn_source_in_transaction(store, db, "simulation-meeting-material")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        after = preflight.current_state_in_transaction(db)
        assert after["artifact_revocation_count"] == 2
        assert after["state_sha256"] != before["state_sha256"]
        with pytest.raises(ValueError, match="当前状态已经变化"):
            checkpoint.verify_in_transaction(db, "series-checkpoint", checkpoint_id)
