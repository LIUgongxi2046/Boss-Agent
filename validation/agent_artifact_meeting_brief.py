import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from agent_artifact_formats import FORMATS, create_runtime_format, verify_format, verify_runtime_format
from agent_artifacts import ArtifactPreparation, read_verified_file, store_exact_file
from agent_run_method_selection import AgentRunMethodSelection
from agent_run_object_scope import AgentRunObjectScope
from agent_run_requirements import RunRequirements
from agent_source_history import AgentSourceHistory
from boss_meeting_brief import compile_brief
from boss_meetings import MeetingAPI
from boss_source_access import require_current_business_source
from business import checksum
from hermes_domain_intents import draft_domain_request_key, read_meeting_context_in_transaction
from hermes_meeting_brief_audit import audit_meeting_brief
from hermes_skill_adapter import HermesSkillAdapter


VERSION = "upgrade2_artifact_brief_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")
KINDS = {"AGENDA", "FACT", "COMMITMENT", "CONSENSUS", "CONFLICT", "DECISION", "MISSING"}


def audit_meeting_sections(context, sections):
    return audit_meeting_brief(context, sections)


def verify_terminal_meeting_brief_in_transaction(db, business_store, artifact_id, expected_version):
    if not db.in_transaction or not isinstance(artifact_id, str) or type(expected_version) is not int or expected_version < 1:
        raise ValueError("终态会议简报核查参数无效")
    saved = db.execute("SELECT snapshot,snapshot_sha256 FROM agent_artifact_briefs WHERE artifact_id=?", (artifact_id,)).fetchone()
    if saved is None:
        raise ValueError("终态会议简报记录不存在")
    snapshot = json.loads(saved[0])
    if checksum(snapshot) != saved[1]:
        raise ValueError("终态会议简报摘要不符")
    record = db.execute("SELECT run_id,version,workspace,storage_key,sha256,size_bytes,source_refs,context,verification_status,status FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
    if record is None or record[0] != snapshot["run_id"] or record[1] != expected_version or record[8] != "VERIFIED" or record[9] not in {"VERIFIED", "PUBLISHED"}:
        raise ValueError("终态会议简报成果不可核查")
    version = db.execute("SELECT version FROM agent_artifact_versions WHERE artifact_id=?", (artifact_id,)).fetchone()
    reservation = db.execute("SELECT run_id,status,size_bytes FROM agent_file_reservations WHERE artifact_id=?", (artifact_id,)).fetchone()
    revoked = db.execute("SELECT 1 FROM agent_artifact_revocations WHERE artifact_id=?", (artifact_id,)).fetchone()
    if version != (expected_version,) or reservation != (record[0], "COMPLETED", record[5]) or revoked is not None:
        raise ValueError("终态会议简报版本、预留或撤销状态不可核查")
    if record[9] == "PUBLISHED" and db.execute("SELECT run_id,version,sha256 FROM agent_artifact_publications WHERE artifact_id=?", (artifact_id,)).fetchone() != (record[0], expected_version, record[4]):
        raise ValueError("终态会议简报发布记录不可核查")
    scope_row = db.execute("SELECT goal_revision,request_key,objects,objects_sha256 FROM agent_run_object_scopes WHERE run_id=? AND goal_revision=?", (snapshot["run_id"], snapshot["goal_revision"])).fetchone()
    if scope_row is None or scope_row[1] != snapshot["meeting_scope"]["request_key"] or checksum(json.loads(scope_row[2])) != scope_row[3] or [(item["entity_type"], item["object_id"], item["version"], item["sha256"]) for item in json.loads(scope_row[2])] != [(item["entity_type"], item["object_id"], item["version"], item["sha256"]) for item in snapshot["meeting_scope"]["members"]]:
        raise ValueError("终态会议简报会议范围不可核查")
    method_event = db.execute("SELECT seq,type,payload FROM agent_run_events WHERE run_id=? AND event_id=?", (snapshot["run_id"], snapshot["method_event_id"])).fetchone()
    if method_event is None or method_event[1] != "TOOL_FINISHED" or json.loads(method_event[2]).get("tool_id") != "read_enabled_method" or json.loads(method_event[2]).get("method_ref") != snapshot["method"] or json.loads(method_event[2]).get("goal_revision") != snapshot["goal_revision"]:
        raise ValueError("终态会议简报方法读取事件不可核查")
    domain_brief = snapshot["domain_brief"]
    started = db.execute("SELECT seq,type,payload FROM agent_run_events WHERE run_id=? AND event_id=?", (snapshot["run_id"], domain_brief["started_event_id"])).fetchone()
    finished = db.execute("SELECT seq,type,payload FROM agent_run_events WHERE run_id=? AND event_id=?", (snapshot["run_id"], domain_brief["finished_event_id"])).fetchone()
    if started is None or finished is None or started[1] != "TOOL_STARTED" or finished[1] != "TOOL_FINISHED" or json.loads(started[2]).get("tool_id") != "boss.meeting.brief.prepare" or json.loads(finished[2]).get("tool_id") != "boss.meeting.brief.prepare" or not method_event[0] < started[0] < finished[0]:
        raise ValueError("终态会议简报领域事件不可核查")

    run = db.execute("SELECT actor_id,space_id,goal_revision,applied_goal_revision,status,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (snapshot["run_id"],)).fetchone()
    if run is None or run[4] not in {"SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"} or run[2:4] != (snapshot["goal_revision"], snapshot["goal_revision"]):
        raise ValueError("终态会议简报运行状态不可核查")
    if set(json.loads(run[5])) != {item["source_id"] for item in snapshot["source_refs"]}:
        raise ValueError("终态会议简报来源范围已经变化")
    data = MeetingAPI(business_store)._data(db)
    meeting = data["meeting"]
    context = snapshot["meeting"]
    if context["meeting"] != meeting:
        raise ValueError("终态会议简报会议内容已经变化")
    if context.get("compiled") != compile_brief(db, data):
        raise ValueError("终态会议简报编译内容已经变化")
    domain_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='meeting_brief' AND id=?", (run[1], meeting["meeting_id"])).fetchone()
    if domain_row is None or checksum(json.loads(domain_row[0])) != domain_brief["sha256"] or json.loads(domain_row[0]).get("version") != domain_brief["version"]:
        raise ValueError("终态会议简报领域记录不可核查")
    documents = []
    for reference in snapshot["source_refs"]:
        document = require_current_business_source(business_store, db, run[1], run[0], reference["source_id"])
        if document["version"] != reference["revision"] or checksum(document) != reference["sha256"]:
            raise ValueError("终态会议简报来源已经变化")
        documents.append(document)
    if json.loads(record[6]) != snapshot["source_refs"]:
        raise ValueError("终态会议简报来源记录不可核查")
    selected = AgentRunMethodSelection.read_in_transaction(db, snapshot["run_id"], snapshot["goal_revision"])
    if selected is None or {key: selected[key] for key in ("sop_id", "name", "version", "content_sha256")} != snapshot["method"]:
        raise ValueError("终态会议简报方法选择已经变化")
    adoption = business_store.get(db, run[1], "hermes_skill_adoption", snapshot["run_id"] + ":SOP04")
    if adoption.get("method") != snapshot["method"]:
        raise ValueError("终态会议简报方法采用记录已经变化")
    content = read_verified_file(Path(record[2]), record[3], record[5], record[4])
    verify_format(snapshot["format_name"], content, documents)
    return {"artifact_id": artifact_id, "version": expected_version, "sha256": record[4], "file_state": "VERIFIED", "section_audit": audit_meeting_sections(context, snapshot["sections"])}


def brief_paragraphs(snapshot):
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ["会议简报", "资料性质：SIMULATED", "会议信息：" + encode(snapshot["meeting"]),
            "运行目标：" + snapshot["goal"], "目标补充：" + encode(snapshot["inputs"]),
            "采用方法：" + encode(snapshot["method"]), "会议范围：" + encode(snapshot["meeting_scope"]), "来源引用：" + encode(snapshot["source_refs"])] + [
                "类别：" + item["kind"] + "\n内容：" + item["text"] + "\n来源：" + encode(item["source_ids"])
                for item in snapshot["sections"]]


class RuntimeMeetingBriefPreparation:
    def __init__(self, preparation, skill, *, allow_migration=False):
        if not isinstance(preparation, ArtifactPreparation) or not isinstance(skill, HermesSkillAdapter):
            raise ValueError("会议简报需要成果服务和实际方法服务")
        if skill.sop_id != "SOP04" or skill.run_gate.config != preparation.run_gate.config or skill.run_gate.lease_owner != preparation.run_gate.lease_owner or skill.store.path.resolve() != preparation.store.path.resolve():
            raise ValueError("会议方法与成果运行不一致")
        self.preparation, self.skill = preparation, skill
        self.object_scope = AgentRunObjectScope(preparation.run_gate.store, preparation.scope_service)
        self.method_selection = AgentRunMethodSelection(preparation.run_gate.store, preparation.scope_service, skill.catalog, skill.drafts)
        with FileLock(str(preparation.store.path) + ".migration.lock", timeout=10), preparation.store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_briefs'").fetchone()
            digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
            if row is None and table is None:
                if not allow_migration:
                    raise ValueError("会议简报迁移尚未安装")
                db.executescript("BEGIN IMMEDIATE;\n" + MIGRATION.read_text(encoding="utf-8"))
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))
            elif row is None or table is None or row[0] != digest:
                raise ValueError("会议简报迁移不可核查")

    def _domain_brief(self, db, run, context, method_event_ids, method):
        run_id, meeting = run["run_id"], context["meeting"]
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='meeting_brief' AND id=?", (run["space_id"], meeting["meeting_id"])).fetchone()
        if row is None:
            raise ValueError("当前运行缺少会议简报领域记录")
        record = json.loads(row[0])
        version = record.get("version")
        if not isinstance(version, str) or not version.isdecimal() or int(version) < 1 or record["meeting_id"] != meeting["meeting_id"] or record["meeting_version"] != meeting["version"] or record["compiled"] != context["compiled"]:
            raise ValueError("会议简报领域记录或范围已经变化")
        params = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "expected_version": str(int(version) - 1)}
        root = self.preparation.run_gate.store.require_active_lineage(db, run_id)
        reservations = db.execute("SELECT request_key,request_digest,root_run_id,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND tool_name='boss.meeting.brief.prepare'", (run_id,)).fetchall()
        method_events = [(event_id, db.execute("SELECT seq FROM agent_run_events WHERE run_id=? AND event_id=?", (run_id, event_id)).fetchone()) for event_id in method_event_ids]
        matches = []
        for key, digest, root_id, epoch in reservations:
            if root_id != root or epoch != self.preparation.run_gate.config.lease_epoch or digest != checksum({"goal_revision": run["goal_revision"], "scope_proof": json.loads(run["scope_proof"]), "params": params}):
                continue
            domain_key = draft_domain_request_key("meeting-brief", run_id, key)
            receipt = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation='boss.meeting.brief.prepare' AND key=?", (run["space_id"], domain_key)).fetchone()
            if receipt is None or receipt[0] != checksum({"action": "boss.meeting.brief.prepare", "content": params}):
                continue
            result = json.loads(receipt[1])
            expected = {"source_type": "SIMULATED", "brief_id": record["brief_id"], "meeting_id": meeting["meeting_id"], "version": version,
                        "state": record["state"], "source_count": len(record["compiled"]["sources"]), "missing_count": len(record["compiled"]["missing_items"]),
                        "historical_commitment_count": len(record["compiled"]["commitments"]), "message_sent": False, "meeting_occurred": record["meeting_occurred"]}
            if result != expected:
                continue
            events = db.execute("SELECT event_id,seq,type,payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type IN ('TOOL_STARTED','TOOL_FINISHED') AND json_extract(payload,'$.call_id')=? ORDER BY seq", (run_id, epoch, key)).fetchall()
            if len(events) != 2 or events[0][2] != "TOOL_STARTED" or events[1][2] != "TOOL_FINISHED" or json.loads(events[0][3]) != {"tool_id": "boss.meeting.brief.prepare", "call_id": key} or events[0][1] >= events[1][1]:
                continue
            finished = json.loads(events[1][3])
            method_event_id = finished.get("method_event_id")
            prior_methods = [row[0] for event_id, row in method_events if event_id == method_event_id and row is not None and row[0] < events[0][1]]
            expected_event = {"tool_id": "boss.meeting.brief.prepare", "call_id": key, "outcome": "RETURNED", "goal_revision": run["goal_revision"], "method_ref": method, "method_event_id": method_event_id,
                              "brief_ref": {"kind": "meeting_brief", "object_id": meeting["meeting_id"], "version": version, "sha256": checksum(record), "domain_operation": "boss.meeting.brief.prepare", "domain_request_key": domain_key}}
            if len(prior_methods) != 1 or finished != expected_event:
                continue
            matches.append(({"brief_id": record["brief_id"], "version": version, "sha256": checksum(record), "request_key": key, "started_event_id": events[0][0], "finished_event_id": events[1][0]}, method_event_id))
        if len(matches) != 1:
            raise ValueError("当前目标缺少可核查的会议简报工具回执")
        return matches[0]

    def _snapshot(self, db, run_id, source_ids, expected_goal_revision, meeting_id, meeting_version, sections, format_name):
        prep = self.preparation
        scope = prep._current_scope(db)
        prep._require_run(db, run_id, source_ids, scope)
        scope, refs, documents = prep._sources(db, source_ids, require_titles=False)
        prep._require_budget(db, run_id)
        if type(expected_goal_revision) is not int or expected_goal_revision < 1:
            raise ValueError("会议简报目标版本无效")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        db.row_factory = None
        if run["goal_revision"] != expected_goal_revision or run["applied_goal_revision"] != expected_goal_revision:
            raise ValueError("会议简报目标版本已经变化")
        meeting = read_meeting_context_in_transaction(db, prep.store, prep.scope_service, run)
        if meeting["meeting"]["meeting_id"] != meeting_id or meeting["meeting"]["version"] != meeting_version:
            raise ValueError("会议编号或版本已经变化")
        if not set(source_ids).intersection(item["source_id"] for item in meeting["meeting"]["source_refs"]):
            raise ValueError("会议简报缺少当前会议资料")
        if set(source_ids) != set(json.loads(run["selected_refs"])):
            raise ValueError("会议简报需要完整保存本人选择的来源")
        selected_scope = self.object_scope.read_meeting_in_transaction(db, prep.run_gate, expected_goal_revision, meeting_id)
        context = selected_scope["meeting_context"]
        if context["meeting"]["version"] != meeting_version:
            raise ValueError("会议范围版本已经变化")
        requirements = RunRequirements.read_in_transaction(db, run_id, expected_goal_revision)
        if requirements["state"] != "CONFIRMED" or format_name not in requirements["required_outputs"]:
            raise ValueError("会议简报格式缺少本人选择")
        method_scope = self.skill._guard(db)
        selected_method = self.method_selection.read_in_transaction(db, run_id, expected_goal_revision)
        if selected_method is None:
            raise ValueError("当前目标缺少一致的方法选择")
        _, method = self.skill._current_method()
        if {key: selected_method[key] for key in ("sop_id", "name", "version", "content_sha256")} != method:
            raise ValueError("当前目标缺少一致的方法选择")
        if self.method_selection._current_method(db, {key: method[key] for key in ("sop_id", "version", "content_sha256")}) != method:
            raise ValueError("会议方法或运行依赖已经变化")
        adopted = self.skill.drafts._get(db, "hermes_skill_adoption", run_id + ":SOP04")
        if adopted != {**method_scope, "method": method}:
            raise ValueError("当前运行缺少有效会议方法采用记录")
        events = db.execute("SELECT event_id,payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='TOOL_FINISHED' ORDER BY seq", (run_id, prep.run_gate.config.lease_epoch)).fetchall()
        matching_events = [row[0] for row in events if (event := json.loads(row[1])).get("tool_id") == "read_enabled_method" and event.get("outcome") == "RETURNED" and event.get("goal_revision") == expected_goal_revision and event.get("method_ref") == method]
        if not matching_events:
            raise ValueError("当前目标缺少方法读取事件")
        domain_brief, method_event_id = self._domain_brief(db, run, context, matching_events, method)
        rows = db.execute("SELECT input_id,input_seq,goal_revision,content,applied_event_id FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq", (run_id,)).fetchall()
        if len(rows) != expected_goal_revision - 1 or any(row[1] != index or row[2] != index + 1 or row[4] is None for index, row in enumerate(rows, 1)):
            raise ValueError("目标补充记录不可核查")
        for input_id, sequence, revision, _, event_id in rows:
            event = db.execute("SELECT type,payload FROM agent_run_events WHERE run_id=? AND event_id=?", (run_id, event_id)).fetchone()
            if event is None or event[0] != "INPUT_APPLIED" or json.loads(event[1]) != {"input_id": input_id, "input_seq": sequence, "goal_revision": revision}:
                raise ValueError("目标补充采用事件不可核查")
        if rows:
            last_applied = db.execute("SELECT seq FROM agent_run_events WHERE run_id=? AND event_id=?", (run_id, rows[-1][4])).fetchone()
            method_event = db.execute("SELECT seq FROM agent_run_events WHERE run_id=? AND event_id=?", (run_id, method_event_id)).fetchone()
            if last_applied is None or method_event is None or last_applied[0] >= method_event[0]:
                raise ValueError("目标补充与方法读取顺序不可核查")
        if not isinstance(sections, list) or not sections or len(sections) > 200:
            raise ValueError("会议整理内容无效")
        for item in sections:
            if not isinstance(item, dict) or set(item) != {"kind", "text", "source_ids"} or item["kind"] not in KINDS or not isinstance(item["text"], str) or not item["text"].strip() or len(item["text"]) > 12000 or not isinstance(item["source_ids"], list) or any(not isinstance(value, str) for value in item["source_ids"]) or len(set(item["source_ids"])) != len(item["source_ids"]) or not set(item["source_ids"]).issubset(source_ids) or (item["kind"] != "MISSING" and not item["source_ids"]):
                raise ValueError("会议整理内容或引用无效")
        meeting_scope = {"request_key": selected_scope["request_key"], "sha256": checksum(context),
                         "members": [{key: member[key] for key in ("entity_type", "object_id", "version", "sha256")} for member in context["members"]],
                         "metric_configurations": {key: None if value is None else {"version": value["version"], "content_sha256": value["content_sha256"]} for key, value in context["metric_configurations"].items()}}
        snapshot = {"run_id": run_id, "goal_revision": expected_goal_revision, "goal": run["goal"], "format_name": format_name,
                    "inputs": [{"input_id": row[0], "input_seq": row[1], "goal_revision": row[2], "content": row[3], "applied_event_id": row[4]} for row in rows],
                    "meeting": meeting, "meeting_scope": meeting_scope, "domain_brief": domain_brief, "method": method, "method_event_id": method_event_id, "source_refs": refs, "sections": sections}
        return scope, refs, documents, snapshot, audit_meeting_sections(context, sections)

    def create(self, run_id, source_ids, *, request_key, format_name, expected_goal_revision, meeting_id, meeting_version, sections, previous_artifact_id=None, expected_version=None):
        prep = self.preparation
        prep._uuid(run_id)
        prep._validate_sources(source_ids)
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128 or format_name not in FORMATS or any(not isinstance(item, str) or not item for item in (meeting_id, meeting_version)):
            raise ValueError("会议简报请求无效")
        if previous_artifact_id is None:
            if expected_version is not None:
                raise ValueError("会议简报前一版本无效")
        else:
            prep._uuid(previous_artifact_id)
            if type(expected_version) is not int or expected_version < 1:
                raise ValueError("会议简报前一版本无效")
        with self.skill.drafts._locked():
            with prep.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                scope, refs, documents, snapshot, section_audit = self._snapshot(db, run_id, source_ids, expected_goal_revision, meeting_id, meeting_version, sections, format_name)
                snapshot_sha = checksum(snapshot)
                digest = checksum({"snapshot_sha256": snapshot_sha, "format": format_name, "previous_artifact_id": previous_artifact_id, "expected_version": expected_version})
                old = db.execute("SELECT artifact_id,request_digest,status FROM agent_file_reservations WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
                if old is not None:
                    if old[1] != digest or old[2] == "RELEASED":
                        raise ValueError("会议简报请求编号冲突")
                    artifact_id = old[0]
                    saved = db.execute("SELECT snapshot,snapshot_sha256 FROM agent_artifact_briefs WHERE artifact_id=?", (artifact_id,)).fetchone()
                    if saved is None or json.loads(saved[0]) != snapshot or saved[1] != snapshot_sha:
                        raise ValueError("会议简报登记内容不可核查")
                    if old[2] == "COMPLETED":
                        return self._verify(db, artifact_id, snapshot, scope, refs, section_audit)
                    pending = db.execute("SELECT content,sha256 FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,)).fetchone()
                    if pending is None or hashlib.sha256(pending[0]).hexdigest() != pending[1]:
                        raise ValueError("会议简报预留内容不可核查")
                    content = pending[0]
                else:
                    content = create_runtime_format(format_name, brief_paragraphs(snapshot))
                    artifact_id = str(uuid4())
                    prior = prep.run_gate.store.reserve_file_in_transaction(db, run_id, prep.run_gate.lease_owner, prep.run_gate.config.lease_epoch, request_key, digest, artifact_id, len(content), allow_reserved=True)
                    if prior is not None:
                        raise ValueError("会议简报预留冲突")
                    series, version = artifact_id, 1
                    if previous_artifact_id is not None:
                        prep._require_previous(db, run_id, previous_artifact_id, expected_version, scope)
                        previous = db.execute("SELECT snapshot,snapshot_sha256 FROM agent_artifact_briefs WHERE artifact_id=?", (previous_artifact_id,)).fetchone()
                        if previous is None:
                            raise ValueError("会议简报前一版本缺少内容记录")
                        prior_snapshot = json.loads(previous[0])
                        if checksum(prior_snapshot) != previous[1] or prior_snapshot["meeting"]["meeting"]["meeting_id"] != meeting_id:
                            raise ValueError("会议简报前一版本内容不符")
                        link = db.execute("SELECT series_id,version FROM agent_artifact_versions WHERE artifact_id=?", (previous_artifact_id,)).fetchone()
                        if link is None or link[1] != expected_version or db.execute("SELECT 1 FROM agent_artifact_versions WHERE previous_artifact_id=?", (previous_artifact_id,)).fetchone() is not None:
                            raise ValueError("会议简报前一版本已经变化")
                        series, version = link[0], expected_version + 1
                    db.execute("INSERT INTO agent_artifact_versions VALUES (?,?,?,?)", (artifact_id, series, version, previous_artifact_id))
                    db.execute("INSERT INTO agent_artifact_pending VALUES (?,?,?,?,?,?,?)", (artifact_id, str(prep.workspace), format_name, content, hashlib.sha256(content).hexdigest(), json.dumps(refs, ensure_ascii=False), json.dumps(scope, ensure_ascii=False)))
                    db.execute("INSERT INTO agent_artifact_briefs VALUES (?,?,?)", (artifact_id, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), snapshot_sha))
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                new_scope, new_refs, _, current, new_audit = self._snapshot(db, run_id, source_ids, expected_goal_revision, meeting_id, meeting_version, sections, format_name)
                if current != snapshot or new_scope != scope or new_refs != refs or new_audit != section_audit:
                    raise ValueError("会议简报生成期间上下文已经变化")
                saved = db.execute("SELECT snapshot,snapshot_sha256 FROM agent_artifact_briefs WHERE artifact_id=?", (artifact_id,)).fetchone()
                if saved is None or json.loads(saved[0]) != snapshot or saved[1] != checksum(snapshot):
                    raise ValueError("会议简报登记内容已经变化")
                if previous_artifact_id is not None:
                    prep._require_previous(db, run_id, previous_artifact_id, expected_version, scope)
                link = db.execute("SELECT version,previous_artifact_id FROM agent_artifact_versions WHERE artifact_id=?", (artifact_id,)).fetchone()
                if link != (1 if expected_version is None else expected_version + 1, previous_artifact_id):
                    raise ValueError("会议简报版本关系不可核查")
                pending = db.execute("SELECT workspace,format_name,content,sha256,source_refs,context FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,)).fetchone()
                if pending is None or pending[0] != str(prep.workspace) or pending[1] != format_name or pending[2] != content or pending[3] != hashlib.sha256(content).hexdigest() or json.loads(pending[4]) != refs or json.loads(pending[5]) != scope:
                    raise ValueError("会议简报预留内容已经变化")
                storage_key = artifact_id + FORMATS[format_name][0]
                content = store_exact_file(prep.workspace, storage_key, content)
                verify_runtime_format(format_name, content, brief_paragraphs(snapshot))
                metadata = {"artifact_id": artifact_id, "run_id": run_id, "version": link[0], "media_type": FORMATS[format_name][1], "storage_key": storage_key, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content), "source_refs": refs, "verification_status": "VERIFIED", "status": "VERIFIED"}
                conversation = db.execute("SELECT conversation_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                if conversation is None:
                    raise ValueError("会议简报运行会话不可核查")
                proof = prep.scope_service.prove_in_transaction(db, conversation[0], source_ids)
                AgentSourceHistory(prep.run_gate.store, prep.scope_service).retain_citations_in_transaction(db, proof, refs, run_id=run_id)
                db.execute("INSERT INTO agent_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (artifact_id, run_id, link[0], metadata["media_type"], str(prep.workspace), storage_key, metadata["sha256"], len(content), json.dumps(refs, ensure_ascii=False), json.dumps(scope, ensure_ascii=False), "VERIFIED", "VERIFIED"))
                if db.execute("UPDATE agent_file_reservations SET status='COMPLETED' WHERE artifact_id=? AND status='RESERVED'", (artifact_id,)).rowcount != 1 or db.execute("DELETE FROM agent_artifact_pending WHERE artifact_id=?", (artifact_id,)).rowcount != 1:
                    raise ValueError("会议简报预留状态不可核查")
                prep._record_candidate(db, metadata)
                from agent_artifact_goal import AgentArtifactGoal
                AgentArtifactGoal.record_in_transaction(db, run_id, artifact_id)
                return {**metadata, "section_audit": section_audit}

    def _verify(self, db, artifact_id, snapshot, scope, refs, section_audit=None):
        prep = self.preparation
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        db.row_factory = None
        if row is None or row["run_id"] != snapshot["run_id"] or row["workspace"] != str(prep.workspace) or row["status"] not in {"VERIFIED", "PUBLISHED"} or row["verification_status"] != "VERIFIED" or json.loads(row["source_refs"]) != refs or json.loads(row["context"]) != scope:
            raise ValueError("会议简报成果不可核查")
        reservation = db.execute("SELECT run_id,status,size_bytes FROM agent_file_reservations WHERE artifact_id=?", (artifact_id,)).fetchone()
        version = db.execute("SELECT series_id,version,previous_artifact_id FROM agent_artifact_versions WHERE artifact_id=?", (artifact_id,)).fetchone()
        revoked = db.execute("SELECT 1 FROM agent_artifact_revocations WHERE artifact_id=?", (artifact_id,)).fetchone()
        if reservation != (snapshot["run_id"], "COMPLETED", row["size_bytes"]) or version is None or version[1] != row["version"] or revoked is not None:
            raise ValueError("会议简报版本或状态不可核查")
        if row["status"] == "PUBLISHED" and db.execute("SELECT run_id,version,sha256,actor_id FROM agent_artifact_publications WHERE artifact_id=?", (artifact_id,)).fetchone() != (row["run_id"], row["version"], row["sha256"], scope["owner_id"]):
            raise ValueError("会议简报发布记录不可核查")
        candidates = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND type='ARTIFACT_CANDIDATE' AND json_extract(payload,'$.artifact_id')=?", (snapshot["run_id"], artifact_id)).fetchall()
        finished = db.execute("SELECT seq FROM agent_run_events WHERE run_id=? AND event_id=?", (snapshot["run_id"], snapshot["domain_brief"]["finished_event_id"])).fetchone()
        if len(candidates) != 1 or json.loads(candidates[0][1]) != {"artifact_id": artifact_id, "version": row["version"], "media_type": row["media_type"], "sha256": row["sha256"]} or finished is None or finished[0] >= candidates[0][0]:
            raise ValueError("会议简报成果事件不可核查")
        format_name = next((name for name, value in FORMATS.items() if value[1] == row["media_type"]), None)
        if format_name is None:
            raise ValueError("会议简报格式无效")
        content = prep._read_verified_bytes(row["storage_key"], row["size_bytes"], row["sha256"])
        verify_runtime_format(format_name, content, brief_paragraphs(snapshot))
        result = {key: json.loads(row[key]) if key == "source_refs" else row[key] for key in ("artifact_id", "run_id", "version", "media_type", "storage_key", "sha256", "size_bytes", "source_refs", "verification_status", "status")}
        if section_audit is not None:
            result["section_audit"] = section_audit
        return result

    def verify_in_transaction(self, db, artifact_id, expected_version):
        prep = self.preparation
        prep._uuid(artifact_id)
        main = db.execute("PRAGMA database_list").fetchone()
        if type(expected_version) is not int or expected_version < 1 or not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != prep.store.path.resolve():
            raise ValueError("会议简报版本无效")
        saved = db.execute("SELECT snapshot,snapshot_sha256 FROM agent_artifact_briefs WHERE artifact_id=?", (artifact_id,)).fetchone()
        if saved is None:
            raise ValueError("会议简报记录不存在")
        snapshot = json.loads(saved[0])
        if checksum(snapshot) != saved[1]:
            raise ValueError("会议简报内容摘要不符")
        meeting = snapshot["meeting"]["meeting"]
        ids = [item["source_id"] for item in snapshot["source_refs"]]
        scope, refs, _, current, section_audit = self._snapshot(db, snapshot["run_id"], ids, snapshot["goal_revision"], meeting["meeting_id"], meeting["version"], snapshot["sections"], snapshot["format_name"])
        if current != snapshot:
            raise ValueError("会议简报引用已经变化")
        metadata = self._verify(db, artifact_id, snapshot, scope, refs, section_audit)
        if metadata["version"] != expected_version or metadata["media_type"] != FORMATS[snapshot["format_name"]][1]:
            raise ValueError("会议简报版本或格式已经变化")
        return {**metadata, "format": snapshot["format_name"], "file_state": "VERIFIED"}

    def read(self, artifact_id, expected_version):
        prep = self.preparation
        with self.skill.drafts._locked(), prep.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            metadata = self.verify_in_transaction(db, artifact_id, expected_version)
            return prep._read_verified_bytes(metadata["storage_key"], metadata["size_bytes"], metadata["sha256"])
