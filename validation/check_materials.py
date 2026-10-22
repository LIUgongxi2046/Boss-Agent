import json
import uuid

from business import ROOT, SPEC, Store, encode, now


def main():
    run_id = "materials-" + str(uuid.uuid4())
    store = Store(ROOT / ".work" / run_id / "business.sqlite")
    baseline = store.initialize(run_id)
    with store.connect() as db:
        data = json.loads(db.execute("SELECT body FROM objects WHERE namespace=? AND kind='initial'", (run_id,)).fetchone()[0])
        configuration = store.get(db, run_id, "configuration", "current")
        schedule = store.get(db, run_id, "schedule", "current")
    kinds = {"boss_profile": [data["boss_profile"]], "contacts": data["contacts"], "business_details": data["details"], "metric_definitions": data["metric_definitions"], "meeting": [data["meeting"]], "documents": data["documents"], "event_and_task": [data["event"]], "private_calendar": [data["private_calendar"]], "runtime_configuration": [configuration], "schedule_and_memory": [{**schedule, **data["memory"]}]}
    fields = []
    for definition in SPEC["initial_materials"]["objects"]:
        rows = kinds[definition["kind"]]
        assert rows and all(set(definition["required_fields"]) <= set(row) for row in rows), definition["id"]
        fields.append({"object_id": definition["id"], "rows": len(rows), "required_fields": definition["required_fields"], "status": "PASS"})
    owner = data["boss_profile"]["owner_id"]
    assert all(item["owner_id"] == owner for item in [data["meeting"], data["event"], data["historical_task"], data["private_calendar"]])
    contacts = {item["contact_id"] for item in data["contacts"]}
    assert len(contacts) == len(data["contacts"]) and len({item["name"] for item in data["contacts"]}) < len(contacts)
    assert set(data["meeting"]["participant_ids"]) <= contacts
    assert data["event"]["coordinator_id"] in contacts and all(document["author_contact_id"] in contacts for document in data["documents"])
    assert data["event"]["meeting_id"] == data["meeting"]["meeting_id"]
    assert data["event"]["task_id"] == data["historical_task"]["task_id"]
    assert data["meeting"]["historical_commitment_ids"] == [data["historical_task"]["task_id"]]
    assert set(data["meeting"]["material_ids"]) <= {document["source_id"] for document in data["documents"]} | {data["event"]["event_id"]}
    assert data["source_type"] == "SIMULATED" and all(document["source_type"] == "SIMULATED" for document in data["documents"])
    output = ROOT.parent / "evidence/T02" / run_id
    output.mkdir(parents=True)
    result = {"status": "PASS", "at": now(), "baseline": baseline, "generator_version": data["generator_version"], "fields": fields, "relations": "老板归属、同名人员独立标识、作者、参会人、事件、会议和历史任务关联均已独立检查", "credential_ref": configuration["credential_ref"]}
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(encode({**result, "evidence": str(output)}))


if __name__ == "__main__":
    main()
