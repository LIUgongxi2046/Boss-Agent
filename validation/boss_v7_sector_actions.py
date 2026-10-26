# 专题后续动作：决定记录、复查计划、会议草稿与资源选项。
# 每项动作先核查当前查询、来源版本与本人范围，再保存对应记录。
from __future__ import annotations

import json
import uuid

from aiohttp import web

from business import now, require
from boss_sector_api import SECTORS, query_id_for
from boss_v7_store import NAMESPACE

DECISION_LABELS = {"记录资源决定", "调整项目", "记录安排"}
RECORD_KIND = "sector_followup"


def _text(value, label, maximum=2400):
    require(isinstance(value, str) and 0 < len(value.strip()) <= maximum, label + "不能为空或过长", web.HTTPBadRequest)
    return value.strip()


def _reference(payload, page, snapshot):
    require(set(payload) == {"client_request_id", "page_id", "execution_namespace", "dataset_version",
                             "query_id", "action_code", "filters", "overview_reference",
                             "source_refs", "purpose", "decision"}, "专题决定字段不完整", web.HTTPBadRequest)
    require(payload["page_id"] == page and page in SECTORS, "专题页面不属于当前范围", web.HTTPBadRequest)
    require(payload["execution_namespace"] == NAMESPACE, "执行空间不一致", web.HTTPConflict)
    require(payload["dataset_version"] == snapshot["dataset_version"], "数据集版本已经变化", web.HTTPConflict)
    filters = payload["filters"]
    overview = payload["overview_reference"]
    require(isinstance(filters, dict) and all(isinstance(key, str) and isinstance(value, str) for key, value in filters.items()),
            "筛选条件无效", web.HTTPBadRequest)
    require(overview is None or isinstance(overview, dict), "经营范围引用无效", web.HTTPBadRequest)
    require(payload["query_id"] == query_id_for(page, filters, overview), "专题查询版本已经变化，请重新读取", web.HTTPConflict)
    require(payload["action_code"] in DECISION_LABELS, "专题决定动作不在获准范围", web.HTTPBadRequest)
    purpose = _text(payload["purpose"], "本次目的")
    decision = _text(payload["decision"], "决定与适用条件")
    return purpose, decision, filters, overview


def save_decision(api, db, snapshot, payload):
    page = payload.get("page_id")
    purpose, decision, filters, overview = _reference(payload, page, snapshot)
    document = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?",
                          (NAMESPACE, "sector-" + page.lower() + "-a")).fetchone()
    require(document is not None, "当前专题模拟资料尚未生成", web.HTTPConflict)
    document = json.loads(document[0])
    require(isinstance(payload["source_refs"], list) and payload["source_refs"], "需要当前来源引用", web.HTTPBadRequest)
    for reference in payload["source_refs"]:
        require(isinstance(reference, dict) and reference.get("source_id") == document["source_id"]
                and reference.get("version") == document["version"], "来源版本已经变化", web.HTTPConflict)
    identifier = "sector-" + str(uuid.uuid4())
    record = {
        "record_id": identifier, "version": "1", "kind": "DECISION",
        "title": payload["action_code"], "state": "RECORDED", "created_at": now(),
        "page_id": page, "query_id": payload["query_id"], "dataset_version": snapshot["dataset_version"],
        "namespace": NAMESPACE, "purpose": purpose, "decision": decision,
        "filters": filters, "overview_reference": overview,
        "source_ids": [document["source_id"]], "source_refs": payload["source_refs"],
        "task_id": None, "plan_id": None, "meeting_id": None, "source_type": "SIMULATED",
    }
    api.store.put(db, NAMESPACE, RECORD_KIND, identifier, record)
    return {"record_id": identifier, "version": "1", "record_version": "1", "state": "RECORDED",
            "kind": "DECISION", "title": record["title"], "created_at": record["created_at"],
            "page_id": page, "query_id": record["query_id"], "execution_namespace": NAMESPACE,
            "action_code": payload["action_code"], "messages_sent": 0, "external_channel_invoked": False,
            "source_ids": record["source_ids"], "task_id": None, "plan_id": None, "meeting_id": None}


def followups(db, page):
    rows = []
    for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id",
                          (NAMESPACE, RECORD_KIND)).fetchall():
        record = json.loads(row[0])
        if record.get("page_id") != page:
            continue
        rows.append({"record_id": record["record_id"], "version": record["version"],
                     "kind": record["kind"], "title": record["title"], "state": record["state"],
                     "created_at": record["created_at"], "task_id": record.get("task_id"),
                     "plan_id": record.get("plan_id"), "meeting_id": record.get("meeting_id"),
                     "source_ids": record.get("source_ids", [])})
    rows.sort(key=lambda item: item["created_at"], reverse=True)
    return rows


REVIEW_LABELS = {"安排复查", "安排后续查询", "继续验证", "准备经营复查"}


def schedule_review(api, db, snapshot, payload):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo, available_timezones
    require(set(payload) == {"client_request_id", "page_id", "execution_namespace", "dataset_version",
                             "query_id", "action_code", "filters", "overview_reference", "source_refs",
                             "purpose", "timezone", "coordinator_id", "coordinator_version",
                             "due_at", "expected_output", "evidence_requirements"},
            "专题复查字段不完整", web.HTTPBadRequest)
    page = payload["page_id"]
    require(page in SECTORS, "专题页面不属于当前范围", web.HTTPBadRequest)
    require(payload["execution_namespace"] == NAMESPACE, "执行空间不一致", web.HTTPConflict)
    require(payload["dataset_version"] == snapshot["dataset_version"], "数据集版本已经变化", web.HTTPConflict)
    filters, overview = payload["filters"], payload["overview_reference"]
    require(isinstance(filters, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in filters.items()),
            "筛选条件无效", web.HTTPBadRequest)
    require(overview is None or isinstance(overview, dict), "经营范围引用无效", web.HTTPBadRequest)
    require(payload["query_id"] == query_id_for(page, filters, overview),
            "专题查询版本已经变化，请重新读取", web.HTTPConflict)
    require(payload["action_code"] in REVIEW_LABELS, "专题复查动作不在获准范围", web.HTTPBadRequest)
    document = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?",
                          (NAMESPACE, "sector-" + page.lower() + "-a")).fetchone()
    require(document is not None, "当前专题模拟资料尚未生成", web.HTTPConflict)
    document = json.loads(document[0])
    require(isinstance(payload["source_refs"], list)
            and payload["source_refs"] == [{"source_id": document["source_id"], "version": document["version"]}],
            "来源版本已经变化", web.HTTPConflict)
    purpose = payload["purpose"]
    output = payload["expected_output"]
    require(isinstance(purpose, str) and 0 < len(purpose.strip()) <= 400, "复查目的为空或过长", web.HTTPBadRequest)
    require(isinstance(output, str) and 0 < len(output.strip()) <= 600, "预期产物为空或过长", web.HTTPBadRequest)
    require(payload["coordinator_id"] == "coordinator-1"
            and payload["coordinator_version"] == "1", "复查负责人无效或版本已经变化", web.HTTPConflict)
    require(payload["timezone"] in available_timezones(), "复查时区无效", web.HTTPBadRequest)
    due = datetime.fromisoformat(payload["due_at"])
    clock = datetime.fromisoformat(api.store.get(db, NAMESPACE, "clock", "current")["at"])
    require(due.tzinfo is not None and due.utcoffset() == due.astimezone(ZoneInfo(payload["timezone"])).utcoffset(),
            "复查时间必须与时区一致", web.HTTPBadRequest)
    require(clock < due <= clock + timedelta(days=366), "复查时间无效", web.HTTPBadRequest)
    evidence = [line.strip() for line in payload["evidence_requirements"].splitlines() if line.strip()]
    require(1 <= len(evidence) <= 8 and all(0 < len(item) <= 160 for item in evidence),
            "证据要求缺少或无效", web.HTTPBadRequest)
    identifier = "sector-" + str(uuid.uuid4())
    event_id = "sector-review-" + str(uuid.uuid4())
    plan_id = "sector-review-plan-" + str(uuid.uuid4())
    plan_content = {"plan_id": plan_id, "event_ids": [event_id], "timezone": payload["timezone"],
                    "not_before": payload["due_at"], "purpose": "专题复查：" + purpose.strip()}
    authorization_id = api._authorize(db, "owner_plan.save", plan_content, plan_id, "1")
    api.store.put(db, NAMESPACE, "owner_plan", plan_id, {
        **plan_content, "version": "1", "event_versions": {event_id: "1"}, "state": "ACTIVE",
        "authorization_id": authorization_id, "owner_id": snapshot["owner_id"],
        "source_type": "SIMULATED", "updated_at": now(), "execution_owner": "CronService",
    })
    api.store.put(db, NAMESPACE, "event", event_id, {
        "event_id": event_id, "version": "1", "state": "OPEN", "impact": "NORMAL",
        "due_at": payload["due_at"], "owner_id": snapshot["owner_id"], "owner_plan_id": plan_id,
        "source_type": "SIMULATED", "generated_by": "SECTOR_REVIEW",
        "source_refs": [{"source_id": document["source_id"], "version": document["version"]}],
    })
    if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='rules' AND id='current'",
                  (NAMESPACE,)).fetchone() is None:
        api.store.put(db, NAMESPACE, "rules", "current", {
            "version": "1", "cooldown_seconds": 3600, "quiet_start": 22, "quiet_end": 7,
            "timezone": "Asia/Shanghai", "important_escalation": False,
        })
    record = {
        "record_id": identifier, "version": "1", "kind": "REVIEW", "title": payload["action_code"],
        "state": "REVIEW_SCHEDULED", "created_at": now(), "page_id": page,
        "query_id": payload["query_id"], "dataset_version": snapshot["dataset_version"],
        "namespace": NAMESPACE, "purpose": purpose.strip(), "expected_output": output.strip(),
        "coordinator_id": payload["coordinator_id"], "due_at": payload["due_at"], "timezone": payload["timezone"],
        "evidence_requirements": evidence, "source_ids": [document["source_id"]],
        "source_refs": payload["source_refs"], "task_id": None, "plan_id": plan_id,
        "event_id": event_id, "meeting_id": None,
        "scheduled_by_plan_service": True, "source_type": "SIMULATED",
    }
    api.store.put(db, NAMESPACE, RECORD_KIND, identifier, record)
    return {"record_id": identifier, "version": "1", "record_version": "1", "state": "REVIEW_SCHEDULED",
            "kind": "REVIEW", "title": payload["action_code"], "created_at": record["created_at"],
            "page_id": page, "query_id": payload["query_id"], "execution_namespace": NAMESPACE,
            "action_code": payload["action_code"], "messages_sent": 0, "external_channel_invoked": False,
            "source_ids": record["source_ids"], "task_id": None, "plan_id": plan_id, "meeting_id": None}


MEETING_LABELS = {"准备会面", "准备跨时区会议"}


def prepare_meeting(api, db, snapshot, payload):
    from datetime import datetime
    from zoneinfo import ZoneInfo, available_timezones
    require(set(payload) == {"client_request_id", "page_id", "execution_namespace", "dataset_version",
                             "query_id", "action_code", "filters", "overview_reference", "source_refs",
                             "purpose", "timezone", "attendee_refs", "starts_at", "ends_at", "location"},
            "专题会议字段不完整", web.HTTPBadRequest)
    page = payload["page_id"]
    require(page in SECTORS, "专题页面不属于当前范围", web.HTTPBadRequest)
    require(payload["execution_namespace"] == NAMESPACE, "执行空间不一致", web.HTTPConflict)
    require(payload["dataset_version"] == snapshot["dataset_version"], "数据集版本已经变化", web.HTTPConflict)
    filters, overview = payload["filters"], payload["overview_reference"]
    require(isinstance(filters, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in filters.items()),
            "筛选条件无效", web.HTTPBadRequest)
    require(overview is None or isinstance(overview, dict), "经营范围引用无效", web.HTTPBadRequest)
    require(payload["query_id"] == query_id_for(page, filters, overview),
            "专题查询版本已经变化，请重新读取", web.HTTPConflict)
    require(payload["action_code"] in MEETING_LABELS, "专题会议动作不在获准范围", web.HTTPBadRequest)
    purpose = payload["purpose"]
    require(isinstance(purpose, str) and 0 < len(purpose.strip()) <= 400, "会议目的为空或过长", web.HTTPBadRequest)
    location = payload["location"]
    require(isinstance(location, str) and 0 < len(location.strip()) <= 500, "会议地点为空或过长", web.HTTPBadRequest)
    require(payload["timezone"] in available_timezones(), "会议时区无效", web.HTTPBadRequest)
    starts = datetime.fromisoformat(payload["starts_at"])
    ends = datetime.fromisoformat(payload["ends_at"])
    clock = datetime.fromisoformat(api.store.get(db, NAMESPACE, "clock", "current")["at"])
    zone = ZoneInfo(payload["timezone"])
    require(all(moment.tzinfo is not None and moment.utcoffset() == moment.astimezone(zone).utcoffset()
                for moment in (starts, ends)), "会议时间必须与时区一致", web.HTTPBadRequest)
    require(clock < starts < ends, "会议时间无效", web.HTTPBadRequest)
    contacts = {row["contact_id"]: row for row in snapshot["contacts"]}
    attendee_refs = payload["attendee_refs"]
    require(isinstance(attendee_refs, list) and 1 <= len(attendee_refs) <= 8
            and all(isinstance(row, dict) and set(row) == {"contact_id", "version"} for row in attendee_refs),
            "参会人无效", web.HTTPBadRequest)
    seen = set()
    today = clock.date().isoformat()
    for row in attendee_refs:
        contact = contacts.get(row["contact_id"])
        require(contact is not None and row["version"] == "1" and row["contact_id"] not in seen
                and contact["valid_from"] <= today <= contact["valid_until"], "参会人不在当前有效目录", web.HTTPConflict)
        seen.add(row["contact_id"])
    source_ids = []
    for reference in payload["source_refs"]:
        require(isinstance(reference, dict) and set(reference) == {"source_id", "version"},
                "来源字段无效", web.HTTPBadRequest)
        document = api.store.get(db, NAMESPACE, "document", reference["source_id"])
        require(document.get("version") == reference["version"]
                and document.get("access_scope") == snapshot["owner_id"]
                and not document.get("withdrawn") and document.get("source_type") == "SIMULATED",
                "来源不在当前获准范围", web.HTTPConflict)
        source_ids.append(document["source_id"])
    identifier = "sector-" + str(uuid.uuid4())
    record = {
        "record_id": identifier, "version": "1", "kind": "MEETING", "title": payload["action_code"],
        "state": "DRAFT_SAVED", "created_at": now(), "page_id": page, "query_id": payload["query_id"],
        "dataset_version": snapshot["dataset_version"], "namespace": NAMESPACE,
        "purpose": purpose.strip(), "timezone": payload["timezone"],
        "attendee_refs": attendee_refs, "starts_at": payload["starts_at"], "ends_at": payload["ends_at"],
        "location": location.strip(), "source_ids": sorted(set(source_ids)),
        "source_refs": payload["source_refs"], "task_id": None, "plan_id": None, "meeting_id": None,
        "scheduled_by_meeting_service": False, "message_sent": False, "source_type": "SIMULATED",
    }
    api.store.put(db, NAMESPACE, RECORD_KIND, identifier, record)
    return {"record_id": identifier, "version": "1", "record_version": "1", "state": "DRAFT_SAVED",
            "kind": "MEETING", "title": payload["action_code"], "created_at": record["created_at"],
            "page_id": page, "query_id": payload["query_id"], "execution_namespace": NAMESPACE,
            "action_code": payload["action_code"], "messages_sent": 0, "external_channel_invoked": False,
            "source_ids": record["source_ids"], "task_id": None, "plan_id": None, "meeting_id": None,
            "message_sent": False}
