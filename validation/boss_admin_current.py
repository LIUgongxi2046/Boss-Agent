import json
from decimal import Decimal
from urllib.parse import parse_qs

from aiohttp import web

from business import checksum, now, require
from boss_meetings import meeting_materials
from boss_v7_store import NAMESPACE, rows


def effective_runtime(store, db, namespace=NAMESPACE):
    current = store.get(db, namespace, "configuration", "current")
    return {"configuration_version": current["version"],
            **{key: current.get(key) for key in ("provider", "model_id", "api_type", "enabled", "max_tool_rounds", "max_output_tokens", "timeout", "workspace_read_mode")},
            "tool_scope": current["tool_scope"], "workspace_projections": current.get("workspace_projections", []),
            "custom_prompt_count": sum(item["enabled"] for item in rows(db, "prompt_active", namespace)),
            "configuration_mutated": False}


def business_records(store, db, initial, namespace=NAMESPACE):
    contacts = {row["contact_id"]: row for row in initial["contacts"]}
    tasks = {row["task_id"]: row for row in rows(db, "task", namespace)}
    output = []
    for task in tasks.values():
        coordinator = contacts[task["coordinator_id"]]
        output.append({"kind": "task", "id": task["task_id"], "version": task["version"], "title": task["purpose"],
                       "state": task["status"], "at": task["due_at"], "author_name": coordinator["name"],
                       "related_object_id": task["task_id"],
                       "source_refs": [{"source_id": source_id, "version": version} for source_id, version in task["source_versions"].items()]})
    for feedback in rows(db, "feedback", namespace):
        require(feedback["task_id"] in tasks, "当前反馈缺少关联任务", web.HTTPConflict)
        task = tasks[feedback["task_id"]]
        output.append({"kind": "feedback", "id": feedback["feedback_id"], "version": feedback["task_version"],
                       "title": task["purpose"], "state": feedback["kind"], "at": feedback["submitted_at"],
                       "author_name": contacts[feedback["author_contact_id"]]["name"], "related_object_id": task["task_id"],
                       "source_refs": [{"source_id": source_id, "version": version} for source_id, version in feedback["evidence_versions"].items()]})
    for event in rows(db, "event", namespace):
        task = tasks.get(event.get("task_id"))
        output.append({"kind": "event", "id": event["event_id"], "version": event["version"],
                       "title": task["purpose"] if task is not None else event.get("description"),
                       "state": event["state"], "at": event["due_at"], "author_name": None,
                       "related_object_id": event.get("task_id", event.get("commitment_id")),
                       "source_refs": event.get("source_refs", [])})
    return sorted(output, key=lambda row: (row["kind"], row["id"]))


def observed_runs(db, namespace=NAMESPACE):
    records = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='runtime_run' ORDER BY json_extract(body,'$.started_at') DESC,id DESC LIMIT 50", (namespace,))
    output = []
    for body, in records:
        run = json.loads(body)
        output.append({"run_id": run["run_id"], "state": run["status"], "started_at": run["started_at"],
                       "finished_at": run["finished_at"], "model_id": run["runtime"]["model_id"],
                       "configuration_version": run["configuration_version"], "dataset_id": run.get("dataset_id"),
                       "dataset_version": run.get("dataset_version"), "model_requests": len(run["model_requests"]),
                       "tool_results": len(run["tool_results"]), "external_model_invoked": run.get("external_model_invoked", False),
                       "formal_evaluation_passed": run["model_behavior_evaluation_passed"]})
    return output


def current_records(store, db, initial, namespace=NAMESPACE):
    documents = rows(db, "document", namespace)
    meetings = {row["meeting_id"]: row for row in rows(db, "meeting", namespace)}
    primary = meeting_materials(db, initial)["meeting"]
    meetings[primary["meeting_id"]] = primary
    records = {
        "financial_detail": initial["details"], "initial_contact": initial["contacts"],
        "document_metadata": [{key: document.get(key) for key in ("source_id", "version", "title", "source_type", "author_contact_id", "published_at", "valid_from", "valid_until")}
                              for document in sorted(documents, key=lambda row: row["source_id"])],
        "meeting_summary": [{key: meeting.get(key) for key in ("meeting_id", "version", "title", "state", "starts_at", "ends_at", "participant_ids", "material_ids")}
                            for meeting in sorted(meetings.values(), key=lambda row: row["meeting_id"])],
        "application_summary": [{key: application[key] for key in ("application_id", "version", "title", "state", "applicant_contact_id", "amount", "currency", "source_id", "source_version")}
                                for application in rows(db, "application", namespace)],
    }
    business = business_records(store, db, initial, namespace)
    for kind in ("task", "feedback", "event"):
        records[kind + "_summary"] = [row for row in business if row["kind"] == kind]
    return records


def current_snapshot(store, db, initial, namespace=NAMESPACE):
    records = current_records(store, db, initial, namespace)
    totals = {period: {field: str(sum(Decimal(row[field]) for row in initial["details"] if row["period"] == period))
                       for field in ("quantity_tonnes", "revenue_cny", "cost_cny")} for period in initial["periods"]}
    at = store.get(db, namespace, "clock", "current")["at"]
    facts = {"dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"],
             "namespace": namespace, "business_at": at, "records": records}
    return {key: value for key, value in facts.items() if key != "records"} | {
        "source_type": "SIMULATED", "snapshot_sha256": checksum(facts),
        "counts": {key: len(value) for key, value in records.items()}, "totals": totals,
        "business_mutation_performed": False, "private_body_available_here": False}


def read_current_records(store, db, initial, query, namespace=NAMESPACE):
    parsed = parse_qs(query, keep_blank_values=True)
    require(set(parsed) == {"kind", "offset", "snapshot_sha256"} and all(len(value) == 1 for value in parsed.values()), "当前资料查询字段无效", web.HTTPBadRequest)
    snapshot = current_snapshot(store, db, initial, namespace)
    require(snapshot["snapshot_sha256"] == parsed["snapshot_sha256"][0], "当前业务资料已经变化，请刷新管理页面", web.HTTPConflict)
    records = current_records(store, db, initial, namespace)
    kind, offset_text = parsed["kind"][0], parsed["offset"][0]
    require(kind in records and offset_text.isascii() and offset_text.isdecimal() and len(offset_text) <= 8, "当前资料类别或位置无效", web.HTTPBadRequest)
    offset = int(offset_text)
    return {"dataset_id": snapshot["dataset_id"], "version": snapshot["dataset_version"], "source_type": "SIMULATED",
            "kind": kind, "facts_sha256": snapshot["snapshot_sha256"], "offset": offset, "limit": 25,
            "total": len(records[kind]), "records": records[kind][offset:offset + 25],
            "private_body_available_here": False, "business_mutation_performed": False, "read_at": now()}
