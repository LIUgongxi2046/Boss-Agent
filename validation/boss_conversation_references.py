import json

from business import require
from boss_conversation import recorded_conversation_context, validate
from boss_simulation_api import KINDS, SimulationAPI
from boss_source_policy import source_validity
from boss_supply_quality import external_adoption


SOURCE_FIELDS = ("author_contact_id", "author_kind", "author_display_name", "generator_version", "published_at",
                 "observed_at", "business_as_of", "valid_from", "valid_until", "coverage", "business_basis",
                 "business_basis_description", "allowed_use")


class ConversationReferences:
    def __init__(self, store):
        self.store = store
        self.simulation = SimulationAPI(store)
        self.interfaces = {}
        for interface, kinds in KINDS.items():
            for kind in kinds:
                self.interfaces.setdefault(kind, interface)

    def project_in_transaction(self, db, context, run):
        found = {}
        def add(kind, identifier, version, support):
            reference = validate("RecordedContextReference", {"kind": kind, "id": identifier, "version": version})
            key = (reference["kind"], reference["id"], reference["version"])
            found.setdefault(key, []).append(support)
        if "conversation_context" in run:
            origin = recorded_conversation_context(run)
            for ref in origin["references"]:
                add(ref["kind"], ref["id"], ref["version"], {"origin": "CONVERSATION_CONTEXT", "tool_id": None, "tool_call_id": None})
        for step in run["tool_results"]:
            if "source_id" in step:
                add("document", step["source_id"], step.get("version"),
                    {"origin": "TOOL_RESULT", "tool_id": step["tool_id"], "tool_call_id": step["tool_call_id"]})
            if "task_id" in step:
                add("task", step["task_id"], step.get("task_version"),
                    {"origin": "TOOL_RESULT", "tool_id": step["tool_id"], "tool_call_id": step["tool_call_id"]})
        rows = []
        for (kind, identifier, version), support in found.items():
            row = {"kind": kind, "id": identifier, "recorded_version": version, "current_version": None,
                "reference_state": "MISSING_OR_FORBIDDEN", "adoption_state": "UNAVAILABLE", "current_validity": None,
                "current_object_state": None, "source_metadata": None, "source_refs": [], "support": support}
            if kind == "document":
                self._source(db, context, row)
            elif kind in self.interfaces:
                self._object(db, context, row)
            else:
                row["reference_state"] = "UNSUPPORTED_KIND"
            rows.append(validate("ContextReference", row))
        return rows

    @staticmethod
    def _version_state(row, current):
        if row["recorded_version"] is None:
            return "VERSION_UNRECORDED"
        return "CURRENT" if row["recorded_version"] == current else "VERSION_CHANGED"

    def _source(self, db, context, row):
        found = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=? "
            "AND json_extract(body,'$.source_id')=? AND json_extract(body,'$.access_scope')=? "
            "AND json_extract(body,'$.source_type')='SIMULATED'",
            (context["namespace"], row["id"], row["id"], context["owner_id"])).fetchone()
        if found is None:
            return
        document = json.loads(found[0])
        state = source_validity(document, context["clock"])
        row.update(current_version=document["version"], current_validity=state, adoption_state="NEEDS_REVIEW")
        row["reference_state"] = self._version_state(row, document["version"]) if state == "VALID" else "NEEDS_REVIEW"
        if state == "VALID":
            initial = self.store.get(db, context["namespace"], "initial", "snapshot")
            adoption = external_adoption(db, context["namespace"], initial, context["clock"], document)
            if adoption["state"] == "NEEDS_REIMPORT":
                row["reference_state"] = "NEEDS_REVIEW"
            for dependency in adoption["dependencies"]:
                current = self.simulation._source(db, context, dependency["source_id"])
                permitted = current is not None and current["source_id"] == dependency["source_id"] and current["access_scope"] == context["owner_id"] and current["source_type"] == "SIMULATED"
                row["source_refs"].append({"source_id": dependency["source_id"], "version": dependency["version"],
                    "current_version": current["version"] if permitted else None, "status": dependency["status"]})
        if row["reference_state"] == "CURRENT":
            row["adoption_state"] = "CURRENT"
            row["source_metadata"] = {"source_type": document["source_type"], "version": document["version"],
                **{field: document.get(field) for field in SOURCE_FIELDS}}

    def _object(self, db, context, row):
        payload = {"interface_id": self.interfaces[row["kind"]], "object_ids": [row["kind"] + ":" + row["id"]], "filters": {}}
        records = [record for record in self.simulation._records(db, context, payload, technical=False)
                   if record["entity_type"] == row["kind"] and record["object_id"] == row["id"]]
        require(len(records) <= 1, "当前上下文对象无法唯一确定")
        if not records:
            return
        record = records[0]
        body = record["data"]
        # 正式模拟查询承担来源及内容采用核查；投影仅保留经过核查的元信息。
        for scope in (body, body.get("envelope", {})):
            if any(scope.get(field, value) != value for field, value in (
                ("owner_id", context["owner_id"]), ("dataset_id", context["dataset_id"]),
                ("dataset_version", context["dataset_version"]), ("execution_namespace", context["namespace"]))):
                return
        self.simulation._protect(db, context, record)
        row.update(current_version=record["version"], current_object_state=record["state"], source_refs=record["source_refs"], adoption_state="NEEDS_REVIEW")
        row["reference_state"] = self._version_state(row, record["version"])
        if record["content_state"] in ("NEEDS_REVIEW", "INACTIVE"):
            row["reference_state"] = record["content_state"]
        if row["reference_state"] == "CURRENT":
            row["adoption_state"] = "CURRENT"
