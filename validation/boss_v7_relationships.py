from datetime import date

from aiohttp import web

from business import now, require
from boss_meetings import meeting_materials
from boss_v7_store import NAMESPACE, rows, text


def read_relationships(store, db, snapshot):
    data = meeting_materials(db, snapshot)
    tasks = rows(db, "task")
    documents = rows(db, "document")
    meeting = data["meeting"]
    records = []
    for contact in data["contacts"]:
        identifier = contact["contact_id"]
        relations = [{"id": item["source_id"], "kind": "SOURCE_AUTHOR", "version": item["version"],
                      "state": "WITHDRAWN" if item.get("withdrawn") else "RECORDED"} for item in documents if item.get("author_contact_id") == identifier]
        relations += [{"id": task["task_id"], "kind": "TASK_COORDINATOR", "version": task["version"], "state": task["status"]}
                      for task in tasks if task.get("coordinator_id") == identifier]
        if identifier in meeting["participant_ids"]:
            relations.append({"id": meeting["meeting_id"], "kind": "MEETING_PARTICIPANT", "version": meeting["version"], "state": meeting.get("state", "RECORDED")})
        records.append({"id": identifier, "kind": "contact", "name": contact["name"],
                        "version": contact.get("version", data["dataset_version"]), "source_id": data["dataset_id"],
                        "source_type": data["source_type"], "responsibility": contact["responsibility"], "organization": contact["organization"],
                        "valid_from": contact["valid_from"], "valid_until": contact["valid_until"], "state": "SIMULATED_CONTACT",
                        "editable": data["source_type"] == "SIMULATED", "relations": relations})
    records.append({"id": meeting["meeting_id"], "kind": "meeting", "name": meeting["meeting_id"], "version": meeting["version"],
                    "source_id": data["dataset_id"], "source_type": data["source_type"], "responsibility": "", "organization": "",
                    "valid_from": meeting["starts_at"], "valid_until": meeting.get("ends_at") or "", "state": meeting.get("state", "RECORDED"),
                    "editable": False, "relations": [{"id": identifier, "kind": "MATERIAL", "version": source["version"],
                                                       "state": "WITHDRAWN" if source.get("withdrawn") else "RECORDED"}
                                                      for identifier in meeting["material_ids"] for source in documents if source["source_id"] == identifier]})
    for task in tasks:
        records.append({"id": task["task_id"], "kind": "matter", "name": task["task_id"], "version": task["version"],
                        "source_id": data["dataset_id"], "source_type": data["source_type"], "responsibility": "", "organization": "",
                        "valid_from": task.get("created_at", ""), "valid_until": task.get("due_at", ""), "state": task["status"], "editable": False,
                        "relations": [{"id": task["coordinator_id"], "kind": "COORDINATOR", "version": contact.get("version", data["dataset_version"]), "state": "SIMULATED_CONTACT"}
                                      for contact in data["contacts"] if contact["contact_id"] == task.get("coordinator_id")]})
    return {"records": records}


def save_contact(api, db, snapshot, payload):
    api._exact(payload, {"client_request_id", "object_id", "expected_version", "values"})
    require(snapshot["source_type"] == "SIMULATED", "仅能维护获准模拟资料", web.HTTPForbidden)
    found = [row for row in snapshot["contacts"] if row["contact_id"] == payload["object_id"]]
    require(len(found) == 1, "当前对象不属于可维护的模拟联系人", web.HTTPForbidden)
    current = found[0]
    version = current.get("version", snapshot["dataset_version"])
    require(version == payload["expected_version"], "联系人版本已经变化")
    values = payload["values"]
    require(isinstance(values, dict), "联系人字段无效", web.HTTPBadRequest)
    api._exact(values, {"name", "organization", "responsibility", "valid_from", "valid_until"})
    for key in ("name", "organization", "responsibility"):
        text(values[key], key, 300)
    start = date.fromisoformat(values["valid_from"])
    end = date.fromisoformat(values["valid_until"])
    require(start < end, "职责有效期无效", web.HTTPBadRequest)
    api.store.put(db, NAMESPACE, "contact_revision", current["contact_id"] + ":" + version, {**current, "version": version})
    updated = {**current, **values, "version": str(int(version) + 1), "updated_at": now()}
    snapshot["contacts"] = [updated if row["contact_id"] == current["contact_id"] else row for row in snapshot["contacts"]]
    api.store.put(db, NAMESPACE, "initial", "snapshot", snapshot)
    return {"object_id": current["contact_id"], "version": updated["version"], "state": "SAVED"}
