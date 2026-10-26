import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, now, require
from boss_source_policy import source_validity

DEFINITION = "FC04-ALERT-1"
GENERATOR = "BUSINESS_ALERT_INPUT"
MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "specs/business-alert-input.json").read_text())
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "specs/business-alert.schema.json").read_text())


def validate(name, value):
    require(not list(Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}, format_checker=FormatChecker()).iter_errors(value)), "经营提醒输入不符合Schema", web.HTTPBadRequest)
    return value


def get(db, ns, kind, identifier):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (ns, kind, identifier)).fetchone()
    return json.loads(row[0]) if row else None


def items(db, ns, kind):
    return [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (ns, kind)).fetchall()]


def owner_role(role):
    require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
    require(role == "BOSS", "经营提醒及本人决定仅限本人", web.HTTPForbidden)


def report_adoption(db, ns, data, clock, document):
    from boss_v7_metrics import policy_fingerprint
    if document.get("metric_policy_sha256", checksum({})) != policy_fingerprint(db, ns):
        return {"state": "NEEDS_REIMPORT", "dependencies": [{"source_id": "metric-configuration", "status": "CHANGED"}]}
    metadata_valid = document.get("owner_id") == data["owner_id"] and document.get("execution_namespace") == ns and all(document.get(field) == data[field] for field in ("dataset_id", "dataset_version"))
    initial = get(db, ns, "initial", "snapshot")
    references = document.get("input_source_refs")
    fingerprints = document.get("input_source_fingerprints")
    if not metadata_valid or document.get("initial_snapshot_sha256") != checksum(initial) or not isinstance(references, list) or len(references) != 1 or not isinstance(fingerprints, dict):
        return {"state": "NEEDS_REIMPORT", "dependencies": []}
    ref = references[0]
    if ref.get("source_id") != "finance-note" or set(fingerprints) != {"finance-note"}:
        return {"state": "NEEDS_REIMPORT", "dependencies": []}
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=? AND json_extract(body,'$.access_scope')=?", (ns, ref["source_id"], data["owner_id"])).fetchone()
    source = json.loads(row[0]) if row else None
    status = source_validity(source, clock) if source else "MISSING_OR_FORBIDDEN"
    if source and status == "VALID" and (source["version"] != ref.get("version") or checksum(source) != fingerprints[ref["source_id"]]):
        status = "CHANGED"
    return {"state": "CURRENT" if status == "VALID" else "NEEDS_REIMPORT", "dependencies": [{"source_id": ref["source_id"], "version": ref.get("version"), "status": status}]}


def effective_rule(store, db, ns, data):
    rule = get(db, ns, "business_alert_rule", "current")
    if rule is None or rule["state"] != "ACTIVE":
        return rule, "RULE_NOT_ENABLED"
    require(rule["owner_id"] == data["owner_id"] and rule["namespace"] == ns, "经营规则归属不符", web.HTTPForbidden)
    if rule["created_by_role"] == "MAINTAINER":
        require(rule["definition_version"] == DEFINITION and rule["configuration"] == MANIFEST["configuration"], "维护不能扩大本人关注规则", web.HTTPForbidden)
    else:
        auth = store.get(db, ns, "authorization", rule["authorization_id"])
        require(auth["owner_id"] == data["owner_id"] and auth["scope"] == ns and auth["issuer_identity"] == "BOSS"
                and auth["issuer"] == data["owner_id"] and auth["action"] == "business_alert.rule.activate"
                and auth["target_id"] == "business-alert-rule" and auth["content_version"] == rule["version"]
                and auth["payload"]["configuration_sha256"] == checksum(rule["configuration"]), "当前规则缺少匹配本人确认", web.HTTPForbidden)
        if auth["revoked"]:
            return rule, "RULE_AUTHORIZATION_REVOKED"
    return rule, "ACTIVE"


def sources(store, db, ns, data, event):
    statuses, documents = [], {}
    clock = store.get(db, ns, "clock", "current")["at"]
    for reference in event["source_refs"]:
        sid = reference["source_id"]
        metadata = db.execute("SELECT json_extract(body,'$.access_scope'),json_extract(body,'$.version') FROM objects WHERE namespace=? AND kind='document' AND id=?", (ns, sid)).fetchone()
        status = "MISSING" if metadata is None else "FORBIDDEN" if metadata[0] != data["owner_id"] else None
        document = None
        if status is None:
            document = store.get(db, ns, "document", sid)
            status = source_validity(document, clock)
            if status == "VALID" and document.get("simulation_definition") == DEFINITION and report_adoption(db, ns, data, clock, document)["state"] != "CURRENT":
                status = "NEEDS_REIMPORT"
            if status == "VALID" and (document["version"] != reference["version"] or checksum(document) != event["source_fingerprints"][sid]):
                status = "SOURCE_CHANGED"
        row = {"source_id": sid, "version": reference["version"], "current_version": metadata[1] if metadata else None, "status": status}
        if status == "VALID":
            row.update({field: document.get(field) for field in ("author_contact_id", "published_at", "observed_at", "valid_from", "valid_until", "original_locator", "source_type")})
            documents[sid] = document
        statuses.append(row)
    return statuses, documents


def classification(store, db, ns, event, cfg):
    facts = event["facts"]
    if not facts["complete"] or facts["confidence"] != "HIGH" or facts["handler_id"] is None:
        return {"phase": "UNKNOWN", "reason": "INSUFFICIENT_CURRENT_EVIDENCE", "duration_seconds": None}
    business_at = datetime.fromisoformat(store.get(db, ns, "clock", "current")["at"])
    business_date = business_at.astimezone(ZoneInfo(cfg["timezone"])).date().isoformat()
    data = store.get(db, ns, "initial", "snapshot")
    handlers = [row for row in data["contacts"] if row["contact_id"] == facts["handler_id"]]
    if len(handlers) != 1 or not handlers[0]["valid_from"] <= business_date <= handlers[0]["valid_until"]:
        return {"phase": "UNKNOWN", "reason": "HANDLER_NOT_CURRENT", "duration_seconds": None}
    if (business_at - datetime.fromisoformat(event["observed_at"])).total_seconds() > cfg["check_interval_seconds"]:
        return {"phase": "UNKNOWN", "reason": "OBSERVATION_NOT_UPDATED", "duration_seconds": None}
    drop = -Decimal(facts["change_pp"]) >= Decimal(cfg["threshold_pp"])
    rows = [row for row in items(db, ns, "business_alert_observation") if row["event_id"] == event["event_id"]]
    rows.sort(key=lambda row: int(row["version"]), reverse=True)
    since, previous = event["observed_at"], datetime.fromisoformat(event["observed_at"])
    for row in rows:
        other = row["facts"]
        at = datetime.fromisoformat(row["observed_at"])
        if previous < at or (previous - at).total_seconds() > cfg["check_interval_seconds"] or row["basis_sha256"] != event["basis_sha256"]:
            break
        if not other["complete"] or other["confidence"] != "HIGH" or other["handler_id"] is None or (-Decimal(other["change_pp"]) >= Decimal(cfg["threshold_pp"])) != drop:
            break
        since, previous = row["observed_at"], at
    duration = int((datetime.fromisoformat(event["observed_at"]) - datetime.fromisoformat(since)).total_seconds())
    if facts["participation"] == "INFORM_ONLY":
        phase, reason = "SUMMARY", "GENERAL_PROGRESS_SUMMARY"
    elif facts["participation"] == "CROSS_FUNCTION_RESOURCE_SHORTAGE":
        phase, reason = "IMMEDIATE", "CROSS_FUNCTION_RESOURCES_REQUIRED"
    elif drop:
        phase, reason = ("BREACH", "CURRENT_THRESHOLD_AND_PARTICIPATION") if duration >= cfg["duration_seconds"] else ("WAITING", "DURATION_NOT_MET")
    else:
        phase, reason = ("RECOVERY", "RECOVERY_DURATION_MET") if duration >= cfg["recovery_seconds"] else ("WAITING", "RECOVERY_DURATION_NOT_MET")
    return {"phase": phase, "reason": reason, "duration_seconds": duration, "condition_since": since}


def material(store, db, ns, data, event):
    require(event.get("generated_by") == GENERATOR, "当前对象缺少经营提醒定义", web.HTTPNotFound)
    require(event["owner_id"] == data["owner_id"] and event["execution_namespace"] == ns
            and event["dataset_id"] == data["dataset_id"] and event["dataset_version"] == data["dataset_version"], "经营提醒不属于当前范围", web.HTTPForbidden)
    rule, rule_state = effective_rule(store, db, ns, data)
    source_states, documents = sources(store, db, ns, data, event)
    valid = all(row["status"] == "VALID" for row in source_states)
    evaluation = classification(store, db, ns, event, rule["configuration"]) if valid and rule_state == "ACTIVE" else {
        "phase": "UNKNOWN", "reason": rule_state if rule_state != "ACTIVE" else "SOURCE_NOT_CURRENT", "duration_seconds": None}
    reminder = get(db, ns, "reminder", event["event_id"])
    reminder_auth = get(db, ns, "authorization", reminder["authorization_id"]) if reminder and reminder.get("authorization_id") else None
    plan = get(db, ns, "owner_plan", event["owner_plan_id"]) if event.get("owner_plan_id") else None
    plan_auth = get(db, ns, "authorization", plan["authorization_id"]) if plan else None
    from boss_owner_preferences import effective_owner_notice
    notice = effective_owner_notice(db, data, ns)
    notice_ref = {"version": notice["version"], "configuration": notice["content"]} if notice else None
    technical = get(db, ns, "rules", "current")
    notification = get(db, ns, "notification", event["event_id"] + ":alert")
    tracking = get(db, ns, "business_alert_tracking", event["event_id"])
    episode = tracking["episode"] if tracking else 0
    measures = [{"kind": "task", "task_id": task["task_id"], "version": task["version"], "status": task["status"], "coordinator_id": task["coordinator_id"], "due_at": task["due_at"]}
                for task in items(db, ns, "task") if event["event_id"] in task.get("related_event_ids", [])]
    if plan:
        require(plan["owner_id"] == data["owner_id"], "本人计划不属于当前范围", web.HTTPForbidden)
        measures.append({"kind": "owner_plan", "plan_id": plan["plan_id"], "version": plan["version"], "state": plan["state"], "not_before": plan["not_before"], "authorization_revoked": plan_auth["revoked"]})
    if reminder:
        measures.append({"kind": "reminder", "version": reminder["version"], "state": reminder["state"], "until": reminder.get("until"), "authorization_revoked": reminder_auth["revoked"] if reminder_auth else None})
    meeting = get(db, ns, "meeting", data["meeting"]["meeting_id"]) or data["meeting"]
    meeting_refs = meeting.get("source_refs", [{"source_id": sid, "version": next((row["version"] for row in data["documents"] if row["source_id"] == sid), None)}
        for sid in meeting.get("material_ids", []) if sid != data["event"]["event_id"]])
    meeting_binding = []
    for ref in meeting_refs:
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=? AND json_extract(body,'$.access_scope')=?", (ns, ref["source_id"], data["owner_id"])).fetchone()
        doc = json.loads(row[0]) if row else None
        status = source_validity(doc, store.get(db, ns, "clock", "current")["at"]) if doc else "MISSING_OR_FORBIDDEN"
        if doc and status == "VALID" and doc["version"] != ref["version"]:
            status = "SOURCE_CHANGED"
        meeting_binding.append({**ref, "status": status, "sha256": checksum(doc) if doc and status == "VALID" else None})
    summary = get(db, ns, "business_alert_summary", event["event_id"])
    binding = {"event": event, "rule": rule, "rule_state": rule_state, "sources": source_states, "documents": documents,
        "reminder": reminder, "reminder_authorization": reminder_auth, "plan": plan, "plan_authorization": plan_auth, "technical": technical, "notice": notice_ref,
        "schedule": store.get(db, ns, "schedule", "current"), "notification": notification, "episode": episode, "measures": measures,
        "meeting": meeting, "meeting_sources": meeting_binding, "clock": store.get(db, ns, "clock", "current")}
    return {"source_type": "SIMULATED", "event_id": event["event_id"], "event_version": event["version"], "episode": episode, "state": event["state"],
        "facts": event["facts"] if valid else None, "observed_at": event["observed_at"], "data_as_of": event["data_as_of"] if valid else None,
        "adoption_state": "CURRENT" if valid else "NEEDS_REVIEW", "sources": source_states, "documents": list(documents.values()),
        "evaluation": evaluation, "business_rule": rule, "rule_state": rule_state, "technical_rule_version": technical["version"] if technical else None,
        "owner_notice_version": notice["version"] if notice else None, "reminder": reminder, "reminder_version": reminder["version"] if reminder else "0",
        "notification": notification if valid else None, "existing_measures": measures if valid else [],
        "summary": summary if valid and summary and summary["event_version"] == event["version"] else None,
        "meeting_reference": {"meeting_id": meeting["meeting_id"], "version": meeting["version"], "sources": meeting_binding,
            "adoption_state": "CURRENT" if all(row["status"] == "VALID" for row in meeting_binding) else "NEEDS_REVIEW"},
        "review_sha256": checksum(binding), "missing_fields": [row["status"] + ":" + row["source_id"] for row in source_states if row["status"] != "VALID"]
            + ([evaluation["reason"]] if evaluation["phase"] == "UNKNOWN" else []) + ["IMPACT_AMOUNT_NOT_PROVIDED"], "execution_owner": "CronService", "external_delivery_verified": False}


def record_dispatch(store, db, ns, result):
    identifier = checksum(result)
    if get(db, ns, "dispatch_history", identifier) is None:
        store.put(db, ns, "dispatch_history", identifier, {**result, "dispatch_id": identifier, "recorded_at": now()})
    store.put(db, ns, "dispatch", result["event_id"], {**result, "dispatch_id": identifier})
    return result
