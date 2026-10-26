# N04 资料目录：会议、资料、审批、研究与人员。
# 只读取当前执行空间内本人可见对象；缺少数据时保留明确缺失，不生成样例。
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from business import require
from boss_source_policy import source_validity

from boss_execution_scope import NAMESPACE as NS


def _get(db, kind, key):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
                     (NS, kind, key)).fetchone()
    return json.loads(row[0]) if row else None


def _list(db, kind):
    return [json.loads(row[0]) for row in
            db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id",
                       (NS, kind)).fetchall()]


def _local(at, timezone):
    if not at:
        return None
    moment = datetime.fromisoformat(at)
    if moment.tzinfo is None:
        return moment.date().isoformat()
    return moment.astimezone(ZoneInfo(timezone)).date().isoformat()


def _action(identifier, title, page, enabled, reason, source_id=None):
    return {"id": identifier, "title": title, "enabled": enabled,
            "disabled_reason": None if enabled else reason,
            "page": page, "source_id": source_id}


def _document_state(document, clock):
    if document.get("withdrawn"):
        return "WITHDRAWN"
    if document.get("access_scope") != "boss-1":
        return "FORBIDDEN"
    if document.get("source_type") != "SIMULATED":
        return "FORBIDDEN"
    return source_validity(document, clock)


def _meeting(db, data, clock):
    initial = data["meeting"]
    meeting = _get(db, "meeting", initial["meeting_id"]) or initial
    timezone = meeting.get("timezone", "Asia/Shanghai")
    material_ids = [item for item in meeting.get("material_ids", [])
                    if item != data["event"]["event_id"]]
    sources, gaps = [], []
    for source_id in material_ids:
        document = _get(db, "document", source_id)
        if document is None:
            gaps.append(source_id)
            continue
        state = _document_state(document, clock)
        if state != "VALID":
            gaps.append(source_id)
            continue
        sources.append({"source_id": source_id, "version": document.get("version"),
                        "location": document.get("original_locator")})
    minute = _get(db, "minutes", meeting["meeting_id"])
    brief = _get(db, "meeting_brief", meeting["meeting_id"])
    tasks = [row for row in _list(db, "task") if row.get("related_meeting_id") == meeting["meeting_id"]]
    participants = [contact for contact in data["contacts"]
                    if contact["contact_id"] in meeting.get("participant_ids", [])]
    material_state = "READY" if sources and not gaps else "PARTIAL" if sources else "MATERIALS_MISSING"
    actions = [
        _action("prepare", "准备会议", "F04", True, ""),
        _action("source", "阅读原文", "D01", bool(sources), "当前会议没有已获准的材料原文",
                sources[0]["source_id"] if sources else None),
        _action("minutes", "打开纪要", "F05", minute is not None, "当前会议尚无已保存纪要"),
        _action("discuss", "继续讨论", "N02", True, ""),
        _action("history", "查看历史决定", "N11", True, ""),
    ]
    return {
        "id": meeting["meeting_id"], "kind": "meeting",
        "title": meeting.get("title") or "经营会议 · " + str(_local(meeting.get("starts_at"), timezone)),
        "version": str(meeting.get("version")),
        "at": meeting.get("starts_at"), "local_date": _local(meeting.get("starts_at"), timezone),
        "timezone": timezone, "source_type": "SIMULATED",
        "summary": "参会人：" + ("、".join(contact["name"] for contact in participants) or "尚未提供"),
        "material_state": material_state,
        "material_gaps": gaps,
        "meeting_state": meeting.get("state", "DRAFT"),
        "preparation_state": brief.get("state") if brief else None,
        "minute_state": minute.get("state") if minute else None,
        "assignment_state": "、".join(sorted({task.get("status", "UNKNOWN") for task in tasks})) if tasks else None,
        "source_refs": sources,
        "related_objects": [{ "id": contact["contact_id"], "title": contact["name"], "kind": "contact"}
                            for contact in participants]
                            + [{"id": task["task_id"], "title": task.get("purpose") or task["task_id"], "kind": "task"}
                               for task in tasks],
        "actions": actions,
    }


def _documents(db, data, clock):
    timezone = data["boss_profile"].get("timezone", "Asia/Shanghai")
    records = []
    for document in _list(db, "document"):
        if document.get("simulation_definition") == "SECTOR-PACK-1":
            continue
        state = _document_state(document, clock)
        accessible = state == "VALID"
        records.append({
            "id": document["source_id"], "kind": "document",
            "title": document.get("title") or "资料 · " + document["source_id"],
            "version": str(document.get("version")), "at": document.get("published_at"),
            "local_date": _local(document.get("published_at"), timezone), "timezone": timezone,
            "source_type": document.get("source_type", "SIMULATED"),
            "summary": (document.get("content") or "")[:160],
            "material_state": state, "material_gaps": [],
            "meeting_state": None, "preparation_state": None, "minute_state": None,
            "assignment_state": None,
            "source_refs": [{"source_id": document["source_id"], "version": document.get("version"),
                             "location": document.get("original_locator")}],
            "related_objects": [],
            "actions": [
                _action("source", "阅读原文", "D01", accessible,
                        "当前资料已撤销、失效或不在本人获准范围", document["source_id"]),
                _action("discuss", "继续讨论", "N02", accessible, "当前资料不可采用"),
            ],
        })
    return records


def _applications(db, data, clock):
    timezone = data["boss_profile"].get("timezone", "Asia/Shanghai")
    records = []
    for application in _list(db, "application"):
        if application.get("source_type") != "SIMULATED":
            continue
        document = _get(db, "document", application.get("source_id"))
        state = _document_state(document, clock) if document else "MISSING"
        open_state = application.get("state") in ("PENDING_DECISION", "WAITING_MATERIAL")
        records.append({
            "id": application["application_id"], "kind": "approval",
            "title": application.get("title") or "待决定申请",
            "version": str(application.get("version")), "at": application.get("created_at"),
            "local_date": _local(application.get("created_at"), timezone), "timezone": timezone,
            "source_type": "SIMULATED",
            "summary": application.get("description") or "尚未提供申请说明",
            "material_state": application.get("state", "UNKNOWN"), "material_gaps": [],
            "meeting_state": None, "preparation_state": None, "minute_state": None,
            "assignment_state": None,
            "source_refs": ([{"source_id": document["source_id"], "version": document.get("version"),
                              "location": document.get("original_locator")}] if document else []),
            "related_objects": [],
            "actions": [
                _action("open", "打开申请审阅", "F07", True, ""),
                _action("source", "阅读原文", "D01", state == "VALID",
                        "申请附件已撤销、失效或不在本人获准范围",
                        application.get("source_id") if state == "VALID" else None),
            ],
        })
    return records


def _people(db, data, clock):
    timezone = data["boss_profile"].get("timezone", "Asia/Shanghai")
    records = []
    for brief in _list(db, "person_brief"):
        compiled = brief.get("compiled") or {}
        contact = compiled.get("contact") or {}
        sources = []
        for item in compiled.get("sources", []):
            document = _get(db, "document", item.get("source_id"))
            if document is None or _document_state(document, clock) != "VALID":
                continue
            sources.append({"source_id": item["source_id"], "version": item.get("version"),
                            "location": document.get("original_locator")})
        records.append({
            "id": brief["brief_id"], "kind": "people",
            "title": "人员会面 · " + (contact.get("name") or "尚未提供联系人"),
            "version": str(brief.get("version")), "at": brief.get("prepared_at"),
            "local_date": _local(brief.get("prepared_at"), timezone), "timezone": timezone,
            "source_type": "SIMULATED",
            "summary": compiled.get("purpose") or "尚未提供会面目的",
            "material_state": brief.get("state", "UNKNOWN"), "material_gaps": [],
            "meeting_state": None, "preparation_state": None, "minute_state": None,
            "assignment_state": None,
            "source_refs": sources,
            "related_objects": ([{"id": contact.get("contact_id"), "title": contact.get("name"), "kind": "contact"}]
                                if contact.get("contact_id") else []),
            "actions": [
                _action("open", "打开人员会面", "F10", True, ""),
                _action("source", "阅读原文", "D01", bool(sources),
                        "当前会面材料没有可用的已获准原文",
                        sources[0]["source_id"] if sources else None),
            ],
        })
    return records


def read_meeting_library(store, db, snapshot):
    clock = store.get(db, NS, "clock", "current")["at"]
    records = [_meeting(db, snapshot, clock)]
    records.extend(_documents(db, snapshot, clock))
    records.extend(_applications(db, snapshot, clock))
    records.extend(_people(db, snapshot, clock))
    coverage = []
    for kind in ("meeting", "document", "approval", "research", "people"):
        count = len([row for row in records if row["kind"] == kind])
        if kind == "research":
            coverage.append({"kind": kind, "state": "NOT_PROVIDED",
                             "reason": "当前没有已保存的研究材料"})
        elif count:
            coverage.append({"kind": kind, "state": "COMPLETE", "reason": None})
        else:
            coverage.append({"kind": kind, "state": "NOT_PROVIDED",
                             "reason": {"approval": "当前没有待决定的模拟申请",
                                        "people": "当前没有人员会面材料",
                                        "document": "当前没有本人可读的资料"}.get(kind, "当前没有已保存记录")})
    require(all(row["kind"] in {"meeting", "document", "approval", "research", "people"}
                for row in records), "目录记录类别无效")
    return {"source_type": "SIMULATED", "records": records, "coverage": coverage,
            "namespace": NS}
