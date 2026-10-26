"""Owner-recorded sector follow-up decisions.

Only the decision action is implemented: it saves the owner's project or
resource decision together with the current sector query reference. Task,
plan and meeting creation remain separate services and are not claimed here.
"""
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
    return {"record_id": identifier, "version": "1", "state": "RECORDED", "kind": "DECISION",
            "title": record["title"], "created_at": record["created_at"], "query_id": record["query_id"],
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
