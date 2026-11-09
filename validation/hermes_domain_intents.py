import json
import hashlib
from dataclasses import asdict
from datetime import datetime

from aiohttp import web

from agent_run_store import RunStore
from boss_execution_scope import NAMESPACE
from boss_meeting_approval import existing, minutes_save
from boss_meetings import MeetingAPI
from boss_source_access import require_current_business_source
from business import checksum
from boss_command_api import _aware_due, _is_text
from hermes_domain_schema import FIELDS, MEETING_DRAFT_SCHEMA, MINUTES_DRAFT_SCHEMA
from jsonschema import Draft202012Validator


MEETING_DRAFT_VALIDATOR = Draft202012Validator(MEETING_DRAFT_SCHEMA)
MINUTES_DRAFT_VALIDATOR = Draft202012Validator(MINUTES_DRAFT_SCHEMA)


def prepare_meeting_brief_in_transaction(db, store, object_scope, sink, params, request_key):
    from agent_run_object_scope import AgentRunObjectScope
    from boss_meeting_brief import prepare
    if not db.in_transaction or not isinstance(object_scope, AgentRunObjectScope) or object_scope.scope.store.path.resolve() != store.path.resolve():
        raise web.HTTPConflict(text="会议简报需要当前运行范围事务")
    if not isinstance(params, dict) or set(params) != {"meeting_id", "meeting_version", "expected_version"} or any(not isinstance(value, str) or not value for value in params.values()) or not isinstance(request_key, str) or not 8 <= len(request_key) <= 128 or not request_key.isascii() or not all(char.isalnum() or char in "-_." for char in request_key):
        raise web.HTTPBadRequest(text="会议简报请求字段无效")
    row = db.execute("SELECT goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
    if row is None or row[0] != row[1]:
        raise web.HTTPConflict(text="运行目标版本已经变化")
    selected = object_scope.read_meeting_in_transaction(db, sink, row[0], params["meeting_id"])
    meeting_context = selected["meeting_context"]
    if meeting_context["meeting"]["version"] != params["meeting_version"]:
        raise web.HTTPConflict(text="会议版本已经变化")
    api = MeetingAPI(store).commands
    data = MeetingAPI(store)._data(db)
    payload = {**params, "client_request_id": draft_domain_request_key("meeting-brief", sink.config.run_id, request_key)}
    key, digest, result = api._check_existing(db, "boss.meeting.brief.prepare", payload)
    if result is None:
        result = prepare(api, db, data, payload)
        api._record(db, "boss.meeting.brief.prepare", payload, key, digest, result)
    record = store.get(db, NAMESPACE, "meeting_brief", params["meeting_id"])
    if record["version"] != result["version"] or record["meeting_version"] != params["meeting_version"] or record["compiled"] != meeting_context["compiled"]:
        raise web.HTTPConflict(text="会议简报或范围已经变化")
    materials = []
    for reference in record["compiled"]["sources"]:
        document = require_current_business_source(store, db, NAMESPACE, meeting_context["meeting"]["owner_id"], reference["source_id"])
        if reference["status"] != "CURRENT" or document["version"] != reference["version"] or checksum(document) != reference["source_sha256"] or not isinstance(document.get("content"), str):
            raise web.HTTPConflict(text="会议材料内容或来源已经变化")
        materials.append({"source_id": document["source_id"], "version": document["version"], "source_sha256": reference["source_sha256"], "content": document["content"]})
    return {**result, "brief": record, "source_materials": materials,
            "content_checks": {kind: "NOT_VERIFIED" for kind in ("AGENDA", "CONSENSUS", "CONFLICT", "DECISION")}}


def draft_domain_request_key(kind, run_id, request_key):
    return "hermes-" + kind + "-" + hashlib.sha256(json.dumps([run_id, request_key], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def brief_result_event_in_transaction(db, store, run_id, goal_revision, request_key, result, method_ref, method_event_id):
    if not db.in_transaction or type(goal_revision) is not int or goal_revision < 1 or not isinstance(method_ref, dict) or method_ref.get("sop_id") != "SOP04" or not isinstance(method_event_id, str) or not method_event_id:
        raise ValueError("会议简报事件参数无效")
    record = store.get(db, NAMESPACE, "meeting_brief", result["meeting_id"])
    domain_key = draft_domain_request_key("meeting-brief", run_id, request_key)
    receipt = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (NAMESPACE, "boss.meeting.brief.prepare", domain_key)).fetchone()
    if record != result.get("brief") or record["version"] != result["version"] or receipt is None or json.loads(receipt[0]) != {key: value for key, value in result.items() if key not in {"brief", "source_materials", "content_checks"}}:
        raise web.HTTPConflict(text="会议简报领域回执不可核查")
    return {"tool_id": "boss.meeting.brief.prepare", "call_id": request_key, "outcome": "RETURNED", "goal_revision": goal_revision, "method_ref": method_ref, "method_event_id": method_event_id, "brief_ref": {"kind": "meeting_brief", "object_id": result["meeting_id"], "version": result["version"], "sha256": checksum(record), "domain_operation": "boss.meeting.brief.prepare", "domain_request_key": domain_key}}


def draft_result_event_in_transaction(db, store, run_id, goal_revision, request_key, kind, result, *, tool_name=None):
    if not db.in_transaction or type(goal_revision) is not int or goal_revision < 1 or kind not in {"meeting", "minutes"}:
        raise ValueError("草稿事件参数无效")
    if kind == "meeting":
        confirmation = result["confirmation_parameters"]
        object_id, version = confirmation["meeting_id"], confirmation["draft_version"]
        object_kind, operation = "meeting_draft", "boss.meeting.draft.save"
        if tool_name is None:
            tool_name = "save_meeting_draft"
        if tool_name not in {"save_meeting_draft", "meetingDraftSave"}:
            raise ValueError("会议草稿工具名称无效")
    else:
        confirmation = result["confirmation_parameters"]
        object_id, version = confirmation["meeting_id"], confirmation["expected_version"]
        object_kind, operation = "minutes", "boss.minutes.save"
        if tool_name is None:
            tool_name = "save_minutes_draft"
        if tool_name != "save_minutes_draft":
            raise ValueError("纪要草稿工具名称无效")
    draft = store.get(db, NAMESPACE, object_kind, object_id)
    if draft["version"] != version:
        raise web.HTTPConflict(text="草稿版本已经变化")
    domain_key = draft_domain_request_key(kind, run_id, request_key)
    if db.execute("SELECT 1 FROM idempotency WHERE namespace=? AND operation=? AND key=?", (NAMESPACE, operation, domain_key)).fetchone() is None:
        raise web.HTTPConflict(text="草稿领域请求记录不存在")
    return {"tool_id": tool_name, "call_id": request_key, "outcome": "RETURNED", "goal_revision": goal_revision,
            "draft_ref": {"kind": object_kind, "object_id": object_id, "version": version, "sha256": checksum(draft), "domain_operation": operation, "domain_request_key": domain_key}}


def minutes_scope_in_transaction(db, store, scope, run):
    if not db.in_transaction or run["status"] != "RUNNING" or run["cancel_requested_at"] is not None or run["goal_revision"] != run["applied_goal_revision"]:
        raise web.HTTPConflict(text="运行或目标版本不可处理纪要")
    RunStore._require_lease(db, run["run_id"], run["lease_owner"], run["lease_epoch"])
    RunStore.require_active_lineage(db, run["run_id"])
    columns = ("actor_id", "space_id", "conversation_id", "selected_refs", "scope_proof", "status", "cancel_requested_at", "goal_revision", "applied_goal_revision", "lease_owner", "lease_epoch")
    current = db.execute("SELECT " + ",".join(columns) + " FROM agent_runs WHERE run_id=?", (run["run_id"],)).fetchone()
    if current is None or tuple(current) != tuple(run[column] for column in columns):
        raise web.HTTPConflict(text="运行记录已经变化")
    proof = scope.prove_in_transaction(db, run["conversation_id"], json.loads(run["selected_refs"]))
    if (proof.owner_id, proof.namespace) != (run["actor_id"], run["space_id"]) or json.loads(json.dumps(asdict(proof))) != json.loads(run["scope_proof"]) or proof.namespace != NAMESPACE:
        raise web.HTTPForbidden(text="纪要来源范围不匹配")
    data = MeetingAPI(store)._data(db)
    if data["owner_id"] != proof.owner_id:
        raise web.HTTPForbidden(text="会议归属不匹配")
    return data, proof


def read_minutes_context_in_transaction(db, store, scope, run):
    data, proof = minutes_scope_in_transaction(db, store, scope, run)
    meeting = data["meeting"]
    minute = existing(db, "minutes", meeting["meeting_id"])
    pins = {source_id: (version, digest) for source_id, version, digest in proof.source_pins}
    relevant = set(meeting["material_ids"]).intersection(pins)
    if not relevant:
        raise web.HTTPForbidden(text="会议材料未获当前运行选择")
    result = {"source_type": "SIMULATED", "meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "minutes": None, "assignment_context": None}
    if "finance-note" in pins:
        assignment_source = require_current_business_source(store, db, proof.namespace, proof.owner_id, "finance-note")
        if assignment_source["version"] != pins["finance-note"][0] or checksum(assignment_source) != pins["finance-note"][1]:
            raise web.HTTPConflict(text="交办来源已经变化")
        today = datetime.fromisoformat(store.get(db, NAMESPACE, "clock", "current")["at"]).date().isoformat()
        coordinators = [item["contact_id"] for item in data["contacts"] if item["contact_id"] == "coordinator-1" and item["valid_from"] <= today <= item["valid_until"]]
        result["assignment_context"] = {"related_meeting_id": meeting["meeting_id"], "related_event_ids": [data["event"]["event_id"]], "source_refs": ["finance-note"], "content_version": "1", "eligible_coordinator_ids": coordinators}
    if minute is None:
        return result
    if minute["source_id"] not in pins or pins[minute["source_id"]][0] != minute["source_version"]:
        raise web.HTTPForbidden(text="纪要来源未获当前运行选择")
    document = require_current_business_source(store, db, proof.namespace, proof.owner_id, minute["source_id"])
    if checksum(document) != pins[minute["source_id"]][1] or minute["meeting_version"] != meeting["version"]:
        raise web.HTTPConflict(text="纪要来源或会议版本已经变化")
    confirmation = {"meeting_id": meeting["meeting_id"], "expected_version": minute["version"], "source_id": minute["source_id"], "source_version": minute["source_version"]} if minute["state"] == "DRAFT_REVIEW" else None
    result["minutes"] = {"details": minute, "confirmation_parameters": confirmation}
    return result


def save_minutes_draft_in_transaction(db, store, scope, run, params, request_key):
    if not MINUTES_DRAFT_VALIDATOR.is_valid(params) or not isinstance(request_key, str) or not 8 <= len(request_key) <= 128 or not request_key.isascii() or not all(char.isalnum() or char in "-_." for char in request_key):
        raise web.HTTPBadRequest(text="纪要草稿字段无效")
    data, proof = minutes_scope_in_transaction(db, store, scope, run)
    read_minutes_context_in_transaction(db, store, scope, run)
    pins = {source_id: (version, digest) for source_id, version, digest in proof.source_pins}
    if params["source_id"] not in pins or pins[params["source_id"]][0] != params["source_version"]:
        raise web.HTTPForbidden(text="纪要来源不属于当前运行范围")
    document = require_current_business_source(store, db, proof.namespace, proof.owner_id, params["source_id"])
    if checksum(document) != pins[params["source_id"]][1]:
        raise web.HTTPConflict(text="纪要来源已经变化")
    api = MeetingAPI(store).commands
    client_key = draft_domain_request_key("minutes", run["run_id"], request_key)
    payload = {**params, "client_request_id": client_key}
    key, digest, saved = api._check_existing(db, "boss.minutes.save", payload)
    if saved is None:
        saved = minutes_save(api, db, data, payload)
        api._record(db, "boss.minutes.save", payload, key, digest, saved)
    current = read_minutes_context_in_transaction(db, store, scope, run)["minutes"]
    if current is None or current["details"]["version"] != saved["version"] or current["details"]["state"] != "DRAFT_REVIEW":
        raise web.HTTPConflict(text="纪要草稿已经变化")
    preview_domain_intent(db, store, scope, run, "boss.minutes.confirm", current["confirmation_parameters"])
    return current


def save_meeting_draft_in_transaction(db, store, scope, run, params, request_key):
    if not db.in_transaction or not MEETING_DRAFT_VALIDATOR.is_valid(params) or not isinstance(request_key, str) or not 8 <= len(request_key) <= 128 or not request_key.isascii() or not all(char.isalnum() or char in "-_." for char in request_key):
        raise web.HTTPBadRequest(text="会议草稿字段无效")
    if run["status"] != "RUNNING" or run["cancel_requested_at"] is not None or run["goal_revision"] != run["applied_goal_revision"]:
        raise web.HTTPConflict(text="运行或目标版本不可准备会议草稿")
    RunStore._require_lease(db, run["run_id"], run["lease_owner"], run["lease_epoch"])
    RunStore.require_active_lineage(db, run["run_id"])
    columns = ("actor_id", "space_id", "conversation_id", "selected_refs", "scope_proof", "status", "cancel_requested_at", "goal_revision", "applied_goal_revision", "lease_owner", "lease_epoch")
    current = db.execute("SELECT " + ",".join(columns) + " FROM agent_runs WHERE run_id=?", (run["run_id"],)).fetchone()
    if current is None or tuple(current) != tuple(run[column] for column in columns):
        raise web.HTTPConflict(text="运行记录已经变化")
    selected = json.loads(run["selected_refs"])
    proof = scope.prove_in_transaction(db, run["conversation_id"], selected)
    if (proof.owner_id, proof.namespace) != (run["actor_id"], run["space_id"]) or json.loads(json.dumps(asdict(proof))) != json.loads(run["scope_proof"]) or proof.namespace != NAMESPACE:
        raise web.HTTPForbidden(text="会议来源范围不匹配")
    pins = {source_id: (version, digest) for source_id, version, digest in proof.source_pins}
    for ref in params["source_refs"]:
        if ref["source_id"] not in pins or pins[ref["source_id"]][0] != ref["version"]:
            raise web.HTTPForbidden(text="会议材料不属于当前运行范围")
        document = require_current_business_source(store, db, proof.namespace, proof.owner_id, ref["source_id"])
        if checksum(document) != pins[ref["source_id"]][1]:
            raise web.HTTPConflict(text="会议材料已经变化")
    api = MeetingAPI(store)
    data = api._data(db)
    if data["owner_id"] != proof.owner_id:
        raise web.HTTPForbidden(text="会议归属不匹配")
    client_key = draft_domain_request_key("meeting", run["run_id"], request_key)
    payload = {**params, "client_request_id": client_key}
    key, digest, result = api.commands._check_existing(db, "boss.meeting.draft.save", payload)
    if result is None:
        result = api._save(db, data, payload)
        api.commands._record(db, "boss.meeting.draft.save", payload, key, digest, result)
    confirmation = {"meeting_id": result["meeting_id"], "meeting_version": result["meeting_version"], "draft_version": result["version"], "review_sha256": result["review_sha256"]}
    preview = preview_domain_intent(db, store, scope, run, "boss.meeting.confirm", confirmation)
    return {"status": "DRAFT", "confirmation_parameters": confirmation, "details": preview["details"], "impact": preview["impact"], "source_refs": preview["source_refs"]}


def read_meeting_context_in_transaction(db, store, scope, run):
    if not db.in_transaction or run["status"] != "RUNNING" or run["cancel_requested_at"] is not None or run["goal_revision"] != run["applied_goal_revision"]:
        raise web.HTTPConflict(text="运行或目标版本不可读取会议")
    RunStore._require_lease(db, run["run_id"], run["lease_owner"], run["lease_epoch"])
    RunStore.require_active_lineage(db, run["run_id"])
    columns = ("actor_id", "space_id", "conversation_id", "selected_refs", "scope_proof", "status", "cancel_requested_at", "goal_revision", "applied_goal_revision", "lease_owner", "lease_epoch")
    current = db.execute("SELECT " + ",".join(columns) + " FROM agent_runs WHERE run_id=?", (run["run_id"],)).fetchone()
    if current is None or tuple(current) != tuple(run[column] for column in columns):
        raise web.HTTPConflict(text="运行记录已经变化")
    selected = json.loads(run["selected_refs"])
    proof = scope.prove_in_transaction(db, run["conversation_id"], selected)
    if (proof.owner_id, proof.namespace) != (run["actor_id"], run["space_id"]) or json.loads(json.dumps(asdict(proof))) != json.loads(run["scope_proof"]) or proof.namespace != NAMESPACE:
        raise web.HTTPForbidden(text="会议来源范围不匹配")
    data = MeetingAPI(store)._data(db)
    meeting = data["meeting"]
    if data["owner_id"] != proof.owner_id:
        raise web.HTTPForbidden(text="会议归属不匹配")
    draft = existing(db, "meeting_draft", meeting["meeting_id"])
    relevant = set(meeting["material_ids"])
    if draft is not None:
        relevant.update(item["source_id"] for item in draft["details"]["source_refs"])
    if not relevant.intersection(selected):
        raise web.HTTPForbidden(text="会议材料未获当前运行选择")
    pins = {source_id: (version, digest) for source_id, version, digest in proof.source_pins}
    materials = []
    for source_id in selected:
        if source_id not in relevant:
            continue
        document = require_current_business_source(store, db, proof.namespace, proof.owner_id, source_id)
        version, digest = pins[source_id]
        if document["version"] != version or checksum(document) != digest:
            raise web.HTTPConflict(text="会议材料已经变化")
        materials.append({"source_id": source_id, "version": version, "source_sha256": digest})
    meeting_context = {"meeting_id": meeting["meeting_id"], "version": meeting["version"], "state": meeting.get("state", "DRAFT"),
                       "title": meeting.get("title"), "starts_at": meeting["starts_at"], "ends_at": meeting.get("ends_at"),
                       "timezone": meeting["timezone"], "participant_ids": meeting["participant_ids"], "source_refs": materials}
    if any(not isinstance(meeting_context[key], str) or not meeting_context[key] for key in ("meeting_id", "version", "state", "starts_at", "timezone")) or any(meeting_context[key] is not None and (not isinstance(meeting_context[key], str) or not meeting_context[key]) for key in ("title", "ends_at")) or not isinstance(meeting_context["participant_ids"], list) or any(not isinstance(item, str) or not item for item in meeting_context["participant_ids"]):
        raise web.HTTPConflict(text="会议基本信息不可核查")
    result = {"source_type": "SIMULATED", "meeting": meeting_context, "draft": None}
    if draft is None:
        return result
    params = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "draft_version": draft["version"], "review_sha256": draft["review_sha256"]}
    preview = preview_domain_intent(db, store, scope, run, "boss.meeting.confirm", params)
    result["draft"] = {"confirmation_parameters": params, "details": preview["details"], "impact": preview["impact"], "source_refs": preview["source_refs"]}
    return result


def read_meeting_projection_in_transaction(db, store, scope, run, kind):
    from boss_insights import meeting_insights
    from boss_v7_library import read_meeting_library
    if kind not in {"catalog", "arrangement"}:
        raise ValueError("会议读取类型无效")
    context = read_meeting_context_in_transaction(db, store, scope, run)
    data = MeetingAPI(store)._data(db)
    selected = set(json.loads(run["selected_refs"]))
    meeting = context["meeting"]
    clock = store.get(db, NAMESPACE, "clock", "current")["at"]
    if kind == "arrangement":
        participants = [contact for contact in data["contacts"] if contact["contact_id"] in meeting["participant_ids"]]
        if len(participants) != len(meeting["participant_ids"]) or len({contact["contact_id"] for contact in participants}) != len(participants):
            raise web.HTTPConflict(text="参会人员集合不可核查")
        revisions = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='meeting_revision' ORDER BY id", (NAMESPACE,)).fetchall()]
        meeting = {**meeting, "preparation_due_at": data["meeting"].get("preparation_due_at")}
        return {"source_type": "SIMULATED", "meeting": meeting, "draft": context["draft"], "contacts": participants,
                "sources": meeting["source_refs"], "revisions": [{"version": item["version"], "state": item.get("state", "DRAFT")} for item in revisions if item.get("meeting_id") == meeting["meeting_id"]],
                "business_at": clock, "invitation_sent": None, "scope": "SELECTED_MEETING_SOURCES"}
    library = read_meeting_library(store, db, data)
    records, insight_records = [], []
    for item in library["records"]:
        refs = item["source_refs"]
        if item["kind"] not in {"meeting", "document"} or not refs or any(ref["source_id"] not in selected for ref in refs):
            continue
        if item["kind"] == "meeting" and (item["id"] != meeting["meeting_id"] or item["material_gaps"]):
            continue
        if item["kind"] == "document" and item["id"] not in selected:
            continue
        record = {key: item[key] for key in ("id", "kind", "title", "version", "at", "local_date", "timezone", "source_type", "summary", "material_state", "meeting_state", "source_refs")}
        record["actions"] = [action for action in item["actions"] if action["id"] == "source" and action["source_id"] in selected]
        records.append(record)
        if item["kind"] == "meeting" and item["meeting_state"] != "HELD":
            insight_records.append(item)
    documents = []
    for ref in meeting["source_refs"]:
        document = require_current_business_source(store, db, scope.namespace, run["actor_id"], ref["source_id"])
        if document["version"] != ref["version"] or checksum(document) != ref["source_sha256"]:
            raise web.HTTPConflict(text="会议材料已经变化")
        documents.append({**ref, "source_type": document["source_type"], "author_contact_id": document.get("author_contact_id"), "published_at": document.get("published_at"), "original_locator": document.get("original_locator")})
    return {"source_type": "SIMULATED", "meeting": meeting, "documents": documents,
            "library": {"source_type": "SIMULATED", "records": records, "insights": meeting_insights(insight_records, clock), "scope": "SELECTED_MEETING_SOURCES", "business_clock": clock},
            "business_at": clock}


def preview_domain_intent(db, store, scope, run, action, params, *, allow_waiting=False):
    if not db.in_transaction or not isinstance(action, str) or action not in FIELDS or not isinstance(params, dict) or set(params) != FIELDS[action]:
        raise web.HTTPBadRequest(text="业务意图字段无效")
    if run["status"] not in ({"RUNNING", "WAITING_CONFIRMATION"} if allow_waiting else {"RUNNING"}) or run["cancel_requested_at"] is not None or run["goal_revision"] != run["applied_goal_revision"]:
        raise web.HTTPConflict(text="运行或目标版本不可准备意图")
    RunStore._require_lease(db, run["run_id"], run["lease_owner"], run["lease_epoch"])
    RunStore.require_active_lineage(db, run["run_id"])
    columns = ("actor_id", "space_id", "conversation_id", "selected_refs", "scope_proof", "status", "cancel_requested_at", "goal_revision", "applied_goal_revision", "lease_owner", "lease_epoch")
    current = db.execute("SELECT " + ",".join(columns) + " FROM agent_runs WHERE run_id=?", (run["run_id"],)).fetchone()
    if current is None or tuple(current) != tuple(run[column] for column in columns):
        raise web.HTTPConflict(text="运行记录已经变化")
    refs = json.loads(run["selected_refs"])
    proof = scope.prove_in_transaction(db, run["conversation_id"], refs)
    if (proof.owner_id, proof.namespace) != (run["actor_id"], run["space_id"]) or json.loads(json.dumps(asdict(proof))) != json.loads(run["scope_proof"]) or proof.namespace != NAMESPACE:
        raise web.HTTPForbidden(text="运行来源范围不匹配")
    data = MeetingAPI(store)._data(db)
    meeting = data["meeting"]
    if data["owner_id"] != proof.owner_id:
        raise web.HTTPForbidden(text="业务对象归属不匹配")
    object_id, object_version = meeting["meeting_id"], meeting["version"]
    context = {"meeting": meeting, "contacts": data["contacts"], "event": data["event"], "clock": store.get(db, NAMESPACE, "clock", "current")}
    sources = []
    impact = None
    details = params
    if action == "boss.meeting.confirm":
        draft = store.get(db, NAMESPACE, "meeting_draft", object_id)
        impact, review = MeetingAPI(store)._preview(db, data, draft["details"])
        if params["meeting_id"] != object_id or params["meeting_version"] != object_version or params["draft_version"] != draft["version"] or draft["state"] != "DRAFT" or draft["meeting_version"] != object_version or params["review_sha256"] != draft["review_sha256"] or review != draft["review_sha256"]:
            raise web.HTTPConflict(text="会议草稿或审阅内容已经变化")
        sources = [item["source_id"] for item in draft["details"]["source_refs"]]
        MeetingAPI(store)._clean(db, data, draft["details"])
        context["draft"] = draft
        details = draft["details"]
    elif action in {"boss.meeting.cancel", "boss.meeting.held"}:
        MeetingAPI._writable(meeting)
        if params["meeting_id"] != object_id or params["expected_version"] != object_version:
            raise web.HTTPConflict(text="会议版本已经变化")
        if not _is_text(params["reason"], 1200):
            raise web.HTTPBadRequest(text="必须明确本次本人决定依据")
        if action == "boss.meeting.held" and (meeting.get("state", "DRAFT") != "SCHEDULED" or datetime.fromisoformat(context["clock"]["at"]) < datetime.fromisoformat(meeting["starts_at"])):
            raise web.HTTPConflict(text="只有已安排且开始时间已经到达的会议可以确认举行")
        sources = [source_id for source_id in meeting["material_ids"] if source_id != data["event"]["event_id"]]
        details = {"meeting_id": object_id, "version": object_version, "state": meeting.get("state", "DRAFT"), "starts_at": meeting["starts_at"], "reason": params["reason"]}
    elif action in {"boss.minutes.confirm", "boss.minutes.assignment.create"}:
        minute = store.get(db, NAMESPACE, "minutes", object_id)
        if params["meeting_id"] != object_id or minute["meeting_version"] != object_version:
            raise web.HTTPConflict(text="纪要所属会议已经变化")
        if action == "boss.minutes.confirm":
            if minute["state"] != "DRAFT_REVIEW" or params["expected_version"] != minute["version"] or (params["source_id"], params["source_version"]) != (minute["source_id"], minute["source_version"]):
                raise web.HTTPConflict(text="纪要草稿或来源已经变化")
        else:
            entry = next((item for item in minute["entries"] if item["entry_id"] == params["entry_id"]), None)
            if minute["state"] != "CONFIRMED" or params["minute_version"] != minute["version"] or entry is None or entry["kind"] != "ASSIGNMENT_DRAFT":
                raise web.HTTPConflict(text="纪要交办条目不可用")
            link = object_id + ":v" + minute["version"] + ":" + entry["entry_id"]
            if existing(db, "minutes_assignment_link", link) is not None:
                raise web.HTTPConflict(text="纪要条目已经关联交办")
            sources.append("finance-note")
        sources.append(minute["source_id"])
        object_id, object_version = minute["minute_id"], minute["version"]
        context["minutes"] = minute
        details = minute
    else:
        if params["related_meeting_id"] != meeting["meeting_id"] or params["related_event_ids"] != [data["event"]["event_id"]] or params["source_refs"] != ["finance-note"] or params["content_version"] != "1":
            raise web.HTTPConflict(text="交办关联对象或来源不匹配")
        sources = params["source_refs"]
    if action in {"boss.minutes.assignment.create", "boss.assignment.create"}:
        if not _is_text(params["purpose"]) or params["coordinator_id"] != "coordinator-1" or not any(item["contact_id"] == params["coordinator_id"] and item["valid_from"] <= datetime.fromisoformat(context["clock"]["at"]).date().isoformat() <= item["valid_until"] for item in data["contacts"]):
            raise web.HTTPBadRequest(text="交办内容或负责人无效")
        evidence = params["evidence_requirements"]
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8 or not all(_is_text(item, 160) for item in evidence) or _aware_due(params["due_at"], params["timezone"]) <= datetime.fromisoformat(context["clock"]["at"]):
            raise web.HTTPBadRequest(text="交办期限或证据要求无效")
    sources = list(dict.fromkeys(sources))
    pins = {source_id: (version, digest) for source_id, version, digest in proof.source_pins}
    if not sources or any(source_id not in pins for source_id in sources):
        raise web.HTTPForbidden(text="业务来源未获当前运行选择")
    bound = []
    for source_id in sources:
        document = require_current_business_source(store, db, proof.namespace, proof.owner_id, source_id)
        version, digest = pins[source_id]
        if document["version"] != version or checksum(document) != digest:
            raise web.HTTPConflict(text="业务来源已经变化")
        bound.append({"source_id": source_id, "version": version, "source_sha256": digest})
    if action in {"boss.meeting.cancel", "boss.meeting.held"}:
        for ref in meeting.get("source_refs", []):
            if ref["source_id"] not in pins or pins[ref["source_id"]][0] != ref["version"]:
                raise web.HTTPConflict(text="会议材料版本已经变化")
    if action in {"boss.minutes.confirm", "boss.minutes.assignment.create"} and pins[minute["source_id"]][0] != minute["source_version"]:
        raise web.HTTPConflict(text="纪要来源版本已经变化")
    if action == "boss.minutes.assignment.create":
        document = require_current_business_source(store, db, proof.namespace, proof.owner_id, minute["source_id"])
        if entry["source_id"] != minute["source_id"] or entry["source_version"] != minute["source_version"] or entry["source_anchor"] not in document["content"]:
            raise web.HTTPConflict(text="纪要交办原文不可核查")
    return {"action": action, "params": params, "object_id": object_id, "object_revision": object_version,
            "goal_revision": run["goal_revision"], "source_refs": bound, "context_digest": checksum(context),
            "impact": impact, "details": details, "owner_decision_required": True, "business_authority_granted": False}
