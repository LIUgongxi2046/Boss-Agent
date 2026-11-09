import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from aiohttp import web
from filelock import FileLock
from jsonschema import Draft202012Validator

from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from business import checksum
from hermes_bridge import EngineEventSink
from hermes_tool_names import METHOD_DEPENDENCY_TOOL_NAMES


VERSION = "upgrade2_run_method_selection_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")
RESELECTION_VERSION = "upgrade2_run_method_reselection_001"
RESELECTION_MIGRATION = Path(__file__).parent / "migrations" / (RESELECTION_VERSION + ".sql")
SCHEMA = json.loads((Path(__file__).parent.parent / "specs/agent-runs.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator({"$ref": "#/$defs/method_selection", "$defs": SCHEMA["$defs"]})
RESELECTION_VALIDATOR = Draft202012Validator({"$ref": "#/$defs/method_reselection", "$defs": SCHEMA["$defs"]})


class AgentRunMethodSelection:
    def __init__(self, store, scope, catalog, drafts, *, allow_migration=False):
        if not isinstance(store, RunStore) or not isinstance(scope, RunScopeService) or not isinstance(catalog, BossSkillCatalog) or not isinstance(drafts, BossSkillDrafts):
            raise ValueError("方法选择需要运行、范围和方法服务")
        if drafts.catalog is not catalog or drafts.namespace != scope.namespace or store.path.resolve() != scope.store.path.resolve() or store.path.resolve() != drafts.store.path.resolve():
            raise ValueError("方法选择服务不属于同一数据库或执行空间")
        self.store, self.scope, self.catalog, self.drafts = store, scope, catalog, drafts
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            for version, migration, table in ((VERSION, MIGRATION, "agent_run_method_selections"), (RESELECTION_VERSION, RESELECTION_MIGRATION, "agent_run_method_reselections")):
                if self._migration_state(db, version, migration, table):
                    continue
                if not allow_migration:
                    raise ValueError("运行方法选择迁移尚未安装")
                db.executescript("BEGIN IMMEDIATE;\n" + migration.read_text(encoding="utf-8"))
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (version, hashlib.sha256(migration.read_bytes()).hexdigest()))
                db.commit()

    @staticmethod
    def schema_state(db):
        return AgentRunMethodSelection._migration_state(db, VERSION, MIGRATION, "agent_run_method_selections")

    @staticmethod
    def _migration_state(db, version, migration, table_name):
        row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (version,)).fetchone()
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
        if row is None and table is None:
            return False
        if row is None or table is None or row[0] != hashlib.sha256(migration.read_bytes()).hexdigest():
            raise ValueError("运行方法选择迁移不可核查")
        return True

    @staticmethod
    def reselection_schema_state(db):
        return AgentRunMethodSelection._migration_state(db, RESELECTION_VERSION, RESELECTION_MIGRATION, "agent_run_method_reselections")

    def _current_method(self, db, selection):
        if not VALIDATOR.is_valid(selection):
            raise ValueError("运行方法选择字段无效")
        if self.drafts._pending(db):
            raise web.HTTPConflict(text="方法配置正在变化")
        config = self.drafts._configuration()
        if set(config.agents.defaults.disabled_skills) != set(self.catalog.loader.disabled_skills):
            raise web.HTTPConflict(text="方法运行配置已经变化")
        path, _, _, _ = self.drafts._method(selection["sop_id"])
        if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
            raise web.HTTPConflict(text="方法文件引用不可用")
        _, references = self.catalog.context("BOSS", [selection["sop_id"]])
        method = references[0]
        if {key: method[key] for key in selection} != selection:
            raise web.HTTPConflict(text="所选方法版本或摘要已经变化")
        items, _ = self.catalog._snapshot()
        matching = [item for item in items if item["sop_id"] == method["sop_id"]]
        if len(matching) != 1:
            raise web.HTTPConflict(text="方法依赖不可核查")
        required = set(matching[0]["read_operations"] + matching[0]["command_operations"])
        if not required.issubset(METHOD_DEPENDENCY_TOOL_NAMES):
            raise web.HTTPConflict(text="当前运行方法依赖未全部注册")
        return method

    def create(self, broker, identity, payload, *, request=None, chat_budget=None):
        if broker.store.path.resolve() != self.store.path.resolve() or broker.scope_service is not self.scope:
            raise ValueError("方法选择与运行创建服务不一致")
        broker.require_identity(identity)
        if payload["conversation_id"] not in identity.conversation_ids or not set(payload["selected_refs"]).issubset(identity.source_refs):
            raise web.HTTPForbidden(text="会话或来源不在当前范围")
        selection = payload.get("method_selection")
        with self.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.schema_state(db):
                raise ValueError("运行方法选择迁移尚未安装")
            method = self._current_method(db, selection)
            query_authority = None
            query_binding = None
            if method["sop_id"] == "SOP03":
                from hermes_bi_authority import HermesBIQueryAuthority
                query_authority = HermesBIQueryAuthority(self.scope)
                query_binding = query_authority.prepare(request, identity, payload)
            prior = db.execute("SELECT 1 FROM agent_api_requests WHERE actor_id=? AND space_id=? AND request_key=?", (identity.actor_id, identity.space_id, payload["request_key"])).fetchone()
            receipt = broker._create_in_transaction(db, identity, payload, request=request, chat_budget=chat_budget)
            if query_authority is not None:
                query_authority.save_in_transaction(db, receipt["run_id"], query_binding)
            row = db.execute("SELECT goal,scope_proof FROM agent_runs WHERE run_id=?", (receipt["run_id"],)).fetchone()
            if row is None or row[1] is None:
                raise ValueError("运行目标或来源范围不可核查")
            method_json = json.dumps(method, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            record = (receipt["run_id"], 1, method_json, checksum(method), checksum(row[0]), checksum(json.loads(row[1])))
            existing = db.execute("SELECT run_id,goal_revision,method,method_sha256,goal_sha256,scope_sha256 FROM agent_run_method_selections WHERE run_id=?", (receipt["run_id"],)).fetchone()
            if existing is None:
                if prior is not None:
                    raise ValueError("原运行缺少方法选择记录")
                db.execute("INSERT INTO agent_run_method_selections VALUES (?,?,?,?,?,?)", record)
            elif tuple(existing) != record:
                raise ValueError("原运行方法选择不可核查")
            broker.require_identity(identity)
            return receipt

    @staticmethod
    def _goal_snapshot(db, run_id, goal_revision, *, allow_historical=False):
        run = db.execute("SELECT goal,goal_revision,last_input_seq,scope_proof,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or type(goal_revision) is not int or goal_revision < 1 or goal_revision > run[1] or not allow_historical and run[1] != goal_revision or run[2] != run[1] - 1 or run[3] is None or not 1 <= run[4] <= run[1]:
            raise ValueError("运行目标版本不可核查")
        inputs = db.execute("SELECT input_id,input_seq,goal_revision,request_key,content,applied_event_id FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq", (run_id,)).fetchall()
        if len(inputs) != run[1] - 1:
            raise ValueError("运行目标补充记录不可核查")
        for index, item in enumerate(inputs, 1):
            if item[1] != index or item[2] != index + 1:
                raise ValueError("运行目标补充顺序不可核查")
            events = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND type='INPUT_RECEIVED' AND json_extract(payload,'$.input_id')=?", (run_id, item[0])).fetchall()
            if len(events) != 1 or json.loads(events[0][0]) != {"input_id": item[0], "input_seq": index, "goal_revision": index + 1}:
                raise ValueError("运行目标补充事件不可核查")
            if (item[2] <= run[4]) != (item[5] is not None):
                raise ValueError("运行目标补充采用状态不可核查")
            if item[5] is not None:
                applied = db.execute("SELECT type,payload FROM agent_run_events WHERE run_id=? AND event_id=?", (run_id, item[5])).fetchone()
                if applied is None or applied[0] != "INPUT_APPLIED" or json.loads(applied[1]) != {"input_id": item[0], "input_seq": index, "goal_revision": index + 1}:
                    raise ValueError("运行目标补充采用事件不可核查")
        return {"goal": run[0], "inputs": [list(item[:5]) for item in inputs[:goal_revision - 1]]}, checksum(json.loads(run[3]))

    def reselect(self, broker, identity, run_id, payload, *, request):
        if broker.store.path.resolve() != self.store.path.resolve() or broker.scope_service is not self.scope or broker.method_selection is not self:
            raise ValueError("方法选择与运行服务不一致")
        broker.require_identity(identity)
        if not isinstance(request, web.Request) or not callable(identity.verify):
            raise web.HTTPUnauthorized(text="重新选择方法需要实际本人会话")
        if not RESELECTION_VALIDATOR.is_valid(payload):
            raise web.HTTPBadRequest(text="重新选择方法字段无效")
        run_id = self.store_uuid(run_id)
        with self.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.schema_state(db) or not self.reselection_schema_state(db):
                raise ValueError("运行方法选择迁移尚未安装")
            row = broker.owned(db, identity, run_id)
            broker.require_current_scope(identity, row, db)
            db.row_factory = None
            from agent_run_memory_guard import require_current_run_memory_in_transaction
            require_current_run_memory_in_transaction(db, self.scope.store, run_id)
            revision = payload["expected_goal_revision"]
            if row["status"] not in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"} or row["cancel_requested_at"] is not None or row["goal_revision"] != revision:
                raise web.HTTPConflict(text="运行状态或目标版本已经变化")
            initial = db.execute("SELECT goal_revision,method,method_sha256,goal_sha256,scope_sha256 FROM agent_run_method_selections WHERE run_id=?", (run_id,)).fetchone()
            if initial is None:
                raise web.HTTPConflict(text="运行缺少初始方法选择")
            initial_method = json.loads(initial[1])
            if initial[0] != 1 or not isinstance(initial_method, dict) or set(initial_method) != {"sop_id", "name", "version", "content_sha256"} or not VALIDATOR.is_valid({key: initial_method[key] for key in ("sop_id", "version", "content_sha256")}) or initial[2] != checksum(initial_method) or initial[3] != checksum(row["goal"]) or row["scope_proof"] is None or initial[4] != checksum(json.loads(row["scope_proof"])):
                raise ValueError("初始方法选择不可核查")
            goal, scope_digest = self._goal_snapshot(db, run_id, revision)
            method = self._current_method(db, payload["method_selection"])
            if method["sop_id"] == "SOP03":
                from hermes_bi_authority import HermesBIQueryAuthority
                query_authority = HermesBIQueryAuthority(self.scope)
                query_payload = {"conversation_id": row["conversation_id"], "goal": row["goal"],
                                 "selected_refs": json.loads(row["selected_refs"])}
                query_binding = query_authority.prepare(request, identity, query_payload, goal_snapshot=goal)
                query_authority.save_in_transaction(db, run_id, query_binding, goal_snapshot=goal)
            digest = checksum({"run_id": run_id, **payload})
            existing = db.execute("SELECT goal_revision,request_digest,input_id,method,method_sha256,goal_sha256,scope_sha256 FROM agent_run_method_reselections WHERE run_id=? AND request_key=?", (run_id, payload["request_key"])).fetchone()
            method_json = json.dumps(method, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            expected = (revision, digest, goal["inputs"][-1][0], method_json, checksum(method), checksum(goal), scope_digest)
            if existing is not None:
                if existing != expected:
                    raise web.HTTPConflict(text="方法选择请求内容已经变化")
            else:
                if db.execute("SELECT 1 FROM agent_run_method_reselections WHERE run_id=? AND goal_revision=?", (run_id, revision)).fetchone() is not None:
                    raise web.HTTPConflict(text="当前目标已经选择方法")
                db.execute("INSERT INTO agent_run_method_reselections VALUES (?,?,?,?,?,?,?,?,?)", (run_id, revision, payload["request_key"], digest, goal["inputs"][-1][0], method_json, checksum(method), checksum(goal), scope_digest))
            broker.require_identity(identity)
            return {"run_id": run_id, "goal_revision": revision, "input_id": goal["inputs"][-1][0], "request_key": payload["request_key"], "method_selection": {**method, "goal_revision": revision, "state": "SELECTED"}}

    @staticmethod
    def store_uuid(value):
        from uuid import UUID
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError("运行编号无效")
        return value

    @staticmethod
    def read_in_transaction(db, run_id, goal_revision=None):
        if not db.in_transaction:
            raise ValueError("方法选择读取需要事务")
        if not AgentRunMethodSelection.schema_state(db):
            return None
        run = db.execute("SELECT goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("运行不存在")
        revision = run[0] if goal_revision is None else goal_revision
        if type(revision) is not int or revision < 1 or revision > run[0]:
            raise ValueError("运行目标版本不可核查")
        if revision > 1:
            if not AgentRunMethodSelection.reselection_schema_state(db):
                return None
            record = db.execute("SELECT request_key,request_digest,input_id,method,method_sha256,goal_sha256,scope_sha256 FROM agent_run_method_reselections WHERE run_id=? AND goal_revision=?", (run_id, revision)).fetchone()
            if record is None:
                return None
            goal, scope_digest = AgentRunMethodSelection._goal_snapshot(db, run_id, revision, allow_historical=True)
            method = json.loads(record[3])
            if not isinstance(method, dict) or set(method) != {"sop_id", "name", "version", "content_sha256"} or not isinstance(method["name"], str) or not method["name"].strip() or not VALIDATOR.is_valid({key: method[key] for key in ("sop_id", "version", "content_sha256")}):
                raise ValueError("运行方法选择记录不可核查")
            request = {"expected_goal_revision": revision, "request_key": record[0], "method_selection": {key: method[key] for key in ("sop_id", "version", "content_sha256")}}
            if record[1] != checksum({"run_id": run_id, **request}) or record[2] != goal["inputs"][-1][0] or record[4] != checksum(method) or record[5] != checksum(goal) or record[6] != scope_digest:
                raise ValueError("运行方法目标或范围记录不可核查")
            return {**method, "goal_revision": revision, "state": "SELECTED"}
        row = db.execute("SELECT goal_revision,method,method_sha256,goal_sha256,scope_sha256 FROM agent_run_method_selections WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        method = json.loads(row[1])
        if not isinstance(method, dict) or set(method) != {"sop_id", "name", "version", "content_sha256"} or not isinstance(method["name"], str) or not method["name"].strip() or not VALIDATOR.is_valid({key: method[key] for key in ("sop_id", "version", "content_sha256")}) or row[0] != 1 or checksum(method) != row[2]:
            raise ValueError("运行方法选择记录不可核查")
        run = db.execute("SELECT goal,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[1] is None or checksum(run[0]) != row[3] or checksum(json.loads(run[1])) != row[4]:
            raise ValueError("运行方法目标或范围记录不可核查")
        return {**method, "goal_revision": row[0], "state": "SELECTED"}

    def request_receipt(self, broker, identity, run_id, request_key, *, request):
        if broker.store.path.resolve() != self.store.path.resolve() or broker.scope_service is not self.scope or broker.method_selection is not self:
            raise ValueError("方法选择与运行服务不一致")
        broker.require_identity(identity)
        if not isinstance(request, web.Request) or not callable(identity.verify):
            raise web.HTTPUnauthorized(text="方法选择回执需要实际本人会话")
        self.store_uuid(run_id)
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise web.HTTPBadRequest(text="方法选择请求编号无效")
        with self.store.connect() as db:
            db.execute("BEGIN")
            run = broker.owned(db, identity, run_id)
            broker.require_current_scope(identity, run, db)
            db.row_factory = None
            from agent_run_memory_guard import require_current_run_memory_in_transaction
            require_current_run_memory_in_transaction(db, self.scope.store, run_id)
            if not self.reselection_schema_state(db):
                raise ValueError("运行方法选择迁移尚未安装")
            row = db.execute("SELECT goal_revision,input_id FROM agent_run_method_reselections WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
            if row is None:
                raise web.HTTPNotFound(text="方法选择原请求不存在")
            selected = self.read_in_transaction(db, run_id, row[0])
            if selected is None:
                raise ValueError("方法选择原请求不可核查")
            broker.require_identity(identity)
            return {"run_id": run_id, "goal_revision": row[0], "input_id": row[1], "request_key": request_key, "method_selection": selected}

    def require_current(self, sink):
        if not isinstance(sink, EngineEventSink) or sink.store.path.resolve() != self.store.path.resolve():
            raise ValueError("方法选择需要同一运行租约")
        with self.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._require_current_in_transaction(db, sink)

    def _require_current_in_transaction(self, db, sink):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve() or not isinstance(sink, EngineEventSink) or sink.store.path.resolve() != self.store.path.resolve():
            raise ValueError("方法选择需要同一运行事务与租约")
        self.store._require_lease(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)
        self.store.require_active_lineage(db, sink.config.run_id)
        row = db.execute("SELECT status,cancel_requested_at,goal_revision,applied_goal_revision,conversation_id,selected_refs,scope_proof,actor_id,space_id FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        if row is None or row[0] != "RUNNING" or row[1] is not None or type(row[2]) is not int or type(row[3]) is not int or not 1 <= row[3] <= row[2]:
            raise ValueError("运行目标或状态不可核查")
        if row[2] != row[3]:
            inputs = db.execute("SELECT input_seq,goal_revision,applied_event_id FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq", (sink.config.run_id,)).fetchall()
            if len(inputs) != row[2] - 1 or any(item[0] != index or item[1] != index + 1 or (item[2] is None) != (item[1] > row[3]) for index, item in enumerate(inputs, 1)):
                raise ValueError("运行补充目标不可核查")
        saved = self.read_in_transaction(db, sink.config.run_id)
        if saved is None or saved["goal_revision"] != row[2]:
            raise ValueError("当前目标缺少明确方法选择")
        proof = self.scope.prove_in_transaction(db, row[4], json.loads(row[5]))
        if json.loads(json.dumps(asdict(proof))) != json.loads(row[6]) or (proof.owner_id, proof.namespace) != row[7:9]:
            raise ValueError("运行来源范围已经变化")
        method = self._current_method(db, {key: saved[key] for key in ("sop_id", "version", "content_sha256")})
        if method != {key: saved[key] for key in ("sop_id", "name", "version", "content_sha256")}:
            raise ValueError("运行方法版本已经变化")
        return saved

    def can_reselect_in_transaction(self, db, run, identity):
        if not db.in_transaction or not callable(identity.verify) or run["goal_revision"] < 2 or run["status"] not in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"} or run["cancel_requested_at"] is not None:
            return False
        if not self.schema_state(db) or not self.reselection_schema_state(db) or self.read_in_transaction(db, run["run_id"], 1) is None or self.read_in_transaction(db, run["run_id"]) is not None:
            return False
        self._goal_snapshot(db, run["run_id"], run["goal_revision"])
        if self.drafts._pending(db):
            return False
        config = self.drafts._configuration()
        if set(config.agents.defaults.disabled_skills) != set(self.catalog.loader.disabled_skills):
            raise ValueError("方法运行配置已经变化")
        items, _ = self.catalog._snapshot()
        for item in items:
            required = set(item["read_operations"] + item["command_operations"])
            if item["context_eligible"] and required.issubset(METHOD_DEPENDENCY_TOOL_NAMES):
                selection = {key: item[key] for key in ("sop_id", "version", "content_sha256")}
                self._current_method(db, selection)
                return True
        return False

    def catalog_in_transaction(self, db):
        if not db.in_transaction or self.drafts._pending(db):
            raise web.HTTPConflict(text="方法配置不可核查")
        config = self.drafts._configuration()
        if set(config.agents.defaults.disabled_skills) != set(self.catalog.loader.disabled_skills):
            raise web.HTTPConflict(text="方法运行配置已经变化")
        items, _ = self.catalog._snapshot()
        result = []
        for item in items:
            path, _, _, _ = self.drafts._method(item["sop_id"])
            if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
                raise web.HTTPConflict(text="方法文件引用不可用")
            required = set(item["read_operations"] + item["command_operations"])
            runtime_missing = sorted(required - METHOD_DEPENDENCY_TOOL_NAMES)
            native_missing = sorted(item["missing_tools"])
            projections = sorted(item["missing_projections"])
            reasons = []
            if not item["enabled"]:
                reasons.append("DISABLED")
            if not item["native_available"]:
                reasons.append("METHOD_UNAVAILABLE")
            if native_missing:
                reasons.append("NATIVE_TOOLS_MISSING")
            if runtime_missing:
                reasons.append("RUNTIME_TOOLS_MISSING")
            if projections:
                reasons.append("PROJECTIONS_MISSING")
            result.append({**{key: item[key] for key in ("sop_id", "name", "version", "content_sha256")},
                           "status": "UNAVAILABLE" if reasons else "AVAILABLE", "reasons": reasons,
                           "missing_native_tools": native_missing, "missing_runtime_tools": runtime_missing,
                           "missing_projections": projections})
        return result

    def catalog_for_run(self, broker, identity, run_id, *, request):
        if broker.store.path.resolve() != self.store.path.resolve() or broker.scope_service is not self.scope or broker.method_selection is not self:
            raise ValueError("方法目录与运行服务不一致")
        broker.require_identity(identity)
        if not isinstance(request, web.Request) or not callable(identity.verify):
            raise web.HTTPUnauthorized(text="方法目录需要实际本人会话")
        self.store_uuid(run_id)
        with self.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN")
            run = broker.owned(db, identity, run_id)
            broker.require_current_scope(identity, run, db)
            db.row_factory = None
            from agent_run_memory_guard import require_current_run_memory_in_transaction
            require_current_run_memory_in_transaction(db, self.scope.store, run_id)
            methods = self.catalog_in_transaction(db)
            allowed = self.can_reselect_in_transaction(db, run, identity)
            broker.require_identity(identity)
            return {"run_id": run_id, "goal_revision": run["goal_revision"], "selection_allowed": allowed, "methods": methods}
