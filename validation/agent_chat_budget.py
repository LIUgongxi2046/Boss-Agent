import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from aiohttp import web
from filelock import FileLock

from agent_run_store import RunStore, utc_now
from boss_owner_plans import valid_plan_budget
from business import checksum
from role_channel import RoleChannel, bearer_token
from agent_run_broker import fail


VERSION = "upgrade2_chat_budget_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentChatBudget:
    def __init__(self, store, channel, scope, *, allow_migration=False):
        if not isinstance(store, RunStore) or not isinstance(channel, RoleChannel) or channel.boss_commands is None or channel.boss_commands.store.path.resolve() != store.path.resolve() or scope.store.path.resolve() != store.path.resolve() or channel.gateway.session_manager is not scope.sources.sessions:
            raise ValueError("聊天预算服务环境不一致")
        self.store, self.channel, self.scope = store, channel, scope
        source = MIGRATION.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("聊天预算迁移摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('agent_chat_budget_configs','agent_chat_run_budgets')").fetchone() is not None:
                raise ValueError("聊天预算迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source.decode("utf-8"))
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    @staticmethod
    def require_schema(db):
        row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
        if row != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
            raise ValueError("聊天预算迁移摘要不符")

    def require_maintainer(self, request):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        token = bearer_token(request.headers)
        if not token or not self.channel.gateway.tokens.check_api_token(request) or self.channel.token_roles.get(token) != "MAINTAINER" or time.monotonic() >= self.channel.token_expirations.get(token, 0):
            raise web.HTTPUnauthorized(text="维护身份无效")
        if not self.channel.execution_space_active():
            raise web.HTTPConflict(text="执行空间已经切换")

    def configure(self, request, request_key, expected_version, budget):
        self.require_maintainer(request)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = self._configure_in_transaction(db, request_key, expected_version, budget)
            self.require_maintainer(request)
            return result

    def _configure_in_transaction(self, db, request_key, expected_version, budget):
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200 or request_key.encode("utf-8", errors="replace").decode("utf-8") != request_key or type(expected_version) is not int or expected_version < 0 or not valid_plan_budget(budget):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "聊天预算配置无效")
        encoded = json.dumps(budget, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = checksum(budget)
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("聊天预算配置需要同一数据库事务")
        db.execute("UPDATE agent_chat_budget_configs SET version=version WHERE 0")
        self.require_schema(db)
        old = db.execute("SELECT version,budget,budget_sha256 FROM agent_chat_budget_configs WHERE request_key=?", (request_key,)).fetchone()
        if old is not None:
            if old != (expected_version + 1, encoded, digest):
                fail(web.HTTPConflict, "REQUEST_KEY_CONFLICT", "聊天预算请求内容冲突")
            return {"version": old[0], "budget": budget}
        current = db.execute("SELECT coalesce(max(version),0) FROM agent_chat_budget_configs").fetchone()[0]
        if current != expected_version:
            fail(web.HTTPConflict, "REVISION_CONFLICT", "聊天预算版本已经变化")
        db.execute("INSERT INTO agent_chat_budget_configs VALUES (?,?,?,?,?)", (current + 1, request_key, encoded, digest, utc_now().isoformat()))
        return {"version": current + 1, "budget": budget}

    def read_configuration(self, request):
        self.require_maintainer(request)
        with self.store.connect() as db:
            db.execute("BEGIN")
            result = self._read_configuration_in_transaction(db)
            self.require_maintainer(request)
            return result

    def _read_configuration_in_transaction(self, db):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("聊天预算读取需要同一数据库事务")
        self.require_schema(db)
        row = db.execute("SELECT version,budget,budget_sha256 FROM agent_chat_budget_configs ORDER BY version DESC LIMIT 1").fetchone()
        if row is None:
            return {"version": 0, "budget": None}
        budget = json.loads(row[1])
        if not valid_plan_budget(budget) or checksum(budget) != row[2]:
            raise ValueError("聊天运行预算不可核查")
        return {"version": row[0], "budget": budget}

    def bind_in_transaction(self, db, request, run_id):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("聊天预算绑定需要同一数据库事务")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        self.require_schema(db)
        if db.execute("SELECT 1 FROM agent_api_requests WHERE run_id=? AND operation='create'", (run_id,)).fetchone() is not None:
            raise ValueError("聊天预算必须在运行创建时绑定")
        row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[3] is None or row[4] is None or row[5:] != ("QUEUED", None):
            raise ValueError("排队运行或来源不可核查")
        self.channel.require_run_subscription(request, row[2])
        proof = self.scope.prove_in_transaction(db, row[2], json.loads(row[3]))
        if (proof.owner_id, proof.namespace) != row[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(row[4]):
            raise ValueError("运行来源范围已经变化")
        old = db.execute("SELECT config_version,budget_sha256 FROM agent_chat_run_budgets WHERE run_id=?", (run_id,)).fetchone()
        if old is None:
            config = db.execute("SELECT version,budget,budget_sha256 FROM agent_chat_budget_configs ORDER BY version DESC LIMIT 1").fetchone()
            if config is None:
                raise ValueError("聊天运行预算尚未配置")
            budget = json.loads(config[1])
            if not valid_plan_budget(budget) or checksum(budget) != config[2]:
                raise ValueError("聊天运行预算不可核查")
            db.execute("INSERT INTO agent_chat_run_budgets VALUES (?,?,?,?)", (run_id, config[0], config[2], utc_now().isoformat()))
        else:
            config = db.execute("SELECT version,budget,budget_sha256 FROM agent_chat_budget_configs WHERE version=?", (old[0],)).fetchone()
            if config is None or config[2] != old[1]:
                raise ValueError("原聊天预算不可核查")
            budget = json.loads(config[1])
            if not valid_plan_budget(budget) or checksum(budget) != config[2]:
                raise ValueError("原聊天预算不可核查")
        self.channel.require_run_subscription(request, row[2])
        return {"run_id": run_id, "config_version": config[0], "budget": budget}

    @staticmethod
    def read_in_transaction(db, run_id):
        AgentChatBudget.require_schema(db)
        row = db.execute("SELECT b.config_version,b.budget_sha256,c.budget,c.budget_sha256 FROM agent_chat_run_budgets b JOIN agent_chat_budget_configs c ON c.version=b.config_version WHERE b.run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("聊天运行预算尚未绑定")
        budget = json.loads(row[2])
        if row[1] != row[3] or not valid_plan_budget(budget) or checksum(budget) != row[1]:
            raise ValueError("聊天运行预算不可核查")
        return {"config_version": row[0], "budget": budget}
