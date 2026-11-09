import hashlib
import json
from pathlib import Path

from aiohttp import web
from filelock import FileLock
from jsonschema import Draft202012Validator

from agent_run_method_selection import AgentRunMethodSelection
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_simulation_api import SimulationAPI
from boss_source_access import require_current_business_source
from business import checksum
from hermes_bridge import EngineEventSink


VERSION = "upgrade2_run_object_scope_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")
INTERFACES = {"task": "SI06", "metric_detail": "SI07", "event": "SI14", "travel_plan": "SI03", "owner_goals_active": "SI01"}
SCHEMA = json.loads((Path(__file__).parent.parent / "specs/agent-runs.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator({"$ref": "#/$defs/object_scope_request", "$defs": SCHEMA["$defs"]})
REFERENCE_VALIDATOR = Draft202012Validator({"$ref": "#/$defs/object_scope_reference", "$defs": SCHEMA["$defs"]})


class AgentRunObjectScope:
    def __init__(self, runs, scope, *, allow_migration=False):
        if not isinstance(runs, RunStore) or not isinstance(scope, RunScopeService) or runs.path.resolve() != scope.store.path.resolve():
            raise ValueError("对象范围与运行数据库不一致")
        self.runs, self.scope, self.simulation = runs, scope, SimulationAPI(scope.store)
        with FileLock(str(runs.path) + ".migration.lock", timeout=10), runs.connect() as db:
            if self.schema_state(db):
                return
            if not allow_migration:
                raise ValueError("运行对象范围迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + MIGRATION.read_text(encoding="utf-8"))
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, hashlib.sha256(MIGRATION.read_bytes()).hexdigest()))

    @staticmethod
    def schema_state(db):
        row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_run_object_scopes'").fetchone()
        if row is None and table is None:
            return False
        if row is None or table is None or row[0] != hashlib.sha256(MIGRATION.read_bytes()).hexdigest():
            raise ValueError("运行对象范围迁移不可核查")
        return True

    def _resolve(self, db, ref, source_proof):
        if not REFERENCE_VALIDATOR.is_valid(ref):
            raise ValueError("运行对象引用无效")
        kind, identifier = ref["entity_type"], ref["object_id"]
        if kind == "meeting_context":
            from agent_run_meeting_scope import meeting_context_in_transaction
            data = meeting_context_in_transaction(self, db, source_proof, identifier)
            if data["meeting"]["version"] != ref["version"] or checksum(data) != ref["sha256"]:
                raise web.HTTPConflict(text="会议范围版本或成员已经变化")
            return {**ref, "source_refs": [{"source_id": item[0], "version": item[1], "sha256": item[2]} for item in sorted(source_proof.source_pins)]}
        projection = self.simulation.project_in_transaction("BOSS", db, {"interface_id": INTERFACES[kind], "object_ids": [kind + ":" + identifier], "filters": {}})
        records = [item for item in projection["records"] if item["entity_type"] == kind and item["object_id"] == identifier]
        if len(records) != 1 or records[0]["data"] is None or records[0]["content_state"] != "STORED_RECORD":
            raise web.HTTPConflict(text="所选业务对象不可读取或需要复核")
        record = records[0]
        if record["version"] != ref["version"] or checksum(record["data"]) != ref["sha256"]:
            raise web.HTTPConflict(text="所选业务对象版本或摘要已经变化")
        sources = self._record_sources(record)
        pins = {item[0]: (item[1], item[2]) for item in source_proof.source_pins}
        checked = []
        for source in sources:
            document = require_current_business_source(self.scope.store, db, source_proof.namespace, source_proof.owner_id, source["source_id"])
            if source["status"] != "VALID" or pins.get(source["source_id"]) != (source["version"], checksum(document)):
                raise web.HTTPForbidden(text="业务对象来源未获当前运行选择或已经变化")
            checked.append({"source_id": source["source_id"], "version": source["version"], "sha256": checksum(document)})
        return {**ref, "source_refs": sorted(checked, key=lambda item: (item["source_id"], item["version"]))}

    @staticmethod
    def _record_sources(record):
        sources = list(record["source_refs"])
        if record["entity_type"] == "travel_plan":
            body = record["data"]
            for details in (body.get("current"), (body.get("pending") or {}).get("details")):
                if details:
                    sources.extend({"source_id": value["source_id"], "version": value["version"], "status": "VALID"} for value in details.get("transport_refs", []))
        return sources

    def candidates_in_transaction(self, db, proof):
        if not db.in_transaction:
            raise ValueError("候选读取需要当前事务")
        pins = {item[0]: item[1] for item in proof.source_pins}
        candidates = []
        for kind, interface in INTERFACES.items():
            projection = self.simulation.project_in_transaction("BOSS", db, {"interface_id": interface, "object_ids": [], "filters": {}})
            for record in projection["records"]:
                if record["entity_type"] != kind or record["content_state"] != "STORED_RECORD" or record["data"] is None:
                    continue
                if any(source["status"] != "VALID" or pins.get(source["source_id"]) != source["version"] for source in self._record_sources(record)):
                    continue
                ref = {"entity_type": kind, "object_id": record["object_id"], "version": record["version"], "sha256": checksum(record["data"])}
                resolved = self._resolve(db, ref, proof)
                candidates.append({**resolved, "data": record["data"]})
        return candidates

    def _owner_run(self, db, broker, identity, run_id, request):
        if broker.store.path.resolve() != self.runs.path.resolve() or broker.scope_service is not self.scope:
            raise ValueError("对象范围与运行服务不一致")
        broker.require_identity(identity)
        if not isinstance(request, web.Request) or not callable(identity.verify):
            raise web.HTTPUnauthorized(text="对象读取需要实际本人会话")
        AgentRunMethodSelection.store_uuid(run_id)
        if not self.schema_state(db):
            raise ValueError("运行对象范围迁移尚未安装")
        run = broker.owned(db, identity, run_id)
        broker.require_current_scope(identity, run, db)
        db.row_factory = None
        from agent_run_memory_guard import require_current_run_memory_in_transaction
        require_current_run_memory_in_transaction(db, self.scope.store, run_id)
        proof = self.scope.prove_in_transaction(db, run["conversation_id"], json.loads(run["selected_refs"]))
        return run, proof

    def candidates(self, broker, identity, run_id, *, request):
        with self.runs.connect() as db:
            db.execute("BEGIN")
            run, proof = self._owner_run(db, broker, identity, run_id, request)
            reasons = self._selection_reasons(db, run)
            result = {"run_id": run_id, "goal_revision": run["goal_revision"], "selection_allowed": not reasons, "unavailable_reasons": reasons, "objects": self.candidates_in_transaction(db, proof)}
            broker.require_identity(identity)
            return result

    def meeting_candidate(self, broker, identity, run_id, meeting_id, *, request):
        from agent_run_meeting_scope import meeting_context_in_transaction
        with self.runs.connect() as db:
            db.execute("BEGIN")
            run, proof = self._owner_run(db, broker, identity, run_id, request)
            data = meeting_context_in_transaction(self, db, proof, meeting_id)
            ref = {"entity_type": "meeting_context", "object_id": meeting_id, "version": data["meeting"]["version"], "sha256": checksum(data)}
            reasons = self._selection_reasons(db, run)
            result = {"run_id": run_id, "goal_revision": run["goal_revision"], "selection_allowed": not reasons, "unavailable_reasons": reasons, "objects": [{**self._resolve(db, ref, proof), "data": data}]}
            broker.require_identity(identity)
            return result

    @staticmethod
    def _selection_reasons(db, run):
        reasons = []
        if run["cancel_requested_at"] is not None:
            reasons.append("RUN_CANCELED")
        if run["status"] not in {"QUEUED", "WAITING_INPUT"}:
            reasons.append("RUN_STATE_UNAVAILABLE")
        if db.execute("SELECT 1 FROM agent_run_object_scopes WHERE run_id=? AND goal_revision=?", (run["run_id"], run["goal_revision"])).fetchone() is not None:
            reasons.append("GOAL_ALREADY_SELECTED")
        return reasons

    def request_receipt(self, broker, identity, run_id, request_key, *, request):
        with self.runs.connect() as db:
            db.execute("BEGIN")
            run, proof = self._owner_run(db, broker, identity, run_id, request)
            result = self._receipt_in_transaction(db, run_id, request_key, proof)
            broker.require_identity(identity)
            return result

    def _receipt_in_transaction(self, db, run_id, request_key, proof):
        row = db.execute("SELECT goal_revision,request_digest,goal_sha256,source_scope_sha256,objects,objects_sha256 FROM agent_run_object_scopes WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if row is None:
            raise web.HTTPNotFound(text="对象选择回执不存在")
        objects = json.loads(row[4])
        refs = [{key: item[key] for key in ("entity_type", "object_id", "version", "sha256")} for item in objects]
        payload = {"expected_goal_revision": row[0], "request_key": request_key, "objects": refs}
        goal, source_digest = AgentRunMethodSelection._goal_snapshot(db, run_id, row[0])
        if not VALIDATOR.is_valid(payload) or checksum(objects) != row[5] or checksum(goal) != row[2] or source_digest != row[3] or row[1] != checksum({"run_id": run_id, **payload}) or [self._resolve(db, ref, proof) for ref in refs] != objects:
            raise web.HTTPConflict(text="对象选择回执或当前资料已经变化")
        return {"run_id": run_id, "goal_revision": row[0], "request_key": request_key, "objects": objects}

    def bind(self, broker, identity, run_id, payload, *, request):
        if not VALIDATOR.is_valid(payload) or len({(item["entity_type"], item["object_id"]) for item in payload["objects"]}) != len(payload["objects"]):
            raise web.HTTPBadRequest(text="对象选择字段无效")
        with self.runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run, proof = self._owner_run(db, broker, identity, run_id, request)
            result = self._bind_in_transaction(db, run, proof, payload)
            broker.require_identity(identity)
            return result

    def _bind_in_transaction(self, db, run, proof, payload):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.runs.path.resolve():
            raise ValueError("对象选择需要同一运行事务")
        run_id, revision = run["run_id"], payload["expected_goal_revision"]
        if run["status"] not in {"QUEUED", "RUNNING", "WAITING_INPUT"} or run["cancel_requested_at"] is not None or run["goal_revision"] != revision:
            raise web.HTTPConflict(text="运行状态或目标版本不可选择对象")
        goal, source_digest = AgentRunMethodSelection._goal_snapshot(db, run_id, revision)
        objects = [self._resolve(db, item, proof) for item in payload["objects"]]
        request_digest = checksum({"run_id": run_id, **payload})
        encoded = json.dumps(objects, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected = (run_id, revision, payload["request_key"], request_digest, checksum(goal), source_digest, encoded, checksum(objects))
        old = db.execute("SELECT run_id,goal_revision,request_key,request_digest,goal_sha256,source_scope_sha256,objects,objects_sha256 FROM agent_run_object_scopes WHERE run_id=? AND (goal_revision=? OR request_key=?)", (run_id, revision, payload["request_key"])).fetchall()
        if old and (len(old) != 1 or old[0] != expected):
            raise web.HTTPConflict(text="对象选择请求或目标版本已经变化")
        if not old:
            if run["status"] == "RUNNING":
                raise web.HTTPConflict(text="运行进行中不能新增对象选择")
            db.execute("INSERT INTO agent_run_object_scopes VALUES (?,?,?,?,?,?,?,?)", expected)
        return {"run_id": run_id, "goal_revision": revision, "request_key": payload["request_key"], "objects": objects}

    def read_in_transaction(self, db, sink, goal_revision):
        main = db.execute("PRAGMA database_list").fetchone()
        if not isinstance(sink, EngineEventSink) or sink.store.path.resolve() != self.runs.path.resolve() or not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.runs.path.resolve() or type(goal_revision) is not int or goal_revision < 1:
            raise ValueError("对象范围读取需要同一运行事务")
        self.runs._require_lease(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)
        self.runs.require_active_lineage(db, sink.config.run_id)
        run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        if run is None or run[5] != "RUNNING" or run[6] is not None or run[7:9] != (goal_revision, goal_revision) or run[3] is None or run[4] is None or not self.schema_state(db):
            raise ValueError("运行对象范围或目标版本不可核查")
        from agent_run_memory_guard import require_current_run_memory_in_transaction
        require_current_run_memory_in_transaction(db, self.scope.store, sink.config.run_id)
        proof = self.scope.prove_in_transaction(db, run[2], json.loads(run[3]))
        from dataclasses import asdict
        if (proof.owner_id, proof.namespace) != run[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(run[4]):
            raise ValueError("运行来源范围已经变化")
        row = db.execute("SELECT request_key,request_digest,goal_sha256,source_scope_sha256,objects,objects_sha256 FROM agent_run_object_scopes WHERE run_id=? AND goal_revision=?", (sink.config.run_id, goal_revision)).fetchone()
        if row is None:
            raise ValueError("当前目标缺少明确对象选择")
        objects = json.loads(row[4])
        goal, source_digest = AgentRunMethodSelection._goal_snapshot(db, sink.config.run_id, goal_revision)
        refs = [{key: item[key] for key in ("entity_type", "object_id", "version", "sha256")} for item in objects]
        request = {"expected_goal_revision": goal_revision, "request_key": row[0], "objects": refs}
        if checksum(objects) != row[5] or checksum(goal) != row[2] or source_digest != row[3] or row[1] != checksum({"run_id": sink.config.run_id, **request}) or [self._resolve(db, ref, proof) for ref in refs] != objects:
            raise ValueError("运行对象选择或当前版本已经变化")
        return {"run_id": sink.config.run_id, "goal_revision": goal_revision, "request_key": row[0], "objects": objects}

    def read_meeting_in_transaction(self, db, sink, goal_revision, meeting_id):
        from agent_run_meeting_scope import meeting_context_in_transaction
        selection = self.read_in_transaction(db, sink, goal_revision)
        matches = [item for item in selection["objects"] if item["entity_type"] == "meeting_context" and item["object_id"] == meeting_id]
        if len(matches) != 1:
            raise ValueError("会议范围缺少本人明确选择")
        run = db.execute("SELECT conversation_id,selected_refs FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        proof = self.scope.prove_in_transaction(db, run[0], json.loads(run[1]))
        data = meeting_context_in_transaction(self, db, proof, meeting_id)
        if checksum(data) != matches[0]["sha256"] or data["meeting"]["version"] != matches[0]["version"]:
            raise ValueError("会议范围或成员已经变化")
        return {"run_id": sink.config.run_id, "goal_revision": goal_revision, "request_key": selection["request_key"], "meeting_context": data}
