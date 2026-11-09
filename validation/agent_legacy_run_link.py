import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from aiohttp import web
from filelock import FileLock

from agent_legacy_inventory import AgentLegacyInventory
from agent_run_broker import RunBroker
from agent_run_store import utc_now
from role_channel import RoleChannel


VERSION = "upgrade2_legacy_links_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentLegacyRunLink:
    def __init__(self, inventory, broker, *, allow_migration=False):
        if not isinstance(inventory, AgentLegacyInventory) or not isinstance(broker, RunBroker) or broker.scope_service is not inventory.scope or broker.store.path.resolve() != inventory.store.path.resolve():
            raise ValueError("历史会话与运行服务不匹配")
        self.inventory = inventory
        self.broker = broker
        source = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with FileLock(str(inventory.store.path) + ".migration.lock", timeout=10), inventory.store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("历史运行关联迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_legacy_run_links'").fetchone() is not None:
                raise ValueError("历史运行关联迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def link(self, request, channel, run_id):
        if not isinstance(request, web.Request) or not isinstance(channel, RoleChannel) or channel.boss_commands is None or channel.boss_commands.store.path.resolve() != self.inventory.store.path.resolve():
            raise ValueError("需要同一业务数据库的本人身份服务")
        channel.require_run_api_role(request)
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("运行编号无效")
        with self.inventory.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = self.inventory._require_transaction(db)
            if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
                raise ValueError("历史运行关联迁移摘要不符")
            row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[:2] != (context["owner_id"], context["namespace"]) or row[2] is None or row[3] is None or row[4] is None:
                raise ValueError("运行身份与会话不可核查")
            chat_id, refs = row[2], json.loads(row[3])
            channel.require_run_subscription(request, chat_id)
            proof = self.inventory.scope.prove_in_transaction(db, chat_id, refs)
            if json.loads(row[4]) != json.loads(json.dumps(asdict(proof), ensure_ascii=False)):
                raise ValueError("运行会话或来源范围已经变化")
            if self.inventory.scope.sources._running(db, context, {"session_id": proof.session_id}):
                raise ValueError("历史会话仍有未完成的旧运行")
            original = db.execute("SELECT receipt FROM agent_api_requests WHERE actor_id=? AND space_id=? AND run_id=? AND operation='create'", (context["owner_id"], context["namespace"], run_id)).fetchall()
            if len(original) != 1 or json.loads(original[0][0]).get("run_id") != run_id:
                raise ValueError("原运行创建回执不可核查")
            if db.execute("SELECT 1 FROM agent_legacy_inventory WHERE namespace=? AND record_type='SESSION' AND record_id=?", (context["namespace"], proof.session_id)).fetchone() is None:
                raise ValueError("历史会话尚未登记")
            source = self.inventory.session_in_transaction(db, chat_id, refs)
            expected = (context["namespace"], "SESSION", proof.session_id, source["source_digest"])
            previous = db.execute("SELECT namespace,record_type,session_id,source_digest FROM agent_legacy_run_links WHERE run_id=?", (run_id,)).fetchone()
            if previous is not None and previous != expected:
                raise ValueError("历史运行关联已经变化")
            if previous is None:
                if row[5:] != ("QUEUED", None):
                    raise ValueError("运行已经开始或取消，不能添加历史关联")
                db.execute("INSERT INTO agent_legacy_run_links VALUES (?,?,?,?,?,?)", (run_id, *expected, utc_now().isoformat()))
            channel.require_run_subscription(request, chat_id)
            return {"run_id": run_id, "session_id": proof.session_id, "engine": "nanobot", "source_digest": source["source_digest"], "created": previous is None}
