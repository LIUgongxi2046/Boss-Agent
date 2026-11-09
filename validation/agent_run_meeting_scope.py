from aiohttp import web

from boss_execution_scope import NAMESPACE
from boss_meeting_brief import compile_brief
from boss_meetings import meeting_materials
from boss_owner_preferences import effective_owner_goals
from boss_source_access import require_current_business_source
from boss_v7_metrics import METRICS, effective_configuration
from business import checksum


def meeting_context_in_transaction(service, db, proof, meeting_id):
    if not db.in_transaction or proof.namespace != NAMESPACE:
        raise web.HTTPForbidden(text="会议范围与当前执行空间不符")
    data = service.scope.store.get(db, proof.namespace, "initial", "snapshot")
    data = meeting_materials(db, data)
    meeting = data["meeting"]
    if meeting["meeting_id"] != meeting_id or meeting["owner_id"] != proof.owner_id or data["owner_id"] != proof.owner_id or data["dataset_id"] != proof.dataset_id or data["dataset_version"] != proof.dataset_version:
        raise web.HTTPForbidden(text="会议不属于当前本人资料范围")
    pins = {item[0]: (item[1], item[2]) for item in proof.source_pins}
    source_ids = set(meeting["material_ids"]) - {data["event"]["event_id"]}
    for source_id in sorted(source_ids):
        document = require_current_business_source(service.scope.store, db, proof.namespace, proof.owner_id, source_id)
        if pins.get(source_id) != (document["version"], checksum(document)):
            raise web.HTTPForbidden(text="会议资料未获当前运行选择")
    compiled = compile_brief(db, data)
    if compiled["needs_review"] or any(item["status"] != "CURRENT" for item in compiled["sources"]):
        raise web.HTTPConflict(text="会议资料或参与人员需要复核")
    if data["event"].get("meeting_id") != meeting_id or data["historical_task"]["task_id"] not in meeting.get("historical_commitment_ids", []):
        raise web.HTTPConflict(text="会议历史任务或事件缺少明确关联")

    def member(kind, identifier):
        interface = {"task": "SI06", "event": "SI14", "metric_detail": "SI07", "travel_plan": "SI03", "person_brief": "SI02", "feedback": "SI06"}[kind]
        projected = service.simulation.project_in_transaction("BOSS", db, {"interface_id": interface, "object_ids": [kind + ":" + identifier], "filters": {}})
        records = [item for item in projected["records"] if item["entity_type"] == kind and item["object_id"] == identifier]
        if len(records) != 1 or records[0]["data"] is None or records[0]["content_state"] != "STORED_RECORD" or not isinstance(records[0]["version"], str) or not records[0]["version"]:
            raise web.HTTPConflict(text="会议关联对象不可核查")
        record = records[0]
        for source in service._record_sources(record):
            document = require_current_business_source(service.scope.store, db, proof.namespace, proof.owner_id, source["source_id"])
            if source["status"] != "VALID" or pins.get(source["source_id"]) != (source["version"], checksum(document)):
                raise web.HTTPForbidden(text="会议关联对象来源未获当前运行选择")
        return {"entity_type": kind, "object_id": identifier, "version": record["version"], "sha256": checksum(record["data"]), "data": record["data"]}

    members = {}
    def add(kind, identifier):
        key = (kind, identifier)
        if key not in members:
            members[key] = member(kind, identifier)
        return members[key]["data"]

    for item in compiled["commitments"]:
        task = add("task", item["task_id"])
        if item["task_id"] != data["historical_task"]["task_id"] and task.get("related_meeting_id") != meeting_id:
            raise web.HTTPConflict(text="任务缺少会议关联")
    event = add("event", compiled["event"]["event_id"])
    if event.get("meeting_id") != meeting_id:
        raise web.HTTPConflict(text="事件缺少会议关联")
    for item in compiled["travel_impacts"]:
        add("travel_plan", item["travel_id"])
    for item in compiled["people_meeting_impacts"]:
        if item["source_state"] != "CURRENT" or item["meeting_version"] != meeting["version"]:
            raise web.HTTPConflict(text="人员简报关联已经变化")
        person = add("person_brief", item["brief_id"])
        if person["linked_meeting_version"] != meeting["version"] or person["compiled"]["meeting"]["meeting_id"] != meeting_id or person["compiled_sha256"] != checksum(person["compiled"]):
            raise web.HTTPConflict(text="人员简报内容或会议关联已经变化")
        for task in person["compiled"]["tasks"]:
            current = add("task", task["task_id"])
            if current["version"] != task["version"]:
                raise web.HTTPConflict(text="人员简报关联任务已经变化")
        for feedback in person["compiled"]["feedback"]:
            add("feedback", feedback["feedback_id"])
            for source_id in feedback["evidence_source_ids"]:
                document = require_current_business_source(service.scope.store, db, proof.namespace, proof.owner_id, source_id)
                if pins.get(source_id) != (document["version"], checksum(document)):
                    raise web.HTTPForbidden(text="反馈来源未获当前运行选择")
    for period in compiled["metrics"]["values"]:
        for identifier in period["detail_refs"]:
            add("metric_detail", identifier)
    participants = [item for item in data["contacts"] if item["contact_id"] in meeting["participant_ids"]]
    if len(participants) != len(meeting["participant_ids"]) or len({item["contact_id"] for item in participants}) != len(participants):
        raise web.HTTPConflict(text="参会人员集合不可核查")
    configurations = {}
    for identifier in METRICS:
        active = effective_configuration(db, proof.namespace, identifier)
        if active is not None and checksum(active["values"]) != active["content_sha256"]:
            raise web.HTTPConflict(text="指标配置摘要不可核查")
        configurations[identifier] = active
    goals = effective_owner_goals(db, data, proof.namespace)
    return {"meeting": meeting, "participants": participants, "members": [members[key] for key in sorted(members)], "metric_definitions": data["metric_definitions"], "periods": data["periods"], "metric_configurations": configurations, "owner_goals": goals, "compiled": compiled}
