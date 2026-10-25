import asyncio
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp import web
from nanobot.agent.tools.base import Tool

from business import checksum, encode, require
from boss_business_overview import owner


def compile_preparation(identity, selection, overview, task, meeting, documents, contacts):
    zone = ZoneInfo(meeting["timezone"])
    today = datetime.fromisoformat(identity["clock"]).astimezone(zone).date().isoformat()
    meeting_day = datetime.fromisoformat(meeting["starts_at"]).astimezone(zone).date().isoformat()
    participants = []
    for identifier in meeting["participant_ids"]:
        matches = [row for row in contacts if row["contact_id"] == identifier]
        if len(matches) != 1 or not all(matches[0]["valid_from"] <= day <= matches[0]["valid_until"] for day in (today, meeting_day)):
            return None, ["CURRENT_MEETING_PARTICIPANTS_REQUIRED"]
        participants.append({field: matches[0][field] for field in ("contact_id", "name", "organization", "responsibility")} | {"state": "CURRENT"})
    if not participants or len({row["contact_id"] for row in participants}) != len(participants):
        return None, ["CURRENT_MEETING_PARTICIPANTS_REQUIRED"]
    finance = "finance-note" in documents
    result = {"source_type": "SIMULATED", **{field: selection[field] for field in ("applied_scope", "topic_reference", "snapshot_sha256")},
        "meeting": {field: meeting.get(field) for field in ("meeting_id", "version", "state", "purpose", "starts_at", "ends_at", "timezone", "preparation_due_at")},
        "task": {field: task[field] for field in ("task_id", "version", "status", "purpose", "coordinator_id", "due_at", "timezone", "evidence_requirements")},
        "participants": participants,
        "materials": [{"source_reference": {"kind": "document", "id": identifier, "version": document["version"],
            "content_sha256": checksum(document), "status": "VALID"},
            **{field: document.get(field) for field in ("source_type", "author_contact_id", "published_at", "observed_at", "valid_from", "valid_until")},
            "content": document["content"]} for identifier, document in sorted(documents.items())],
        "metrics": overview["metrics"] if finance else [], "metric_scope": overview["metric_scope"] if finance else None,
        "metric_coverage": overview["metric_coverage"] if finance else None,
        "metric_missing_fields": overview["metric_missing_fields"] if finance else ["NO_METRIC_SOURCE_IN_MEETING_MATERIALS"],
        "topic_missing_fields": next(row["missing_fields"] for row in overview["topics"] if row["page_id"] == selection["topic_reference"]["page_id"]) if selection["topic_reference"] is not None else [],
        "scope_application": overview["scope_application"], "coverage_state": "PARTIAL", "business_at": identity["clock"],
        "owner_decision_required": True, "business_authorization_granted": False, "business_mutation_performed": False,
        "invitation_sent": False, "message_sent": False, "task_completed": False, "meeting_occurred": False}
    result["preparation_sha256"] = checksum({"identity": identity, "preparation": result})
    return result, []


@dataclass(frozen=True)
class MeetingPreparationContext:
    role: str
    selection: dict
    context_sha256: str
    active: object


class BusinessMeetingPreparationReadTool(Tool):
    def __init__(self, preparation, context_provider):
        require(callable(context_provider), "会议准备读取需要可信当前上下文", web.HTTPServiceUnavailable)
        self.preparation, self.context_provider = preparation, context_provider

    @property
    def name(self):
        return "businessMeetingPreparationRead"

    @property
    def description(self):
        return "读取当前已应用经营范围中明确关联会议的准备材料、任务、来源版本和范围指标；没有保存、邀请或发送权限。"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}, "additionalProperties": False}

    def _context(self):
        context = self.context_provider()
        require(isinstance(context, MeetingPreparationContext) and callable(context.active), "会议准备缺少可信当前上下文", web.HTTPForbidden)
        owner(context.role)
        require(context.active(), "会议准备本人认证已经失效", web.HTTPUnauthorized)
        return context

    async def execute(self):
        context = self._context()
        payload = {"selection": context.selection, "context_sha256": context.context_sha256}
        digest = checksum(payload)
        result = self.preparation.meeting(context.role, payload)
        await asyncio.sleep(0)
        current = self._context()
        current_payload = {"selection": current.selection, "context_sha256": current.context_sha256}
        require(current.role == context.role and checksum(current_payload) == digest, "当前会议准备选择已经变化", web.HTTPConflict)
        checked = self.preparation.meeting(current.role, current_payload)
        require(checked["preparation_sha256"] == result["preparation_sha256"], "会议准备期间资料已经变化", web.HTTPConflict)
        return encode(checked)
