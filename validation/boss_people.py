"""FR-10 deterministic people-meeting preparation and owner-confirmed agenda linking.

Only known employee/contact IDs and approved work sources are used. Matching a
display name does not identify a person. It neither creates employee accounts
nor edits the external meeting attendance or sends invitations.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from aiohttp import web

from business import checksum, now, require
from boss_owner_preferences import effective_owner_goals
from boss_meetings import meeting_materials

NS = "ui-check"


def _get(db, kind, key):
    row = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
        (NS, kind, key),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _list(db, kind):
    return [
        json.loads(row[0]) for row in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id",
            (NS, kind),
        ).fetchall()
    ]


def _contact(api, db, data, contact_id):
    require(isinstance(contact_id, str) and len(contact_id) <= 128,
            "必须使用联系人稳定 ID", web.HTTPBadRequest)
    rows = [p for p in data["contacts"] if p["contact_id"] == contact_id]
    require(len(rows) == 1, "该联系人标识无法唯一确定", web.HTTPBadRequest)
    person = rows[0]
    clock = api.store.get(db, NS, "clock", "current")["at"]
    day = datetime.fromisoformat(clock).date().isoformat()
    require(person["valid_from"] <= day <= person["valid_until"],
            "联系人当前职责已过有效期，请复核", web.HTTPForbidden)
    return {
        "contact_id": person["contact_id"],
        "name": person["name"],
        "organization": person["organization"],
        "responsibility": person["responsibility"],
        "valid_from": person["valid_from"],
        "valid_until": person["valid_until"],
    }


def _sources(api, db, data, refs):
    require(isinstance(refs, list) and len(refs) <= 8,
            "资料数量上限为8", web.HTTPBadRequest)
    used, sources = set(), []
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) == {"source_id", "version"},
                "必须逐条指定来源及当前版本", web.HTTPBadRequest)
        identifier, version = ref["source_id"], ref["version"]
        require(isinstance(identifier, str) and 0 < len(identifier) <= 128
                and identifier not in used
                and isinstance(version, str) and 0 < len(version) <= 40,
                "资料 ID 重复或版本不合法", web.HTTPBadRequest)
        used.add(identifier)
        doc = api.store.get(db, NS, "document", identifier)
        require(not doc.get("withdrawn")
                and doc.get("access_scope") == data["owner_id"]
                and doc.get("source_type") == "SIMULATED",
                "来源不在当前获准范围或已经撤销", web.HTTPForbidden)
        require(doc["version"] == version, "资料版本已变化", web.HTTPConflict)
        sources.append({
            "source_id": identifier, "version": version,
            "author_contact_id": doc.get("author_contact_id"),
            "published_at": doc.get("published_at"),
            "excerpt": doc.get("content", "")[:300],
            "source_type": "SIMULATED",
        })
    return sorted(sources, key=lambda x: x["source_id"])


def _work_facts(db, data, contact_id):
    tasks = []
    historical = data["historical_task"]
    if data["event"]["coordinator_id"] == contact_id:
        tasks.append({
            "task_id": historical["task_id"], "version": historical["version"],
            "status": historical["status"], "due_at": historical["due_at"],
            "evidence_requirements": historical["evidence_requirements"],
            "is_historical": True, "source_type": "SIMULATED",
        })
    for task in _list(db, "task"):
        if task.get("coordinator_id") != contact_id:
            continue
        tasks.append({
            "task_id": task["task_id"], "version": task["version"],
            "status": task["status"], "due_at": task.get("due_at"),
            "evidence_requirements": task.get("evidence_requirements", []),
            "is_historical": False, "source_type": "SIMULATED",
        })
    feedbacks = [{
        "feedback_id": feedback["feedback_id"],
        "task_id": feedback["task_id"], "kind": feedback["kind"],
        "author_contact_id": feedback.get("author_contact_id"),
        "evidence_source_ids": feedback.get("evidence_refs", []),
        "source_type": "SIMULATED",
    } for feedback in _list(db, "feedback")
        if feedback.get("author_contact_id") == contact_id
        and any(task["task_id"] == feedback.get("task_id") for task in tasks)]
    return {
        "tasks": sorted(tasks, key=lambda x: x["task_id"]),
        "feedback": sorted(feedbacks, key=lambda x: x["feedback_id"]),
        "questions": [{
            "task_id": task["task_id"],
            "text": "请核查此任务的当前进展、有效证据及待本人决定的问题",
            "question_is_generated_from_status_only": True,
        } for task in tasks if task["status"] not in ("CANCELED", "COMPLETED_CONFIRMED")],
    }


def _compile(api, db, data, contact_id, refs, purpose, meeting_id):
    data = meeting_materials(db, data)
    contact = _contact(api, db, data, contact_id)
    require(isinstance(purpose, str) and 0 < len(purpose.strip()) <= 1200,
            "会面目的不能为空或超限", web.HTTPBadRequest)
    require(meeting_id is None or meeting_id == data["meeting"]["meeting_id"],
            "所选会议超出当前获准范围", web.HTTPBadRequest)
    sources = _sources(api, db, data, refs)
    facts = _work_facts(db, data, contact_id)
    meeting = data["meeting"]
    return {
        "contact": contact, "purpose": purpose.strip(),
        "meeting": {
            "meeting_id": meeting_id, "version": meeting["version"] if meeting_id else None,
            "contact_is_participant": contact_id in meeting["participant_ids"] if meeting_id else False,
        },
        "goals": (list(effective_owner_goals(db,data)["content"]["goals"])
                  if effective_owner_goals(db,data) is not None
                  and effective_owner_goals(db,data)["content"]["scope"] in
                  ("OWNER_WORKSPACE","MEETING_PREP") else []),
        "sources": sources, **facts,
        "has_original_evidence": bool(sources),
        "external_meeting_updated": False,
        "personal_traits_inferred": False, "source_type": "SIMULATED",
    }


def _payload_refs(compiled):
    return [
        {"source_id": x["source_id"], "version": x["version"]}
        for x in compiled["sources"]
    ]


def prepare(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "brief_id", "expected_version",
        "contact_id", "purpose", "meeting_id", "source_refs",
    })
    identifier = payload["brief_id"]
    require(identifier is None or isinstance(identifier, str) and 0 < len(identifier) <= 128,
            "会面材料标识无效", web.HTTPBadRequest)
    previous = _get(db, "person_brief", identifier) if identifier else None
    require((previous is not None) if identifier else payload["expected_version"] == "0",
            "材料不存在或创建版本错误", web.HTTPConflict)
    if previous:
        require(previous["version"] == payload["expected_version"]
                and previous["linked_meeting_version"] is None,
                "会面材料已关联会议或版本变化，须先解除关联", web.HTTPConflict)
    compiled = _compile(api, db, data,
                        payload["contact_id"], payload["source_refs"],
                        payload["purpose"], payload["meeting_id"])
    if previous:
        api.store.put(db, NS, "person_brief_revision",
                      identifier + ":v" + previous["version"], previous)
    else:
        identifier = "people-" + str(uuid.uuid4())
    version = str(int(previous["version"]) + 1) if previous else "1"
    record = {
        "brief_id": identifier, "version": version,
        "state": "READY_FOR_REVIEW" if compiled["sources"] or compiled["tasks"] else "MATERIALS_MISSING",
        "compiled": compiled, "compiled_sha256": checksum(compiled),
        "linked_meeting_version": None,
        "prepared_at": now(), "source_type": "SIMULATED",
    }
    api.store.put(db, NS, "person_brief", identifier, record)
    return {
        "brief_id": identifier, "version": version, "state": record["state"],
        "source_count": len(compiled["sources"]),
        "task_count": len(compiled["tasks"]),
        "linked_meeting_version": None,
        "meeting_unchanged": True, "invitation_sent": False,
    }


def attach(api, db, data, payload):
    data = meeting_materials(db, data)
    api._exact(payload, {
        "client_request_id", "brief_id", "expected_version",
        "meeting_id", "meeting_version", "compiled_sha256",
    })
    record = api.store.get(db, NS, "person_brief", payload["brief_id"])
    meeting = data["meeting"]
    require(payload["meeting_id"] == meeting["meeting_id"]
            and payload["meeting_version"] == meeting["version"],
            "会议标识或版本已经变化", web.HTTPConflict)
    require(meeting.get("state", "DRAFT") not in ("CANCELED", "HELD"), "已结束的会议不能增加会面议题")
    require(record["version"] == payload["expected_version"]
            and record["state"] in ("READY_FOR_REVIEW", "MATERIALS_MISSING")
            and record["compiled_sha256"] == payload["compiled_sha256"],
            "材料版本、状态或摘要不一致", web.HTTPConflict)
    old = record["compiled"]
    require(old["meeting"]["meeting_id"] == meeting["meeting_id"],
            "该会面尚未选择并核查当前会议", web.HTTPConflict)
    live = _compile(api, db, data,
                    old["contact"]["contact_id"], _payload_refs(old),
                    old["purpose"], meeting["meeting_id"])
    require(checksum(live) == record["compiled_sha256"],
            "负责人职责、任务、反馈或资料已变化，请重新准备材料", web.HTTPConflict)
    require(record["linked_meeting_version"] is None,
            "当前材料已加入会议议题，不得重复", web.HTTPConflict)
    authorization_id = api._authorize(db, "people.attach_meeting", {
        "brief_id": record["brief_id"], "brief_version": record["version"],
        "meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"],
        "content_sha256": record["compiled_sha256"],
    }, record["brief_id"], record["version"])
    api.store.put(db, NS, "person_brief_revision",
                  record["brief_id"] + ":v" + record["version"], record)
    record["linked_meeting_version"] = meeting["version"]
    record["version"] = str(int(record["version"]) + 1)
    record["state"] = "ATTACHED_TO_MEETING_AGENDA"
    record["updated_at"] = now()
    record["authorization_id"] = authorization_id
    api.store.put(db, NS, "person_brief", record["brief_id"], record)
    return {
        "brief_id": record["brief_id"], "version": record["version"],
        "state": record["state"], "meeting_id": meeting["meeting_id"],
        "authorization_id": authorization_id, "meeting_attendees_changed": False,
        "meeting_agenda_linked": True, "invitation_sent": False,
        "external_calendar_updated": False,
    }


def detach(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "brief_id", "expected_version", "reason",
    })
    reason = payload["reason"]
    require(isinstance(reason, str) and 0 < len(reason.strip()) <= 400,
            "必须说明从会议议题移除的原因", web.HTTPBadRequest)
    record = api.store.get(db, NS, "person_brief", payload["brief_id"])
    require(record["version"] == payload["expected_version"]
            and record["state"] == "ATTACHED_TO_MEETING_AGENDA"
            and record["linked_meeting_version"] is not None,
            "材料版本已变化或并未关联会议", web.HTTPConflict)
    auth_id = api._authorize(db, "people.detach_meeting", {
        "brief_id": record["brief_id"], "version": record["version"],
        "reason_sha256": checksum(reason.strip()),
    }, record["brief_id"], record["version"])
    api.store.put(db, NS, "person_brief_revision",
                  record["brief_id"] + ":v" + record["version"], record)
    record["linked_meeting_version"] = None
    record["version"] = str(int(record["version"]) + 1)
    record["state"] = "UNLINKED_FROM_MEETING_AGENDA"
    record["updated_at"] = now()
    record["authorization_id"] = auth_id
    record["unlink_reason"] = reason.strip()
    api.store.put(db, NS, "person_brief", record["brief_id"], record)
    return {
        "brief_id": record["brief_id"], "version": record["version"],
        "state": record["state"], "authorization_id": auth_id,
        "meeting_agenda_linked": False, "external_calendar_updated": False,
    }


def meeting_impacts(db, meeting):
    result = []
    for row in _list(db, "person_brief"):
        if row["linked_meeting_version"] is None or row["compiled"]["meeting"]["meeting_id"] != meeting["meeting_id"]:
            continue
        pins = [
            {"source_id": item["source_id"], "version": item["version"]}
            for item in row["compiled"]["sources"]
        ]
        valid = row["linked_meeting_version"] == meeting["version"] and meeting.get("state", "DRAFT") not in ("CANCELED", "HELD")
        for pin in pins:
            source = _get(db, "document", pin["source_id"])
            if not source or source.get("withdrawn") or source.get("version") != pin["version"] or source.get("access_scope") != "boss-1":
                valid = False
        result.append({
            "brief_id": row["brief_id"], "version": row["version"],
            "contact_id": row["compiled"]["contact"]["contact_id"],
            "meeting_version": row["linked_meeting_version"],
            "pinned_source_versions": pins,
            "source_state": "CURRENT" if valid else "NEEDS_REVIEW",
        })
    return sorted(result, key=lambda p: p["brief_id"])


def projection(api, db, data):
    data = meeting_materials(db, data)
    results = []
    for brief in _list(db, "person_brief"):
        row = dict(brief)
        saved = row["compiled"]
        try:
            live = _compile(
                api, db, data,
                saved["contact"]["contact_id"], _payload_refs(saved),
                saved["purpose"], saved["meeting"]["meeting_id"],
            )
            fresh = checksum(live) == row["compiled_sha256"]
        except (web.HTTPException, ValueError, KeyError, TypeError):
            fresh = False
        row["live_evidence_current"] = fresh
        if not fresh:
            # Historical source/version metadata can remain, but revoked or
            # superseded source text may not be reused by the current UI.
            row["compiled"] = {
                **saved,
                "sources": [{**item, "excerpt": None}
                            for item in saved["sources"]],
                "evidence_redacted_until_review": True,
            }
        results.append(row)
    clock = api.store.get(db, NS, "clock", "current")
    return {
        "briefs": results,
        "contacts": [{
            "contact_id": c["contact_id"], "name": c["name"],
            "organization": c["organization"], "responsibility": c["responsibility"],
            "valid_from": c["valid_from"], "valid_until": c["valid_until"],
        } for c in data["contacts"]],
        "meeting": {
            "meeting_id": data["meeting"]["meeting_id"],
            "version": data["meeting"]["version"],
            "participant_ids": data["meeting"]["participant_ids"],
            "starts_at": data["meeting"]["starts_at"],
        },
        "business_clock": clock["at"],
        "employee_accounts_created": False,
        "external_meeting_invitation_sent": False,
        "visibility": "BOSS_ONLY",
    }
