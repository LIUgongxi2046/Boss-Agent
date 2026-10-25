import json
from pathlib import Path

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from business import checksum, now, require
from boss_assignment_sources import AssignmentSourcesAPI
from boss_conversation import ConversationAPI
from boss_business_overview import owner
from boss_meetings import meeting_materials
from boss_simulation_api import _context


DIRECTORY = Path(__file__).resolve().parents[1] / "specs"
PATH = DIRECTORY / "business-overview-preparation.schema.json"
SCHEMA = json.loads(PATH.read_text())
RESOURCES = [PATH, DIRECTORY / "business-overview.schema.json"]
REGISTRY = Registry().with_resources((path.as_uri(), Resource.from_contents({**json.loads(path.read_text()), "$id": path.as_uri()})) for path in RESOURCES)


def validate(name, value):
    require(not list(Draft202012Validator({**SCHEMA, "$id": PATH.as_uri(), "$ref": "#/$defs/" + name},
        registry=REGISTRY, format_checker=FormatChecker()).iter_errors(value)), "经营准备输入输出不符合Schema", web.HTTPBadRequest)
    return value


def reference(row):
    return {field: row[field] for field in ("kind", "id", "version")}


class BusinessOverviewPreparation:
    def __init__(self, overview):
        self.overview, self.store = overview, overview.store
        self.assignments = AssignmentSourcesAPI(self.store)
        self.conversation = ConversationAPI(self.store)

    def read(self, role, payload):
        owner(role)
        validate("Input", payload)
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self.project_in_transaction(role, db, payload)

    def project_in_transaction(self, role, db, payload):
        owner(role)
        validate("Input", payload)
        identity = _context(db)
        require(identity["namespace"] == "ui-check", "当前准备流程仅支持获准执行空间", web.HTTPForbidden)
        view = self.overview.project_in_transaction(role, db, payload["applied_scope"])
        require(view["snapshot_sha256"] == payload["snapshot_sha256"], "经营范围、对象或来源已经变化", web.HTTPConflict)
        topic = None
        if payload["topic_reference"] is not None:
            selected = payload["topic_reference"]
            topic = next(row for row in view["topics"] if row["page_id"] == selected["page_id"])
            require(selected["use"] is None or selected["use"] in topic["uses"], "专题不支持所选用途", web.HTTPBadRequest)
        records = topic["records"] if topic is not None else []
        topic_sources = {ref["source_id"] for row in records for ref in row["source_refs"]}
        if topic is not None:
            topic_sources.update(ref["source_id"] for ref in topic["related_sales_source_refs"])
        tasks = [row for row in view["associations"] if topic is None or any(ref["source_id"] in topic_sources for ref in row["source_refs"])]
        candidates = sorted([reference(row) for row in [*records, *tasks]], key=lambda row: (row["kind"], row["id"]))
        result = {"source_type": "SIMULATED", **{field: payload[field] for field in
            ("applied_scope", "topic_reference", "snapshot_sha256", "object_reference", "action")},
            "state": "WAITING_INPUT", "candidates": candidates, "task_candidates": [], "source_references": [],
            "assignment_context": None, "meeting_context": None, "handoff": None, "missing_conditions": [], "required_inputs": [],
            "business_at": view["business_at"], "read_at": now(), "current_use_verified": False,
            "owner_decision_required": True, "business_authorization_granted": False, "business_mutation_performed": False,
            "message_sent": False, "task_completed": False}
        selected = payload["object_reference"]
        if selected is None:
            result["missing_conditions"].append("EXPLICIT_OBJECT_SELECTION_REQUIRED")
            result["required_inputs"].append("object_reference")
            if topic is not None and not records and not tasks:
                result["missing_conditions"].append("CURRENT_TOPIC_SOURCE_REQUIRED")
        else:
            matches = [row for row in [*records, *tasks] if row["kind"] == selected["kind"] and row["id"] == selected["id"]]
            require(len(matches) == 1, "准备对象不属于当前范围和专题", web.HTTPForbidden)
            current = matches[0]
            require(current["version"] == selected["version"], "准备对象版本已经变化", web.HTTPConflict)
            sources = {row["source_id"]: row for row in view["sources"]}
            result["source_references"] = [{"kind": "document", "id": ref["source_id"], "version": ref["version"],
                "content_sha256": sources[ref["source_id"]]["sha256"] if ref["source_id"] in sources else None,
                "status": sources[ref["source_id"]]["status"] if ref["source_id"] in sources and sources[ref["source_id"]]["version"] == ref["version"] else "MISSING_OR_CHANGED"}
                for ref in sorted(current["source_refs"], key=lambda row: row["source_id"])]
            required_state = "STORED_RECORD" if selected["kind"] == "task" else "CURRENT"
            if current["adoption_state"] != required_state or not result["source_references"] or any(ref["status"] != "VALID" for ref in result["source_references"]):
                result["missing_conditions"].append("CURRENT_OBJECT_SOURCES_REQUIRED")
            elif selected["kind"] == "task":
                self._assignment(db, identity, payload, current, topic_sources if topic is not None else set(sources), result)
            else:
                # 仅正式协调记录证明专题对象与任务的关系，不按名称或相同来源推断。
                for row, in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='supply_quality_coordination' ORDER BY id", (identity["namespace"],)):
                    link = json.loads(row)
                    if all(link[field] == selected[target] for field, target in
                           (("origin_entity_type", "kind"), ("origin_record_id", "id"), ("origin_version", "version"))):
                        result["task_candidates"].extend(reference(task) for task in tasks if task["id"] == link["task_id"] and task["adoption_state"] == "STORED_RECORD")
                result["task_candidates"] = sorted({(row["kind"], row["id"]): row for row in result["task_candidates"]}.values(), key=lambda row: row["id"])
                result["missing_conditions"].append("EXPLICIT_RELATED_TASK_SELECTION_REQUIRED" if result["task_candidates"] else "EXISTING_RELATED_TASK_REQUIRED")
                result["required_inputs"].append("object_reference")
                if payload["action"] == "MEETING_PREPARATION":
                    result["missing_conditions"].append("RELATED_MEETING_REFERENCE_REQUIRED")
        result["context_sha256"] = checksum({"identity": identity, "result": {key: value for key, value in result.items() if key != "read_at"}})
        return validate("View", result)

    def _assignment(self, db, identity, payload, current, allowed_sources, result):
        review = self.assignments.project_in_transaction("BOSS", db, current["id"])
        require(review["task"]["version"] == current["version"], "交办来源核查与当前对象版本不符", web.HTTPConflict)
        result["assignment_context"] = {"task_reference": reference(current), "review_sha256": review["review_sha256"],
            "binding_state": review["binding_state"], "task_state": review["task"]["status"],
            "result_evidence_current": review["result_evidence_current"],
            "result_evidence_requires_resubmission": review["result_evidence_requires_resubmission"]}
        if review["binding_state"] != "CURRENT":
            result["missing_conditions"].append("ASSIGNMENT_SOURCE_REVIEW_REQUIRED")
            return
        if not {row["source_id"] for row in review["sources"]} <= allowed_sources:
            result["missing_conditions"].append("ASSIGNMENT_SOURCES_OUTSIDE_SELECTED_SCOPE")
            return
        task = self.conversation.task_in_transaction(db, identity, current["id"], current["version"])
        if payload["action"] == "ASSIGNMENT_REVIEW":
            result.update(state="READY_FOR_REVIEW", current_use_verified=True, handoff={"page_id": "F06",
                "operation": "boss.assignment.prepare", "parameters": {"task_id": current["id"], "task_version": current["version"]},
                "required_inputs": ["client_request_id"]})
            return
        result["missing_conditions"].append("SCOPED_MEETING_PREPARATION_REQUIRED")
        if task["related_meeting_id"] is None:
            result["missing_conditions"].append("RELATED_MEETING_REFERENCE_REQUIRED")
            return
        initial = self.store.get(db, identity["namespace"], "initial", "snapshot")
        meeting = meeting_materials(db, initial)["meeting"]
        if meeting["meeting_id"] != task["related_meeting_id"]:
            result["missing_conditions"].append("RELATED_MEETING_NOT_AVAILABLE")
            return
        require(meeting["owner_id"] == identity["owner_id"], "关联会议不属于当前本人范围", web.HTTPForbidden)
        result["meeting_context"] = {"meeting_reference": {"kind": "meeting", "id": meeting["meeting_id"], "version": meeting["version"]},
            "relation": "EXPLICIT_TASK_MEETING_REFERENCE", "state": meeting.get("state", "DRAFT"), "source_scope_current": False}
        document_ids = set(meeting["material_ids"]) - set(task["related_event_ids"])
        if not document_ids or not document_ids <= allowed_sources:
            result["missing_conditions"].append("MEETING_MATERIALS_OUTSIDE_SELECTED_SCOPE")
        else:
            documents = self.store.assignment_sources(db, identity["namespace"], initial, sorted(document_ids))
            result["meeting_context"]["source_scope_current"] = all(any(ref["id"] == identifier and ref["version"] == document["version"]
                and ref["content_sha256"] == checksum(document) for ref in result["source_references"]) for identifier, document in documents.items())
            if not result["meeting_context"]["source_scope_current"]:
                result["missing_conditions"].append("CURRENT_MEETING_SOURCES_REQUIRED")
        if meeting.get("state", "DRAFT") in {"CANCELED", "HELD"}:
            result["missing_conditions"].append("CURRENT_MEETING_STATE_REQUIRED")

    def verify(self, role, payload, context_sha256):
        owner(role)
        validate("Sha256", context_sha256)
        result = self.read(role, payload)
        require(result["context_sha256"] == context_sha256 and result["current_use_verified"], "经营准备上下文已经变化或必要条件不足", web.HTTPConflict)
        return result
