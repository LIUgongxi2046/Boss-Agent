"""Simulation event and reply records for A04.

Maintainer-only. Every save verifies the current execution space, dataset,
target, author, source and clock versions. Saved records keep the separate
outcomes for business tasks, notifications, simulation and Agent processing;
none of them is reported successful unless actually produced.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from urllib.parse import parse_qs

from aiohttp import web

from business import now, require
from boss_source_policy import source_validity
from boss_v7_store import NAMESPACE

RECORD_KIND = "simulation_event_record"
EVENT_KIND = "simulation_event"


def _get(db, kind, key):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
                     (NAMESPACE, kind, key)).fetchone()
    return json.loads(row[0]) if row else None


def _authors(snapshot):
    return [{"id": contact["contact_id"], "title": contact["name"],
             "version": "1", "organization": contact.get("organization")}
            for contact in snapshot["contacts"]]


def _sources(db, snapshot, clock):
    meeting = snapshot["meeting"]
    rows = []
    for source_id in meeting["material_ids"]:
        if source_id == snapshot["event"]["event_id"]:
            continue
        document = _get(db, "document", source_id)
        if document is None:
            continue
        state = "CURRENT" if source_validity(document, clock) == "VALID" else source_validity(document, clock)
        rows.append({"id": source_id, "title": "资料 · " + source_id,
                     "version": str(document.get("version")), "as_of": document.get("published_at"),
                     "state": state, "author_id": document.get("author_contact_id")})
    return rows


def _target(db, snapshot):
    event = _get(db, "event", snapshot["event"]["event_id"]) or snapshot["event"]
    return {"id": event["event_id"], "title": "模拟经营事件 " + event["event_id"],
            "version": str(event.get("version", "1")), "kind": "event",
            "author_ids": [row["id"] for row in _authors(snapshot)],
            "source_ids": [row["id"] for row in _sources(db, snapshot, _clock(db)["at"])]}


def _clock(db):
    return json.loads(db.execute("SELECT body FROM objects WHERE namespace=? AND kind='clock' AND id='current'",
                                 (NAMESPACE,)).fetchone()[0])


def _time(value, label):
    require(isinstance(value, str) and value, label + "缺失", web.HTTPBadRequest)
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, label + "必须包含明确时区", web.HTTPBadRequest)
    return parsed


def _records(db):
    rows = []
    for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id",
                          (NAMESPACE, RECORD_KIND)).fetchall():
        rows.append(json.loads(row[0]))
    rows.sort(key=lambda item: item["created_at"], reverse=True)
    return rows


def read_simulation_events(store, db, snapshot, query):
    require(not query, "事件读取不接受查询参数", web.HTTPBadRequest)
    clock = _clock(db)
    sources = _sources(db, snapshot, clock["at"])
    target = _target(db, snapshot)
    return {
        "source_type": "SIMULATED", "namespace": NAMESPACE,
        "dataset_id": snapshot["dataset_id"], "dataset_version": snapshot["dataset_version"],
        "business_clock": {"at": clock["at"], "version": str(clock.get("version", "1"))},
        "event_types": [{"id": "business-event", "title": "经营事件与模拟回复",
                         "actions": ["inject", "reply"], "target_kinds": ["event"]}],
        "targets": [target],
        "authors": _authors(snapshot),
        "sources": sources,
        "records": _records(db),
        "allowed_actions": ["inject", "reply", "advance-clock"],
        "read_at": now(),
    }


def _common(payload, snapshot, clock):
    require(set(payload) == {"client_request_id", "namespace", "dataset_id", "dataset_version",
                             "event_type", "target_id", "target_version", "author_id", "author_version",
                             "source_id", "source_version", "source_at", "event_at", "content",
                             "expected_clock_version"}, "事件保存字段不完整", web.HTTPBadRequest)
    require(payload["namespace"] == NAMESPACE, "执行空间不一致", web.HTTPConflict)
    require(payload["dataset_id"] == snapshot["dataset_id"]
            and payload["dataset_version"] == snapshot["dataset_version"], "数据集已经变化", web.HTTPConflict)
    require(payload["expected_clock_version"] == str(clock.get("version", "1")), "业务时钟已经变化", web.HTTPConflict)
    require(payload["event_type"] == "business-event", "事件类型不在获准范围", web.HTTPBadRequest)
    require(isinstance(payload["content"], str) and 0 < len(payload["content"].strip()) <= 2400,
            "事件内容不能为空或过长", web.HTTPBadRequest)
    _time(payload["event_at"], "业务事件时间")


def record(store, db, snapshot, payload, action):
    clock = _clock(db)
    _common(payload, snapshot, clock)
    target = _target(db, snapshot)
    require(payload["target_id"] == target["id"] and payload["target_version"] == target["version"],
            "关联事项版本已经变化", web.HTTPConflict)
    author = next((row for row in _authors(snapshot) if row["id"] == payload["author_id"]), None)
    require(author is not None and payload["author_version"] == author["version"], "模拟作者已经变化", web.HTTPConflict)
    source = next((row for row in _sources(db, snapshot, clock["at"]) if row["id"] == payload["source_id"]), None)
    require(source is not None and source["state"] == "CURRENT", "资料不在当前可用范围", web.HTTPConflict)
    require(payload["source_version"] == source["version"], "资料版本已经变化", web.HTTPConflict)
    require(payload["source_at"] == source["as_of"], "资料时间已经变化", web.HTTPConflict)
    identifier = "sim-event-" + str(uuid.uuid4())
    saved = {"state": "RECORDED", "ids": [identifier], "error": None}
    record_row = {
        "id": identifier, "action": action, "event_type": payload["event_type"], "namespace": NAMESPACE,
        "request_id": payload["client_request_id"], "created_at": now(),
        "target_id": target["id"], "source_id": source["id"], "source_version": source["version"],
        "author_id": author["id"], "event_at": payload["event_at"], "content": payload["content"].strip(),
        "saved": saved,
        "tasks": {"state": "NOT_TRIGGERED", "ids": [], "error": None},
        "notifications": {"state": "NOT_TRIGGERED", "ids": [], "error": None},
        "simulation": {"state": "NOT_TRIGGERED", "ids": [], "error": None},
        "agent": {"state": "NOT_REQUESTED", "ids": [], "error": None},
        "run_ids": [],
    }
    store.put(db, NAMESPACE, RECORD_KIND, identifier, record_row)
    store.put(db, NAMESPACE, EVENT_KIND, identifier, {
        "id": identifier, "event_type": payload["event_type"], "target_id": target["id"],
        "author_id": author["id"], "source_id": source["id"], "source_version": source["version"],
        "event_at": payload["event_at"], "content": record_row["content"],
        "source_type": "SIMULATED",
    })
    return {"source_type": "SIMULATED", "record_id": identifier, "action": action,
            "saved": saved, "tasks": record_row["tasks"], "notifications": record_row["notifications"],
            "simulation": record_row["simulation"], "agent": record_row["agent"]}


def advance_clock(store, db, snapshot, payload):
    require(set(payload) == {"client_request_id", "namespace", "dataset_id", "dataset_version",
                             "expected_clock_version", "at"}, "时钟推进字段不完整", web.HTTPBadRequest)
    require(payload["namespace"] == NAMESPACE, "执行空间不一致", web.HTTPConflict)
    require(payload["dataset_id"] == snapshot["dataset_id"]
            and payload["dataset_version"] == snapshot["dataset_version"], "数据集已经变化", web.HTTPConflict)
    clock = _clock(db)
    require(payload["expected_clock_version"] == str(clock.get("version", "1")), "业务时钟已经变化", web.HTTPConflict)
    current = _time(clock["at"], "当前业务时钟")
    requested = _time(payload["at"], "目标业务时钟")
    require(requested >= current, "业务时钟只能前进", web.HTTPBadRequest)
    require((requested - current).total_seconds() <= 366 * 86400, "单次推进不能超过366天", web.HTTPBadRequest)
    updated = store.control_clock(db, NAMESPACE, {"at": payload["at"]})
    identifier = "sim-event-" + str(uuid.uuid4())
    record_row = {
        "id": identifier, "action": "advance-clock", "event_type": "clock", "namespace": NAMESPACE,
        "request_id": payload["client_request_id"], "created_at": now(),
        "target_id": None, "source_id": None, "source_version": None, "author_id": None,
        "event_at": payload["at"], "content": "业务时钟推进",
        "saved": {"state": "RECORDED", "ids": [identifier], "error": None},
        "tasks": {"state": "PENDING_CRON", "ids": [], "error": None},
        "notifications": {"state": "PENDING_CRON", "ids": [], "error": None},
        "simulation": {"state": "RECORDED", "ids": [], "error": None},
        "agent": {"state": "NOT_REQUESTED", "ids": [], "error": None},
        "run_ids": [],
    }
    store.put(db, NAMESPACE, RECORD_KIND, identifier, record_row)
    return {"source_type": "SIMULATED", "record_id": identifier, "at": updated["at"],
            "version": str(updated.get("version")), "saved": record_row["saved"],
            "tasks": record_row["tasks"], "notifications": record_row["notifications"],
            "simulation": record_row["simulation"], "agent": record_row["agent"]}
