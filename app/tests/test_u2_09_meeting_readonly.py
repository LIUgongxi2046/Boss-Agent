import asyncio
import hashlib
import json
import os
import shutil
import socket
from pathlib import Path
from uuid import uuid4

import httpx
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import set_config_path
from nanobot.webui.gateway_services import build_gateway_services

from agent_artifact_formats import FORMATS, create_format, verify_format
from agent_artifacts import read_verified_file
from agent_run_api import product_application
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_meetings import meeting_materials
from boss_memory_sessions import MemorySessionManager
from boss_simulation_api import _context
from boss_source_access import require_current_business_source
from controls import ControlStore
from hermes_intents import install_owner_decision
from role_channel import RoleChannel


def test_meeting_sources_files_and_unauthenticated_intent(tmp_path):
    source = Path(os.environ["BOSS_U2_09_SIMULATION_DB"]).resolve(strict=True)
    target = tmp_path / "business.sqlite"
    shutil.copyfile(source, target)
    set_config_path(tmp_path / "config.json")
    store = ControlStore(target)
    runs = RunStore(target)
    with store.connect() as db:
        db.execute("BEGIN")
        context = _context(db)
        initial = store.get(db, context["namespace"], "initial", "snapshot")
        meeting = meeting_materials(db, initial)["meeting"]
        source_id = "simulation-meeting-material"
        assert initial["source_type"] == "SIMULATED"
        assert source_id in meeting["material_ids"]
        document = require_current_business_source(store, db, context["namespace"], context["owner_id"], source_id)
        assert document["source_type"] == "SIMULATED" and document["version"] == "1"
        minutes = store.get(db, context["namespace"], "minutes", meeting["meeting_id"])
        assert minutes["meeting_id"] == meeting["meeting_id"]
        task_row = db.execute("SELECT id FROM objects WHERE namespace=? AND kind='task' ORDER BY id LIMIT 1", (context["namespace"],)).fetchone()
        assert task_row is not None
        task_id = task_row[0]
        task = store.get(db, context["namespace"], "task", task_id)
        counts_before = dict(db.execute("SELECT kind,count(*) FROM objects GROUP BY kind").fetchall())
        audit_before = db.execute("SELECT count(*) FROM audit").fetchone()[0]
        run_before = db.execute("SELECT count(*) FROM agent_runs").fetchone()[0]
        content_before = hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
    generated = {}
    for format_name, (suffix, _) in FORMATS.items():
        content = create_format(format_name, [document])
        name = str(uuid4()) + suffix
        (tmp_path / name).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        reopened = read_verified_file(tmp_path, name, len(content), digest)
        verify_format(format_name, reopened, [document])
        generated[format_name] = {"bytes": len(content), "sha256": digest}

    async def exercise():
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        scope = RunScopeService(store, sessions, context["namespace"])
        broker = RunBroker(runs, scope_service=scope)
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        app = product_application(channel, broker, public_port=port, upstream_port=9)
        install_owner_decision(app, channel, broker, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                requests = [
                    ("POST", "/api/v2/runs", {"goal": meeting["title"]}),
                    ("GET", "/api/v2/runs/unknown/intent", None),
                    ("POST", "/api/v2/intents/unknown/decision", {}),
                ]
                statuses = {}
                for method, path, payload in requests:
                    response = await client.request(method, origin + path, json=payload, headers={"Origin": origin})
                    assert response.status_code == 401
                    statuses[path] = response.status_code
                return statuses
        finally:
            await runner.cleanup()

    statuses = asyncio.run(exercise())
    reopened_store = ControlStore(target)
    with reopened_store.connect() as db:
        db.execute("BEGIN")
        current = _context(db)
        current_meeting = meeting_materials(db, reopened_store.get(db, current["namespace"], "initial", "snapshot"))["meeting"]
        current_document = require_current_business_source(reopened_store, db, current["namespace"], current["owner_id"], source_id)
        assert current_meeting == meeting and current_document == document
        assert reopened_store.get(db, current["namespace"], "minutes", meeting["meeting_id"]) == minutes
        assert reopened_store.get(db, current["namespace"], "task", task_id) == task
        assert dict(db.execute("SELECT kind,count(*) FROM objects GROUP BY kind").fetchall()) == counts_before
        assert db.execute("SELECT count(*) FROM audit").fetchone()[0] == audit_before
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == run_before
        assert hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest() == content_before
    result = {"dataset": context["dataset_id"], "dataset_version": context["dataset_version"],
        "meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "meeting_title": meeting["title"],
        "source_id": source_id, "source_version": document["version"], "task_id": task_id,
        "task_version": task["version"], "minutes_version": minutes["version"], "generated": generated,
        "http_status": statuses, "business_object_counts_unchanged": True, "audit_count_unchanged": True,
        "run_count_unchanged": True, "database_content_sha256": content_before}
    result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    (tmp_path / "result.json").write_text(result_text, encoding="utf-8")
    print(result_text)
