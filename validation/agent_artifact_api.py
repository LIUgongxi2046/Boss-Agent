import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from agent_artifacts import ArtifactPreparation, artifact_format, read_verified_file
from agent_artifact_formats import FORMATS, parse_format, verify_format
from agent_run_broker import fail
from agent_run_store import utc_now
from agent_run_scope import RunScopeService
from boss_execution_transition import pending_transition
from boss_simulation_api import _context
from boss_source_access import require_current_business_source
from boss_source_policy import source_validity
from business import checksum
from hermes_process_manager import IsolationBoundaryUnavailable
from role_channel import RoleChannel


ARTIFACT_SCHEMA = json.loads((Path(__file__).parent / "agent_artifact_schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(ARTIFACT_SCHEMA)
ARTIFACT_VALIDATORS = {name: Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": ARTIFACT_SCHEMA["$defs"]}, format_checker=FormatChecker()) for name in ("metadata", "list", "task_list", "task_ref", "publication", "meeting_brief_tool_request", "meeting_brief_format_tool_request", "request_receipt", "pending_requests", "version_list")}


def require_related_workspaces(workspace, run_id, prior_workspace, prior_run_id):
    if workspace == prior_workspace:
        return
    from agent_artifact_workspace import ArtifactWorkspace
    current, prior = Path(workspace), Path(prior_workspace)
    if current.parent != prior.parent:
        raise ValueError("成果版本目录根路径不一致")
    mapping = ArtifactWorkspace(current.parent)
    if str(mapping.open(run_id)) != workspace or str(mapping.open(prior_run_id)) != prior_workspace:
        raise ValueError("成果版本目录不可核查")


def artifact_goal_revision_in_transaction(db, record):
    if not db.in_transaction:
        raise ValueError("成果目标版本核查需要当前事务")
    from agent_artifact_goal import AgentArtifactGoal
    recorded_revision = AgentArtifactGoal.read_in_transaction(db, record)
    table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_briefs'").fetchone()
    from agent_artifact_meeting_brief import MIGRATION, VERSION
    migration = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
    if table is None:
        if migration is not None:
            raise ValueError("会议简报迁移不可核查")
        return recorded_revision
    if migration != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
        raise ValueError("会议简报迁移不可核查")
    saved = db.execute("SELECT snapshot,snapshot_sha256 FROM agent_artifact_briefs WHERE artifact_id=?", (record["artifact_id"],)).fetchone()
    if saved is None:
        return recorded_revision
    snapshot = json.loads(saved[0])
    if not isinstance(snapshot, dict):
        raise ValueError("成果目标快照格式不可核查")
    run = db.execute("SELECT goal,goal_revision FROM agent_runs WHERE run_id=?", (record["run_id"],)).fetchone()
    revision = snapshot.get("goal_revision")
    if checksum(snapshot) != saved[1] or snapshot.get("run_id") != record["run_id"] or run is None or snapshot.get("goal") != run[0] or type(revision) is not int or not 1 <= revision <= run[1] or snapshot.get("source_refs") != json.loads(record["source_refs"]):
        raise ValueError("成果目标版本或内容摘要不可核查")
    rows = db.execute("SELECT input_id,input_seq,goal_revision,content,applied_event_id FROM agent_run_inputs WHERE run_id=? AND goal_revision<=? ORDER BY input_seq", (record["run_id"], revision)).fetchall()
    expected = [{"input_id": row[0], "input_seq": row[1], "goal_revision": row[2], "content": row[3], "applied_event_id": row[4]} for row in rows]
    if len(rows) != revision - 1 or snapshot.get("inputs") != expected:
        raise ValueError("成果目标补充记录不可核查")
    last_seq = 0
    for index, row in enumerate(rows, 1):
        event = db.execute("SELECT type,payload,seq FROM agent_run_events WHERE run_id=? AND event_id=?", (record["run_id"], row[4])).fetchone()
        if row[1:3] != (index, index + 1) or event is None or event[0] != "INPUT_APPLIED" or json.loads(event[1]) != {"input_id": row[0], "input_seq": index, "goal_revision": row[2]} or event[2] <= last_seq:
            raise ValueError("成果目标采用事件不可核查")
        last_seq = event[2]
    events = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND type='ARTIFACT_CANDIDATE' AND json_extract(payload,'$.artifact_id')=?", (record["run_id"], record["artifact_id"])).fetchall()
    expected_event = {"artifact_id": record["artifact_id"], "version": record["version"], "media_type": record["media_type"], "sha256": record["sha256"]}
    if len(events) != 1 or events[0][0] <= last_seq or json.loads(events[0][1]) != expected_event:
        raise ValueError("成果目标与成果事件不可核查")
    if recorded_revision is not None and recorded_revision != revision:
        raise ValueError("成果目标记录与快照不一致")
    return revision


def propagate_withdrawn_source_in_transaction(store, db, source_id):
    if not db.in_transaction or not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("来源撤销传播参数无效")
    main = db.execute("PRAGMA database_list").fetchone()
    if main is None or main[1] != "main" or Path(main[2]).resolve() != store.path.resolve():
        raise ValueError("来源撤销传播数据库不匹配")
    context = _context(db)
    if pending_transition(db, context["namespace"]) is not None:
        raise ValueError("当前执行空间正在切换")
    scope = {key: context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")}
    document = store.get(db, scope["namespace"], "document", source_id)
    if document.get("source_id") != source_id or document.get("access_scope") != scope["owner_id"] or document.get("source_type") != "SIMULATED" or source_validity(document, context["clock"]) != "WITHDRAWN":
        raise ValueError("当前来源未撤销或不属于当前空间")
    pending_rows = db.execute("SELECT p.artifact_id,p.content,p.sha256,p.source_refs,p.context,f.status,f.size_bytes,r.selected_refs,r.scope_proof,p.workspace,p.format_name FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE r.actor_id=? AND r.space_id=?", (scope["owner_id"], scope["namespace"])).fetchall()
    for artifact_id, content, digest, raw_refs, raw_scope, status, size, raw_selected, raw_proof, workspace, format_name in pending_rows:
        refs = json.loads(raw_refs)
        if not isinstance(refs, list) or any(not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str) for ref in refs):
            raise ValueError("成果预留来源不可核查")
        if not any(ref["source_id"] == source_id for ref in refs):
            continue
        redacted = content == b"" and digest == hashlib.sha256(b"").hexdigest()
        if json.loads(raw_scope) != scope or status != "RESERVED" or (not redacted and (len(content) != size or hashlib.sha256(content).hexdigest() != digest)) or raw_selected is None or raw_proof is None or format_name not in FORMATS or not isinstance(workspace, str) or not workspace:
            raise ValueError("成果预留状态不可核查")
        selected, proof = json.loads(raw_selected), json.loads(raw_proof)
        if source_id not in selected or any(proof.get(key) != scope[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")) or not any(pin[0] == source_id for pin in proof.get("source_pins", [])) or db.execute("SELECT 1 FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone() is not None:
            raise ValueError("成果预留来源不可核查")
        if not redacted:
            if db.execute("DELETE FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,)).rowcount != 1:
                raise ValueError("成果预留清理不可核查")
            db.execute("INSERT INTO agent_artifact_pending VALUES (?,?,?,?,?,?,?)", (artifact_id, workspace, format_name, b"", hashlib.sha256(b"").hexdigest(), raw_refs, raw_scope))
    rows = db.execute("SELECT a.artifact_id,a.status,a.source_refs,a.context,r.selected_refs,r.scope_proof,v.series_id,v.version,v.previous_artifact_id FROM agent_artifacts a JOIN agent_runs r ON r.run_id=a.run_id JOIN agent_artifact_versions v ON v.artifact_id=a.artifact_id WHERE r.actor_id=? AND r.space_id=? ORDER BY v.series_id,v.version", (scope["owner_id"], scope["namespace"])).fetchall()
    series = {}
    for row in rows:
        series.setdefault(row[6], []).append(row)
    affected = []
    for series_id, records in series.items():
        direct = []
        for record in records:
            artifact_scope = json.loads(record[3])
            refs = json.loads(record[2])
            if artifact_scope != scope:
                if any(ref.get("source_id") == source_id for ref in refs if isinstance(ref, dict)):
                    raise ValueError("关联成果范围不可核查")
                continue
            if not any(isinstance(ref, dict) and ref.get("source_id") == source_id for ref in refs):
                continue
            if record[4] is None or record[5] is None:
                raise ValueError("关联成果范围不可核查")
            selected_refs, saved_proof = json.loads(record[4]), json.loads(record[5])
            if source_id not in selected_refs or any(saved_proof.get(key) != scope[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")) or not any(pin[0] == source_id for pin in saved_proof.get("source_pins", [])):
                raise ValueError("关联成果来源不可核查")
            direct.append(record)
        if not direct:
            continue
        versions = [record[7] for record in records]
        if versions != list(range(1, len(records) + 1)) or any(record[8] != (None if record[7] == 1 else records[record[7] - 2][0]) for record in records):
            raise ValueError("成果版本链不可核查")
        for record in records:
            if record[4] is None or record[5] is None:
                raise ValueError("关联成果范围不可核查")
            saved_proof = json.loads(record[5])
            if any(saved_proof.get(key) != scope[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")):
                raise ValueError("关联成果范围不可核查")
        for record in records[min(item[7] for item in direct) - 1:]:
            artifact_id, status = record[0], record[1]
            if status in {"VERIFIED", "PUBLISHED"}:
                db.execute("UPDATE agent_artifacts SET status='REVOKED' WHERE artifact_id=?", (artifact_id,))
                db.execute("INSERT INTO agent_artifact_revocations VALUES (?, 'SOURCE_WITHDRAWN', ?, ?)", (artifact_id, source_id, utc_now().isoformat()))
                affected.append(artifact_id)
            elif status == "REVOKED":
                revoked = db.execute("SELECT reason,source_id FROM agent_artifact_revocations WHERE artifact_id=?", (artifact_id,)).fetchone()
                if revoked is None:
                    raise ValueError("成果撤销记录不可核查")
            else:
                raise ValueError("关联成果状态不可核查")
    successors = db.execute("SELECT p.artifact_id,p.workspace,p.format_name,p.content,p.sha256,p.source_refs,p.context,f.status,f.size_bytes,r.selected_refs,r.scope_proof,v.series_id,v.version,v.previous_artifact_id,pv.series_id,pv.version,a.context,pr.actor_id,pr.space_id,pr.scope_proof,r.conversation_id,pr.conversation_id,a.workspace,r.run_id,pr.run_id FROM agent_artifact_pending p JOIN agent_file_reservations f ON f.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=f.run_id JOIN agent_artifact_versions v ON v.artifact_id=p.artifact_id JOIN agent_artifact_versions pv ON pv.artifact_id=v.previous_artifact_id JOIN agent_artifacts a ON a.artifact_id=pv.artifact_id JOIN agent_runs pr ON pr.run_id=a.run_id JOIN agent_artifact_revocations x ON x.artifact_id=pv.artifact_id WHERE r.actor_id=? AND r.space_id=? AND x.reason='SOURCE_WITHDRAWN' AND x.source_id=?", (scope["owner_id"], scope["namespace"], source_id)).fetchall()
    for artifact_id, workspace, format_name, content, digest, raw_refs, raw_scope, status, size, raw_selected, raw_proof, series, version, previous, prior_series, prior_version, prior_scope, prior_owner, prior_space, prior_proof, conversation, prior_conversation, prior_workspace, run_id, prior_run_id in successors:
        redacted = content == b"" and digest == hashlib.sha256(b"").hexdigest()
        if status != "RESERVED" or format_name not in FORMATS or not isinstance(workspace, str) or not workspace or json.loads(raw_scope) != scope or json.loads(prior_scope) != scope or (prior_owner, prior_space) != (scope["owner_id"], scope["namespace"]) or conversation != prior_conversation or prior_proof is None or any(json.loads(prior_proof).get(key) != scope[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")) or (not redacted and (len(content) != size or hashlib.sha256(content).hexdigest() != digest)) or raw_selected is None or raw_proof is None or series != prior_series or version != prior_version + 1 or db.execute("SELECT status FROM agent_artifacts WHERE artifact_id=?", (previous,)).fetchone() != ("REVOKED",) or db.execute("SELECT 1 FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone() is not None:
            raise ValueError("成果后续版本预留不可核查")
        require_related_workspaces(workspace, run_id, prior_workspace, prior_run_id)
        selected, proof, refs = json.loads(raw_selected), json.loads(raw_proof), json.loads(raw_refs)
        if not isinstance(selected, list) or any(proof.get(key) != scope[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")) or not isinstance(refs, list) or not refs or any(not isinstance(ref, dict) or ref.get("source_id") not in selected or [ref.get("source_id"), ref.get("revision"), ref.get("sha256")] not in proof.get("source_pins", []) for ref in refs):
            raise ValueError("成果后续版本范围不可核查")
        if not redacted:
            if db.execute("DELETE FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,)).rowcount != 1:
                raise ValueError("成果后续版本清理不可核查")
            db.execute("INSERT INTO agent_artifact_pending VALUES (?,?,?,?,?,?,?)", (artifact_id, workspace, format_name, b"", hashlib.sha256(b"").hexdigest(), raw_refs, raw_scope))
    return affected


def withdrawn_run_session_in_transaction(scope_service, db, run_id):
    main = db.execute("PRAGMA database_list").fetchone()
    if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != scope_service.store.path.resolve():
        raise ValueError("成果待核查状态需要同一数据库事务")
    context = _context(db)
    if context["namespace"] != scope_service.namespace or pending_transition(db, context["namespace"]) is not None:
        raise ValueError("当前执行空间正在切换")
    run = db.execute("SELECT actor_id,space_id,conversation_id,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None or run[:2] != (context["owner_id"], context["namespace"]) or run[3] is None:
        raise ValueError("成果原运行主体不可核查")
    proof = json.loads(run[3])
    scope = {key: context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")}
    session = scope_service.sources._session(db, context, run[2])
    if not isinstance(proof, dict) or any(proof.get(key) != value for key, value in {**scope, **session}.items()):
        raise ValueError("成果原运行会话不可核查")
    return context, scope, session, proof


def withdrawn_pending_receipt_in_transaction(scope_service, db, run_id, request_key, workspace):
    context, scope, session, _ = withdrawn_run_session_in_transaction(scope_service, db, run_id)
    row = db.execute("SELECT r.actor_id,r.space_id,r.conversation_id,r.selected_refs,r.scope_proof,f.artifact_id,f.status,p.workspace,p.format_name,p.content,p.sha256,p.source_refs,p.context FROM agent_runs r JOIN agent_file_reservations f ON f.run_id=r.run_id JOIN agent_artifact_pending p ON p.artifact_id=f.artifact_id WHERE r.run_id=? AND f.request_key=?", (run_id, request_key)).fetchone()
    if row is None or row[0:2] != (context["owner_id"], context["namespace"]) or row[3] is None or row[4] is None or row[6] != "RESERVED" or row[7] != str(workspace) or row[8] not in FORMATS or row[9] != b"" or row[10] != hashlib.sha256(b"").hexdigest():
        raise ValueError("成果待核查状态不可读取")
    selected, proof, refs, saved_scope = json.loads(row[3]), json.loads(row[4]), json.loads(row[11]), json.loads(row[12])
    if saved_scope != scope or any(proof.get(key) != value for key, value in {**scope, **session}.items()) or not isinstance(selected, list) or not isinstance(refs, list) or not refs:
        raise ValueError("成果原运行范围不可核查")
    pins = proof.get("source_pins")
    if not isinstance(pins, list) or any(not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str) or ref["source_id"] not in selected or [ref["source_id"], ref.get("revision"), ref.get("sha256")] not in pins for ref in refs):
        raise ValueError("成果原来源范围不可核查")
    withdrawn = False
    for ref in refs:
        document = scope_service.store.get(db, scope["namespace"], "document", ref["source_id"])
        if document.get("access_scope") != scope["owner_id"] or document.get("source_id") != ref["source_id"]:
            raise ValueError("成果来源主体不可核查")
        withdrawn = withdrawn or source_validity(document, context["clock"]) == "WITHDRAWN"
    lineage = db.execute("SELECT v.series_id,v.version,p.series_id,p.version,a.status,x.source_id,a.context,r.actor_id,r.space_id,r.scope_proof,r.conversation_id,a.workspace,r.run_id FROM agent_artifact_versions v JOIN agent_artifact_versions p ON p.artifact_id=v.previous_artifact_id JOIN agent_artifacts a ON a.artifact_id=p.artifact_id JOIN agent_runs r ON r.run_id=a.run_id JOIN agent_artifact_revocations x ON x.artifact_id=p.artifact_id WHERE v.artifact_id=? AND x.reason='SOURCE_WITHDRAWN'", (row[5],)).fetchone()
    if lineage is not None:
        if lineage[0] != lineage[2] or lineage[1] != lineage[3] + 1 or lineage[4] != "REVOKED" or json.loads(lineage[6]) != scope or lineage[7:9] != (scope["owner_id"], scope["namespace"]) or lineage[10] != row[2] or lineage[9] is None or any(json.loads(lineage[9]).get(key) != scope[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")):
            raise ValueError("成果前一版本撤销状态不可核查")
        require_related_workspaces(row[7], run_id, lineage[11], lineage[12])
        document = scope_service.store.get(db, scope["namespace"], "document", lineage[5])
        if document.get("source_id") != lineage[5] or document.get("access_scope") != scope["owner_id"] or source_validity(document, context["clock"]) != "WITHDRAWN":
            raise ValueError("成果前一版本来源不可核查")
        withdrawn = True
    if not withdrawn or db.execute("SELECT 1 FROM agent_artifacts WHERE artifact_id=?", (row[5],)).fetchone() is not None or db.execute("SELECT 1 FROM agent_artifact_versions WHERE artifact_id=?", (row[5],)).fetchone() is None:
        raise ValueError("成果撤销状态不可核查")
    return {"run_id": run_id, "request_key": request_key, "artifact_id": row[5], "status": "RECONCILING", "artifact": None}


def withdrawn_pending_requests_in_transaction(scope_service, db, run_id, workspace):
    withdrawn_run_session_in_transaction(scope_service, db, run_id)
    rows = db.execute("SELECT f.request_key FROM agent_file_reservations f JOIN agent_artifact_pending p ON p.artifact_id=f.artifact_id WHERE f.run_id=? AND f.status='RESERVED' AND p.content=? AND p.sha256=? ORDER BY f.request_key", (run_id, b"", hashlib.sha256(b"").hexdigest())).fetchall()
    result = {"run_id": run_id, "requests": [withdrawn_pending_receipt_in_transaction(scope_service, db, run_id, row[0], workspace) for row in rows]}
    ARTIFACT_VALIDATORS["pending_requests"].validate(result)
    return result


class OwnerArtifactReader:
    @classmethod
    def for_run_workspace(cls, channel, scope_service, mapping, run_id):
        from agent_artifact_workspace import ArtifactWorkspace
        if not isinstance(mapping, ArtifactWorkspace):
            raise ValueError("需要成果目录映射")
        reader = cls(channel, scope_service, mapping.open(run_id))
        reader.run_id = run_id
        reader.mapping = mapping
        return reader

    def __init__(self, channel, scope_service, workspace):
        if not isinstance(channel, RoleChannel) or not isinstance(scope_service, RunScopeService):
            raise ValueError("需要产品身份和会话范围服务")
        if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != scope_service.store.path.resolve() or channel.gateway.session_manager is not scope_service.sources.sessions:
            raise ValueError("身份与资料服务不属于同一环境")
        path = Path(workspace)
        if path.is_symlink() or not path.is_dir():
            raise ValueError("成果工作区必须是已存在的目录")
        self.channel, self.scope_service, self.workspace = channel, scope_service, path.resolve(strict=True)
        self.run_id = None
        self.mapping = None

    @classmethod
    def for_workspace_mapping(cls, channel, scope_service, mapping):
        from agent_artifact_workspace import ArtifactWorkspace
        if not isinstance(mapping, ArtifactWorkspace):
            raise ValueError("需要成果目录映射")
        reader = cls(channel, scope_service, mapping.root)
        reader.mapping = mapping
        return reader

    def _workspace_for(self, run_id):
        if self.mapping is None:
            return self.workspace
        if self.run_id is not None and self.run_id != run_id:
            raise ValueError("成果运行与目录不符")
        return self.mapping.open(run_id)

    def _verify_run(self, db, request, run_id):
        if self.run_id is not None and run_id != self.run_id:
            raise ValueError("成果运行与目录不符")
        row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[3] is None or row[4] is None or row[5] not in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING", "SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"}:
            raise ValueError("运行不存在或资料范围无效")
        self.channel.require_run_subscription(request, row[2])
        context = _context(db)
        if pending_transition(db, context["namespace"]) is not None or row[:2] != (context["owner_id"], context["namespace"]):
            raise ValueError("运行不属于当前主体或空间")
        selected, saved_proof = json.loads(row[3]), json.loads(row[4])
        proof = self.scope_service.prove_in_transaction(db, row[2], selected)
        fields = ("owner_id", "namespace", "dataset_id", "dataset_version", "chat_id", "session_id", "native_session_created_at")
        if any(getattr(proof, key) != saved_proof.get(key) for key in fields):
            raise ValueError("会话资料范围已经变化")
        scope = {key: context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")}
        return row[2], selected, scope

    def _verify_record(self, db, record, selected, scope, expected_version, *, require_current_source=False):
        if record is None or record["workspace"] != str(self._workspace_for(record["run_id"])) or record["status"] not in {"VERIFIED", "PUBLISHED"} or record["verification_status"] != "VERIFIED":
            raise ValueError("成果不存在或不可读取")
        if record["media_type"] != FORMATS[artifact_format(record["storage_key"])][1]:
            raise ValueError("成果媒体类型不符")
        if record["version"] != expected_version:
            raise ValueError("成果版本已经变化")
        lineage = db.execute("SELECT series_id,version,previous_artifact_id FROM agent_artifact_versions WHERE artifact_id=?", (record["artifact_id"],)).fetchone()
        if lineage is None or lineage[1] != record["version"]:
            raise ValueError("成果版本关系不可核查")
        if record["status"] == "PUBLISHED":
            publication = db.execute("SELECT run_id,version,sha256,actor_id FROM agent_artifact_publications WHERE artifact_id=?", (record["artifact_id"],)).fetchone()
            if publication != (record["run_id"], record["version"], record["sha256"], scope["owner_id"]):
                raise ValueError("成果发布记录不可核查")
        refs = json.loads(record["source_refs"])
        if json.loads(record["context"]) != scope or not {ref["source_id"] for ref in refs}.issubset(selected):
            raise ValueError("成果来源范围已经变化")
        run = db.execute("SELECT scope_proof FROM agent_runs WHERE run_id=?", (record["run_id"],)).fetchone()
        if run is None or run[0] is None:
            raise ValueError("成果原运行范围不可核查")
        pins = json.loads(run[0]).get("source_pins", [])
        from agent_memory_deletion_log import require_memory_deletion_propagation_in_transaction
        require_memory_deletion_propagation_in_transaction(self.scope_service.store, db, scope["namespace"])
        if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (scope["namespace"], record["run_id"])).fetchone() is not None:
            raise ValueError("运行记忆引用已经失效")
        for ref in refs:
            if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_source_cleanup' AND id=?", (scope["namespace"], ref["source_id"])).fetchone() is not None:
                raise ValueError("成果来源撤销或清理已经开始")
            document = require_current_business_source(self.scope_service.store, db, scope["namespace"], scope["owner_id"], ref["source_id"])
            matches = [pin for pin in pins if len(pin) == 3 and pin[0] == ref["source_id"] and pin[1] == ref["revision"] and pin[2] == ref["sha256"]]
            if len(matches) != 1 or (document["version"] == ref["revision"] and checksum(document) != ref["sha256"]):
                raise ValueError("成果原来源版本不可核查")
            if require_current_source and document["version"] != ref["revision"]:
                raise ValueError("成果来源版本已经变化")
        content = read_verified_file(self._workspace_for(record["run_id"]), record["storage_key"], record["size_bytes"], record["sha256"])
        metadata = {key: record[key] for key in ("artifact_id", "run_id", "version", "media_type", "sha256", "size_bytes", "verification_status", "status")}
        metadata["series_id"], _, metadata["previous_artifact_id"] = lineage
        metadata["source_refs"] = refs
        metadata["goal_revision"] = artifact_goal_revision_in_transaction(db, record)
        ARTIFACT_VALIDATORS["metadata"].validate(metadata)
        return metadata, content

    def _access(self, request, artifact_id, expected_version):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        ArtifactPreparation._uuid(artifact_id)
        if type(expected_version) is not int or expected_version <= 0:
            raise ValueError("成果版本无效")
        with self.scope_service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT run_id FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if row is None:
                raise ValueError("成果不存在或不可读取")
            chat_id, selected, scope = self._verify_run(db, request, row[0])
            db.row_factory = sqlite3.Row
            record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=? AND run_id=?", (artifact_id, row[0])).fetchone()
            db.row_factory = None
            result = self._verify_record(db, record, selected, scope, expected_version)
            self.channel.require_run_subscription(request, chat_id)
            return (*result, chat_id)

    def read(self, request, artifact_id, expected_version):
        return self._access(request, artifact_id, expected_version)[1]

    def file_response(self, request, artifact_id, expected_version):
        metadata, content, _ = self._access(request, artifact_id, expected_version)
        return web.Response(body=content, content_type=metadata["media_type"], headers={
            "ETag": '"' + metadata["sha256"] + '"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        })

    def metadata(self, request, artifact_id, expected_version):
        return self._access(request, artifact_id, expected_version)[0]

    def _http_arguments(self, request):
        self.channel.require_run_api_role(request)
        versions = request.query.getall("version", [])
        if len(request.query) != 1 or len(versions) != 1 or not versions[0].isascii() or not versions[0].isdigit() or len(versions[0]) > 16:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "需要有效的成果版本")
        version = int(versions[0])
        if version < 1 or version > 9007199254740991 or str(version) != versions[0]:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "需要有效的成果版本")
        return request.match_info["artifact_id"], version

    async def metadata_http(self, request):
        artifact_id, version = self._http_arguments(request)
        return web.json_response(self.metadata(request, artifact_id, version), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def file_http(self, request):
        artifact_id, version = self._http_arguments(request)
        return self.file_response(request, artifact_id, version)

    async def versions_http(self, request):
        artifact_id, version = self._http_arguments(request)
        return web.json_response(self.list_versions(request, artifact_id, version), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def receipt_http(self, request):
        self.channel.require_run_api_role(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "原请求查询参数无效")
        result = self.request_receipt(request, request.match_info["run_id"], request.match_info["request_key"])
        return web.json_response(result, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    def parsed(self, request, artifact_id, expected_version):
        metadata, content, _ = self._access(request, artifact_id, expected_version)
        format_name = next(name for name, (_, media_type) in FORMATS.items() if media_type == metadata["media_type"])
        parsed = parse_format(format_name, content)
        latest, current_content, _ = self._access(request, artifact_id, expected_version)
        if latest != metadata or current_content != content:
            raise ValueError("解析期间成果已经变化")
        return {"metadata": metadata, "content": parsed}

    def list_for_run(self, request, run_id):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        ArtifactPreparation._uuid(run_id)
        with self.scope_service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            chat_id, selected, scope = self._verify_run(db, request, run_id)
            db.row_factory = sqlite3.Row
            records = db.execute("SELECT * FROM agent_artifacts WHERE run_id=? AND workspace=? AND status IN ('VERIFIED','PUBLISHED') ORDER BY artifact_id", (run_id, str(self._workspace_for(run_id)))).fetchall()
            db.row_factory = None
            items = [self._verify_record(db, record, selected, scope, record["version"])[0] for record in records]
            self.channel.require_run_subscription(request, chat_id)
            result = {"run_id": run_id, "artifacts": items}
            ARTIFACT_VALIDATORS["list"].validate(result)
            return result

    def request_receipt(self, request, run_id, request_key):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        ArtifactPreparation._uuid(run_id)
        if self.run_id is not None and run_id != self.run_id:
            raise ValueError("成果运行与目录不符")
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("成果请求编号无效")
        with self.scope_service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("SELECT p.content,p.sha256,r.conversation_id FROM agent_file_reservations f JOIN agent_artifact_pending p ON p.artifact_id=f.artifact_id JOIN agent_runs r ON r.run_id=f.run_id WHERE f.run_id=? AND f.request_key=?", (run_id, request_key)).fetchone()
            if pending is not None and pending[0] == b"" and pending[1] == hashlib.sha256(b"").hexdigest():
                self.channel.require_run_subscription(request, pending[2])
                result = withdrawn_pending_receipt_in_transaction(self.scope_service, db, run_id, request_key, self._workspace_for(run_id))
                self.channel.require_run_subscription(request, pending[2])
                ARTIFACT_VALIDATORS["request_receipt"].validate(result)
                return result
            chat_id, selected, scope = self._verify_run(db, request, run_id)
            row = db.execute("SELECT artifact_id,size_bytes,status FROM agent_file_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
            if row is None:
                raise web.HTTPNotFound(text="成果原请求不存在")
            artifact_id, size, status = row
            artifact = None
            if status == "COMPLETED":
                db.row_factory = sqlite3.Row
                record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=? AND run_id=?", (artifact_id, run_id)).fetchone()
                db.row_factory = None
                if record is None or record["size_bytes"] != size:
                    raise ValueError("成果原请求登记不可核查")
                artifact = self._verify_record(db, record, selected, scope, record["version"])[0]
            elif status == "RESERVED":
                pending = db.execute("SELECT workspace,format_name,content,sha256,source_refs,context FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,)).fetchone()
                link = db.execute("SELECT version FROM agent_artifact_versions WHERE artifact_id=?", (artifact_id,)).fetchone()
                if pending is None or pending[0] != str(self._workspace_for(run_id)) or pending[1] not in FORMATS or len(pending[2]) != size or hashlib.sha256(pending[2]).hexdigest() != pending[3] or json.loads(pending[5]) != scope or link is None:
                    raise ValueError("成果原请求预留不可核查")
                refs = json.loads(pending[4])
                if not refs or not {ref["source_id"] for ref in refs}.issubset(selected):
                    raise ValueError("成果原请求来源不可核查")
                for ref in refs:
                    document = require_current_business_source(self.scope_service.store, db, scope["namespace"], scope["owner_id"], ref["source_id"])
                    if document["version"] != ref["revision"] or checksum(document) != ref["sha256"]:
                        raise ValueError("成果原请求来源已经变化")
                status = "RECONCILING"
            elif status != "RELEASED":
                raise ValueError("成果原请求状态不可核查")
            self.channel.require_run_subscription(request, chat_id)
            result = {"run_id": run_id, "request_key": request_key, "artifact_id": artifact_id, "status": status, "artifact": artifact}
            ARTIFACT_VALIDATORS["request_receipt"].validate(result)
            return result

    def pending_requests(self, request, run_id):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        ArtifactPreparation._uuid(run_id)
        if self.run_id is not None and run_id != self.run_id:
            raise ValueError("成果运行与目录不符")
        with self.scope_service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            _, _, session, _ = withdrawn_run_session_in_transaction(self.scope_service, db, run_id)
            self.channel.require_run_subscription(request, session["chat_id"])
            result = withdrawn_pending_requests_in_transaction(self.scope_service, db, run_id, self._workspace_for(run_id))
            self.channel.require_run_subscription(request, session["chat_id"])
            return result

    def list_versions(self, request, artifact_id, expected_version):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        ArtifactPreparation._uuid(artifact_id)
        if type(expected_version) is not int or expected_version <= 0:
            raise ValueError("成果版本无效")
        with self.scope_service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            anchor = db.execute("SELECT run_id FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if anchor is None:
                raise ValueError("成果不存在或不可读取")
            anchor_chat, anchor_selected, anchor_scope = self._verify_run(db, request, anchor[0])
            db.row_factory = sqlite3.Row
            anchor_record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            db.row_factory = None
            anchor_metadata, _ = self._verify_record(db, anchor_record, anchor_selected, anchor_scope, expected_version)
            series_id = anchor_metadata["series_id"]
            rows = db.execute("SELECT v.artifact_id,v.version,v.previous_artifact_id,a.run_id,a.status,a.workspace,a.context,r.actor_id,r.space_id,r.conversation_id FROM agent_artifact_versions v JOIN agent_artifacts a ON a.artifact_id=v.artifact_id JOIN agent_runs r ON r.run_id=a.run_id WHERE v.series_id=? ORDER BY v.version", (series_id,)).fetchall()
            versions = []
            previous = None
            for identifier, version, predecessor, run_id, status, workspace, raw_scope, owner, space, chat in rows:
                if version != len(versions) + 1 or predecessor != previous or workspace != str(self._workspace_for(run_id)) or json.loads(raw_scope) != anchor_scope or (owner, space, chat) != (anchor_scope["owner_id"], anchor_scope["namespace"], anchor_chat):
                    raise ValueError("成果版本关系或范围不可核查")
                if status == "REVOKED":
                    if db.execute("SELECT 1 FROM agent_artifact_revocations WHERE artifact_id=?", (identifier,)).fetchone() is None:
                        raise ValueError("成果撤销记录不可核查")
                    goal_revision = None
                else:
                    chat_id, selected, scope = self._verify_run(db, request, run_id)
                    db.row_factory = sqlite3.Row
                    record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (identifier,)).fetchone()
                    db.row_factory = None
                    metadata, _ = self._verify_record(db, record, selected, scope, version)
                    goal_revision = metadata["goal_revision"]
                    self.channel.require_run_subscription(request, chat_id)
                versions.append({"artifact_id": identifier, "run_id": run_id, "version": version, "previous_artifact_id": predecessor, "status": status, "goal_revision": goal_revision})
                previous = identifier
            self.channel.require_run_subscription(request, anchor_chat)
            result = {"series_id": series_id, "versions": versions}
            ARTIFACT_VALIDATORS["version_list"].validate(result)
            return result

    def _task_context(self, db, task_id):
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128:
            raise ValueError("任务编号无效")
        present = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('agent_intents','agent_intent_decisions')").fetchone()[0]
        if present != 2:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "任务成果需要已迁移的领域意图与回执")
        context = _context(db)
        if pending_transition(db, context["namespace"]) is not None:
            raise ValueError("当前执行空间正在切换")
        task = self.scope_service.store.get(db, context["namespace"], "task", task_id)
        if task.get("task_id") != task_id or task.get("owner_id") != context["owner_id"]:
            raise ValueError("任务不属于当前主体或空间")
        return context

    def _verify_task_intent(self, db, task_id, intent_id, context):
        rows = db.execute("SELECT i.intent_id,i.run_id,i.actor_id,i.space_id,i.client_request_id,i.authorization_id,i.result_ref,i.preview,d.receipt FROM agent_intents i JOIN agent_intent_decisions d ON d.intent_id=i.intent_id AND d.actor_id=i.actor_id AND d.space_id=i.space_id WHERE i.intent_id=? AND i.actor_id=? AND i.space_id=? AND i.status='SUCCEEDED' AND i.action='boss.supply_quality.coordinate' AND json_extract(d.receipt,'$.status')='SUCCEEDED' AND json_extract(d.receipt,'$.task_id')=?", (intent_id, context["owner_id"], context["namespace"], task_id)).fetchall()
        if len(rows) != 1:
            raise ValueError("任务缺少唯一领域回执")
        intent_id, run_id, actor_id, space_id, request_id, authorization_id, result_ref, raw_preview, raw_receipt = rows[0]
        preview, receipt = json.loads(raw_preview), json.loads(raw_receipt)
        if result_ref != request_id or not authorization_id or receipt.get("intent_id") != intent_id or receipt.get("authorization_id") != authorization_id or receipt.get("result_ref") != request_id:
            raise ValueError("任务成果的原回执不一致")
        verified = self.channel.boss_commands.verify_coordinate_receipt_in_transaction(db, actor_id=actor_id, space_id=space_id, payload={**preview["coordinate_input"], "client_request_id": request_id}, source_refs=preview["source_refs"], authorization_id=authorization_id)
        if verified.get("task_id") != task_id:
            raise ValueError("任务成果与领域回执不一致")
        return run_id

    def bind_to_task(self, request, task_id, artifact_id, expected_version, intent_id):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        ArtifactPreparation._uuid(artifact_id)
        ArtifactPreparation._uuid(intent_id)
        if type(expected_version) is not int or expected_version <= 0:
            raise ValueError("成果版本无效")
        with self.scope_service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = self._task_context(db, task_id)
            run_id = self._verify_task_intent(db, task_id, intent_id, context)
            chat_id, selected, scope = self._verify_run(db, request, run_id)
            db.row_factory = sqlite3.Row
            record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=? AND run_id=?", (artifact_id, run_id)).fetchone()
            db.row_factory = None
            self._verify_record(db, record, selected, scope, expected_version, require_current_source=True)
            existing = db.execute("SELECT run_id,intent_id,artifact_version FROM agent_task_artifact_refs WHERE task_id=? AND artifact_id=?", (task_id, artifact_id)).fetchone()
            if existing is not None and existing != (run_id, intent_id, expected_version):
                raise ValueError("任务成果引用已经变化")
            if existing is None:
                db.execute("INSERT INTO agent_task_artifact_refs VALUES (?,?,?,?,?)", (task_id, artifact_id, run_id, intent_id, expected_version))
            self.channel.require_run_subscription(request, chat_id)
            result = {"task_id": task_id, "artifact_id": artifact_id, "run_id": run_id, "intent_id": intent_id, "artifact_version": expected_version}
            ARTIFACT_VALIDATORS["task_ref"].validate(result)
            return result

    def list_for_task(self, request, task_id):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        with self.scope_service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = self._task_context(db, task_id)
            links = db.execute("SELECT artifact_id,run_id,intent_id,artifact_version FROM agent_task_artifact_refs WHERE task_id=? ORDER BY artifact_id", (task_id,)).fetchall()
            artifacts = []
            for artifact_id, run_id, intent_id, artifact_version in links:
                if self._verify_task_intent(db, task_id, intent_id, context) != run_id:
                    raise ValueError("任务成果引用不一致")
                chat_id, selected, scope = self._verify_run(db, request, run_id)
                db.row_factory = sqlite3.Row
                record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=? AND run_id=?", (artifact_id, run_id)).fetchone()
                db.row_factory = None
                if record is None:
                    raise ValueError("任务成果不存在")
                if record["status"] != "REVOKED":
                    artifacts.append(self._verify_record(db, record, selected, scope, artifact_version)[0])
                self.channel.require_run_subscription(request, chat_id)
            self.channel.require_run_api_role(request)
            result = {"task_id": task_id, "artifacts": artifacts}
            ARTIFACT_VALIDATORS["task_list"].validate(result)
            return result

    def export(self, request, artifact_id, expected_version, destination_ref):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "导出需要本人授权的目标目录")


def require_meeting_brief_boundary():
    raise IsolationBoundaryUnavailable("本人身份与文件隔离尚未通过验证，成果工具不可调用")


class HermesMeetingBriefTool:
    def __init__(self, preparation):
        if not isinstance(preparation, ArtifactPreparation):
            raise ValueError("需要成果范围检查服务")
        self.preparation = preparation

    def execute_authenticated(self, request, channel, payload):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        preparation = self.preparation
        OwnerArtifactReader(channel, preparation.scope_service, preparation.workspace)
        channel.require_run_api_role(request)
        with preparation.store.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT conversation_id FROM agent_runs WHERE run_id=?", (preparation.run_gate.config.run_id,)).fetchone()
            if row is None or not isinstance(row[0], str):
                raise ValueError("运行会话不可核查")
            chat_id = row[0]
        channel.require_run_subscription(request, chat_id)
        result = self._execute_checked_scope(payload)
        channel.require_run_subscription(request, chat_id)
        return result

    def _execute_checked_scope(self, payload):
        schema = "meeting_brief_format_tool_request" if isinstance(payload, dict) and "format_name" in payload else "meeting_brief_tool_request"
        ARTIFACT_VALIDATORS[schema].validate(payload)
        preparation = self.preparation
        source_ids, request_key = payload["source_ids"], payload["request_key"]
        preparation._validate_sources(source_ids)
        if not request_key.strip():
            raise ValueError("成果请求编号无效")
        run_id = preparation.run_gate.config.run_id
        with preparation.store.connect() as db:
            db.execute("BEGIN")
            scope = preparation._current_scope(db)
            preparation._require_run(db, run_id, source_ids, scope)
            preparation._sources(db, source_ids)
            preparation._require_budget(db, run_id)
            preparation._require_run(db, run_id, source_ids, scope)
        require_meeting_brief_boundary()
        record = preparation.create_meeting_brief(run_id, source_ids, request_key=request_key,
            format_name=payload.get("format_name", "DOCX"), previous_artifact_id=payload.get("previous_artifact_id"),
            expected_version=payload.get("expected_version"))
        content = preparation.read_meeting_brief(record["artifact_id"])
        if len(content) != record["size_bytes"] or hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise ValueError("会议简报内容已经变化")
        with preparation.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            scope = preparation._current_scope(db)
            preparation._require_run(db, run_id, source_ids, scope)
            db.row_factory = sqlite3.Row
            current = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=? AND run_id=?", (record["artifact_id"], run_id)).fetchone()
            db.row_factory = None
            keys = ("artifact_id", "run_id", "version", "media_type", "storage_key", "sha256", "size_bytes", "verification_status", "status")
            if current is None or any(current[key] != record[key] for key in keys) or current["workspace"] != str(preparation.workspace) or json.loads(current["source_refs"]) != record["source_refs"] or json.loads(current["context"]) != scope or current["status"] not in {"VERIFIED", "PUBLISHED"}:
                raise ValueError("会议简报登记已经变化")
            current_scope, current_refs, _ = preparation._sources(db, source_ids)
            if current_scope != scope or current_refs != record["source_refs"]:
                raise ValueError("会议简报来源已经变化")
            if preparation._read_verified_bytes(record["storage_key"], record["size_bytes"], record["sha256"]) != content:
                raise ValueError("会议简报内容已经变化")
            lineage = db.execute("SELECT series_id,version,previous_artifact_id FROM agent_artifact_versions WHERE artifact_id=?", (record["artifact_id"],)).fetchone()
            if lineage is None or lineage[1] != record["version"]:
                raise ValueError("会议简报版本不可核查")
            metadata = {key: record[key] for key in ("artifact_id", "run_id", "version", "media_type", "sha256", "size_bytes", "verification_status", "status", "source_refs")}
            metadata["series_id"], _, metadata["previous_artifact_id"] = lineage
            metadata["goal_revision"] = artifact_goal_revision_in_transaction(db, current)
            ARTIFACT_VALIDATORS["metadata"].validate(metadata)
            preparation._require_run(db, run_id, source_ids, scope)
            return metadata


class ArtifactService:
    def __init__(self, preparation):
        if not isinstance(preparation, ArtifactPreparation):
            raise ValueError("需要成果范围检查服务")
        self.preparation = preparation

    def create(self, run_id, source_ids, request_key, format_name="DOCX", previous_artifact_id=None, expected_version=None):
        return self.preparation.create_meeting_brief(run_id, source_ids, request_key=request_key, format_name=format_name, previous_artifact_id=previous_artifact_id, expected_version=expected_version)

    def read(self, artifact_id):
        return self.preparation.read_meeting_brief(artifact_id)

    def release_unwritten(self, run_id, artifact_id, request_key):
        return self.preparation.release_unwritten_reservation(run_id, artifact_id, request_key)

    def publish(self, artifact_id, expected_version):
        preparation = self.preparation
        preparation._uuid(artifact_id)
        if type(expected_version) is not int or expected_version <= 0:
            raise ValueError("成果版本无效")
        with preparation.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.row_factory = sqlite3.Row
            record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            db.row_factory = None
            if record is None or record["workspace"] != str(preparation.workspace) or record["version"] != expected_version or record["status"] not in {"VERIFIED", "PUBLISHED"} or record["verification_status"] != "VERIFIED":
                raise ValueError("成果版本或状态不可发布")
            lineage = db.execute("SELECT version FROM agent_artifact_versions WHERE artifact_id=?", (artifact_id,)).fetchone()
            if lineage != (expected_version,):
                raise ValueError("成果版本关系不可核查")
            format_name = artifact_format(record["storage_key"])
            if record["media_type"] != FORMATS[format_name][1]:
                raise ValueError("成果媒体类型不符")
            refs, expected_scope = json.loads(record["source_refs"]), json.loads(record["context"])
            source_ids = [ref["source_id"] for ref in refs]
            scope = preparation._current_scope(db)
            preparation._require_run(db, record["run_id"], source_ids, scope)
            current_scope, current_refs, documents = preparation._sources(db, source_ids)
            if current_scope != expected_scope or current_refs != refs:
                raise ValueError("成果来源或执行空间已经变化")
            preparation._require_budget(db, record["run_id"])
            root = preparation.run_gate.store.require_active_lineage(db, record["run_id"])
            reservation = db.execute("SELECT root_run_id,run_id,size_bytes,status FROM agent_file_reservations WHERE artifact_id=?", (artifact_id,)).fetchone()
            count, total = db.execute("SELECT count(*),coalesce(sum(size_bytes),0) FROM agent_file_reservations WHERE root_run_id=? AND status IN ('RESERVED','COMPLETED')", (root,)).fetchone()
            if reservation != (root, record["run_id"], record["size_bytes"], "COMPLETED") or count > preparation.max_files or total > preparation.max_bytes:
                raise ValueError("成果文件预算或预留不可核查")
            content = preparation._read_verified_bytes(record["storage_key"], record["size_bytes"], record["sha256"])
            verify_format(format_name, content, documents)
            preparation._require_run(db, record["run_id"], source_ids, scope)
            publication = db.execute("SELECT run_id,version,sha256,actor_id,published_at FROM agent_artifact_publications WHERE artifact_id=?", (artifact_id,)).fetchone()
            expected = (record["run_id"], expected_version, record["sha256"], scope["owner_id"])
            if record["status"] == "PUBLISHED":
                if publication is None or publication[:4] != expected:
                    raise ValueError("成果发布记录不可核查")
                published_at = publication[4]
            else:
                if publication is not None:
                    raise ValueError("成果发布记录不一致")
                published_at = utc_now().isoformat()
                db.execute("INSERT INTO agent_artifact_publications VALUES (?,?,?,?,?,?)", (artifact_id, *expected, published_at))
                changed = db.execute("UPDATE agent_artifacts SET status='PUBLISHED' WHERE artifact_id=? AND version=? AND status='VERIFIED'", (artifact_id, expected_version))
                if changed.rowcount != 1:
                    raise ValueError("成果发布状态已经变化")
            result = {"artifact_id": artifact_id, "run_id": record["run_id"], "version": expected_version, "sha256": record["sha256"], "status": "PUBLISHED", "published_at": published_at}
            ARTIFACT_VALIDATORS["publication"].validate(result)
            return result

    def revoke(self, artifact_id, expected_version):
        preparation = self.preparation
        preparation._uuid(artifact_id)
        if type(expected_version) is not int or expected_version <= 0:
            raise ValueError("成果版本无效")
        with preparation.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.row_factory = sqlite3.Row
            record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if record is None or record["workspace"] != str(preparation.workspace):
                raise ValueError("成果不存在")
            if record["version"] != expected_version:
                raise ValueError("成果版本已经变化")
            refs = json.loads(record["source_refs"])
            expected_scope = json.loads(record["context"])
            db.row_factory = None
            source_ids = [ref["source_id"] for ref in refs]
            scope = preparation._current_scope(db)
            preparation._require_run(db, record["run_id"], source_ids, scope)
            current_scope, current_refs, _ = preparation._sources(db, source_ids)
            if current_scope != expected_scope or current_refs != refs:
                raise ValueError("成果来源或执行空间已经变化")
            preparation._require_budget(db, record["run_id"])
            previous = db.execute("SELECT reason,revoked_at FROM agent_artifact_revocations WHERE artifact_id=?", (artifact_id,)).fetchone()
            if previous is not None:
                if record["status"] != "REVOKED":
                    raise ValueError("成果撤销记录不一致")
                preparation._require_run(db, record["run_id"], source_ids, scope)
                return {"artifact_id": artifact_id, "version": expected_version, "status": "REVOKED", "reason": previous[0], "revoked_at": previous[1]}
            if record["status"] not in {"VERIFIED", "PUBLISHED"} or record["verification_status"] != "VERIFIED":
                raise ValueError("当前成果状态不可撤销")
            revoked_at = utc_now().isoformat()
            db.execute("UPDATE agent_artifacts SET status='REVOKED' WHERE artifact_id=? AND version=?", (artifact_id, expected_version))
            db.execute("INSERT INTO agent_artifact_revocations VALUES (?, 'SERVICE_REQUEST', NULL, ?)", (artifact_id, revoked_at))
            preparation._require_run(db, record["run_id"], source_ids, scope)
            return {"artifact_id": artifact_id, "version": expected_version, "status": "REVOKED", "reason": "SERVICE_REQUEST", "revoked_at": revoked_at}

    def revoke_withdrawn_source(self, source_id):
        preparation, gate = self.preparation, self.preparation.run_gate
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("来源编号无效")
        with preparation.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            scope = preparation._current_scope(db)
            gate.store._require_lease(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch)
            gate.store.require_active_lineage(db, gate.config.run_id)
            row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
            if row is None or row[:2] != (scope["owner_id"], scope["namespace"]) or row[3] is None or row[4] is None:
                raise ValueError("运行主体或来源范围无效")
            selected, proof = json.loads(row[3]), json.loads(row[4])
            if source_id not in selected:
                raise ValueError("来源未包含在运行资料范围")
            context = _context(db)
            session = preparation.scope_service.sources._session(db, context, row[2])
            binding = preparation.scope_service.sources._binding(db, context, session)
            if binding is None or any(proof.get(key) != scope[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")) or any(proof.get(key) != session[key] for key in ("chat_id", "session_id", "native_session_created_at")) or proof.get("binding_id") != binding["binding_id"] or proof.get("context_version") != binding["context_version"]:
                raise ValueError("运行会话范围已经变化")
            pins = [[ref["source_id"], ref["version"], ref["content_sha256"]] for ref in binding["source_pins"] if ref["source_id"] in selected]
            if proof.get("source_pins") != pins:
                raise ValueError("运行来源证明已经变化")
            from agent_artifact_withdrawal import propagate_domain_source_withdrawal_in_transaction
            affected = propagate_domain_source_withdrawal_in_transaction(preparation.store, db, source_id)["affected"]
            gate.store._require_lease(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch)
            gate.store.require_active_lineage(db, gate.config.run_id)
            return affected


def closed_artifact_application(channel):
    async def unavailable(request):
        channel.require_run_api_role(request)
        fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "成果接口需要本人认证和文件隔离核查")

    application = web.Application()
    application.add_routes([web.post("/api/v2/artifacts", unavailable),
                            web.get("/api/v2/runs/{run_id}/artifacts", unavailable),
                            web.get("/api/v2/runs/{run_id}/artifact-pending-requests", unavailable),
                            web.get("/api/v2/runs/{run_id}/artifact-requests/{request_key}", unavailable),
                            web.get("/api/v2/tasks/{task_id}/artifacts", unavailable),
                            web.post("/api/v2/tasks/{task_id}/artifacts", unavailable),
                            web.get("/api/v2/artifacts/{artifact_id}", unavailable),
                            web.get("/api/v2/artifacts/{artifact_id}/file", unavailable),
                            web.get("/api/v2/artifacts/{artifact_id}/versions", unavailable),
                            web.post("/api/v2/artifacts/{artifact_id}/export", unavailable),
                            web.post("/api/v2/artifacts/{artifact_id}/revoke", unavailable)])
    return application
