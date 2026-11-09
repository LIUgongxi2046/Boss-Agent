import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource

from agent_legacy_inventory import AgentLegacyInventory
from agent_legacy_run_link import AgentLegacyRunLink, MIGRATION as LINK_MIGRATION, VERSION as LINK_VERSION
from agent_run_broker import fail
from boss_simulation_api import _context


LEGACY_PARAMS = web.RequestKey("hermes_legacy_params", dict)


def load_legacy_inventory(scope):
    with scope.store.connect() as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_legacy_run_links'").fetchone()
        version = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (LINK_VERSION,)).fetchone()
        if table is None and version is None:
            return None
        if table is None or version != (hashlib.sha256(LINK_MIGRATION.read_bytes()).hexdigest(),):
            raise ValueError("历史关联迁移不可核查")
    return AgentLegacyInventory(scope.store, scope)


def verify_legacy_link_in_transaction(db, inventory, run_id, proof):
    table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_legacy_run_links'").fetchone()
    if table is None:
        if inventory is not None or db.execute("SELECT 1 FROM agent_schema_migrations WHERE version=?", (LINK_VERSION,)).fetchone() is not None:
            raise ValueError("历史关联迁移不可核查")
        return None
    if inventory is None or db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (LINK_VERSION,)).fetchone() != (hashlib.sha256(LINK_MIGRATION.read_bytes()).hexdigest(),):
        raise ValueError("历史关联迁移不可核查")
    link = db.execute("SELECT namespace,record_type,session_id,source_digest FROM agent_legacy_run_links WHERE run_id=?", (run_id,)).fetchone()
    if link is None:
        return None
    context = _context(db)
    run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None or run[:3] != (proof.owner_id, proof.namespace, proof.chat_id) or run[3] is None or run[4] is None or json.loads(run[4]) != json.loads(json.dumps(asdict(proof), ensure_ascii=False)):
        raise ValueError("历史运行范围不可核查")
    if link[:3] != (context["namespace"], "SESSION", proof.session_id):
        raise ValueError("历史关联身份已经变化")
    if inventory.scope.sources._running(db, context, {"session_id": proof.session_id}):
        raise ValueError("历史会话仍有未完成的旧运行")
    receipt = db.execute("SELECT receipt FROM agent_api_requests WHERE actor_id=? AND space_id=? AND run_id=? AND operation='create'", (proof.owner_id, proof.namespace, run_id)).fetchall()
    if len(receipt) != 1 or json.loads(receipt[0][0]).get("run_id") != run_id:
        raise ValueError("原运行创建回执不可核查")
    if db.execute("SELECT 1 FROM agent_legacy_inventory WHERE namespace=? AND record_type='SESSION' AND record_id=?", (link[0], link[2])).fetchone() is None:
        raise ValueError("历史会话清单不可核查")
    current = inventory.session_in_transaction(db, proof.chat_id, json.loads(run[3]))
    if current["source_digest"] != link[3] or current["created"]:
        raise ValueError("历史关联摘要已经变化")
    return {"run_id": run_id, "session_id": link[2], "engine": "nanobot", "source_digest": link[3]}


@contextmanager
def guard_legacy_adoption_in_transaction(db, inventory, scope, run_store, run_id, owner, epoch):
    if not db.in_transaction:
        raise ValueError("历史会话核查需要数据库事务")
    main = db.execute("PRAGMA database_list").fetchone()
    if main is None or main[1] != "main" or not main[2] or scope.store.path.resolve() != run_store.path.resolve():
        raise ValueError("历史会话核查数据库不匹配")
    if scope.store.path.resolve() != Path(main[2]).resolve():
        raise ValueError("历史会话核查数据库不匹配")
    db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
    run_store._require_lease(db, run_id, owner, epoch)
    run_store.require_active_lineage(db, run_id)
    row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None or row[2] is None or row[3] is None or row[4] is None:
        raise ValueError("历史运行范围不可核查")
    sessions = scope.sources.sessions
    if sessions._store is not sessions._jsonl_store:
        raise ValueError("会话存储不支持共同文件锁")
    with sessions.locked_session_files():
        proof = scope.prove_in_transaction(db, row[2], json.loads(row[3]))
        if (proof.owner_id, proof.namespace) != row[:2] or json.loads(row[4]) != json.loads(json.dumps(asdict(proof), ensure_ascii=False)):
            raise ValueError("历史运行范围已经变化")
        link = verify_legacy_link_in_transaction(db, inventory, run_id, proof)
        snapshot = sessions.read_session_snapshot(proof.session_id) if link is not None else None
        if link is not None and (snapshot is None or snapshot.key != proof.session_id):
            raise ValueError("历史会话不可核查")
        yield link, snapshot
        run_store._require_lease(db, run_id, owner, epoch)
        run_store.require_active_lineage(db, run_id)
        if verify_legacy_link_in_transaction(db, inventory, run_id, proof) != link:
            raise ValueError("历史关联已经变化")


def install_legacy_routes(app, channel, scope, broker, *, public_port):
    host = "127.0.0.1:" + str(public_port)
    origin = "http://" + host

    async def link(request):
        channel.require_run_api_role(request)
        if request.query or await request.read():
            raise web.HTTPBadRequest(text="历史关联请求格式无效")
        inventory = load_legacy_inventory(scope)
        if inventory is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "历史会话迁移尚未安装")
        service = AgentLegacyRunLink(inventory, broker)
        return web.json_response(service.link(request, channel, request[LEGACY_PARAMS]["run_id"]), headers={"Cache-Control": "no-store"})

    async def read(request):
        channel.require_run_api_role(request)
        if request.query:
            raise web.HTTPBadRequest(text="历史关联查询格式无效")
        inventory = load_legacy_inventory(scope)
        if inventory is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "历史会话迁移尚未安装")
        run_id = request[LEGACY_PARAMS]["run_id"]
        with broker.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT conversation_id,selected_refs,actor_id,space_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[0] is None or row[1] is None:
                fail(web.HTTPNotFound, "NOT_FOUND", "运行不存在")
            channel.require_run_subscription(request, row[0])
            proof = scope.prove_in_transaction(db, row[0], json.loads(row[1]))
            if (proof.owner_id, proof.namespace) != row[2:]:
                fail(web.HTTPNotFound, "NOT_FOUND", "运行不存在")
            result = verify_legacy_link_in_transaction(db, inventory, run_id, proof)
            channel.require_run_subscription(request, row[0])
            return web.json_response({"run_id": run_id, "link": result}, headers={"Cache-Control": "no-store"})

    resource = DynamicResource("/api/v2/runs/{run_id}/legacy-link")
    resource.add_route("GET", read)
    resource.add_route("POST", link)

    @web.middleware
    async def dispatch(request, handler):
        match, allowed = await resource.resolve(request)
        if match is None:
            if allowed:
                raise web.HTTPMethodNotAllowed(request.method, allowed)
            return await handler(request)
        request_origin = request.headers.get("Origin")
        if request.headers.get("Host") != host or request_origin not in (None, origin) or request.method != "GET" and request_origin != origin or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
            fail(web.HTTPForbidden, "FORBIDDEN", "历史关联请求来源无效")
        request[LEGACY_PARAMS] = dict(match)
        return await match.handler(request)

    app.middlewares.append(dispatch)
