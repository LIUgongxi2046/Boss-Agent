from business import Store, checksum
from boss_meeting_brief import compile_brief
from agent_artifact_meeting_brief import audit_meeting_sections
from agent_run_api import VALIDATORS


def test_meeting_section_audit_reports_gaps_and_source_versions(tmp_path):
    store = Store(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
        compiled = compile_brief(db, data)
    context = {
        "meeting": data["meeting"],
        "compiled": compiled,
        "members": [{"entity_type": "task", "object_id": "historical-1", "version": data["historical_task"]["version"],
                     "sha256": checksum(data["historical_task"])}],
    }
    sections = [
        {"kind": "AGENDA", "text": "会议议题", "source_ids": ["meeting-minutes"]},
        {"kind": "CONSENSUS", "text": "会议共识", "source_ids": ["meeting-minutes"]},
        {"kind": "CONFLICT", "text": "会议冲突", "source_ids": ["meeting-minutes"]},
        {"kind": "DECISION", "text": "待决定问题", "source_ids": ["meeting-minutes"]},
        {"kind": "COMMITMENT", "text": "历史承诺", "source_ids": ["meeting-minutes"]},
        {"kind": "FACT", "text": "财务事实", "source_ids": ["finance-note"]},
    ]
    audit = audit_meeting_sections(context, sections)
    by_kind = {item["kind"]: item for item in audit["sections"]}
    assert audit["meeting_id"] == data["meeting"]["meeting_id"]
    assert audit["meeting_version"] == data["meeting"]["version"]
    assert audit["completion_state"] == "BLOCKED"
    assert audit["missing_categories"] == []
    assert by_kind["AGENDA"]["status"] == "MISSING_DOMAIN_FIELD"
    assert by_kind["CONSENSUS"]["status"] == "MISSING_DOMAIN_FIELD"
    assert by_kind["DECISION"]["status"] == "MISSING_DOMAIN_FIELD"
    assert by_kind["FACT"]["cited_sources"] == [
        {"source_id": "finance-note", "version": "1", "sha256": checksum(data["documents"][0])}]
    assert by_kind["COMMITMENT"]["status"] in {"UNVERIFIED_CONTENT", "BLOCKED"}
    schema = VALIDATORS["completion_inspection"].schema["$defs"]["completion_inspection"]["properties"]["brief_section_audits"]
    from jsonschema import Draft202012Validator
    Draft202012Validator({**schema, "$defs": VALIDATORS["completion_inspection"].schema["$defs"]}).validate(
        [{"artifact_id": "artifact-1", "version": 1, "section_audit": audit}]
    )


def test_empty_sections_audit_reports_all_missing_without_saving(tmp_path):
    store = Store(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
        compiled = compile_brief(db, data)
    context = {"meeting": data["meeting"], "compiled": compiled, "members": []}
    audit = audit_meeting_sections(context, [])
    assert audit["sections"] == []
    assert audit["completion_state"] == "BLOCKED"
    assert set(audit["missing_categories"]) == {"AGENDA", "CONSENSUS", "CONFLICT", "DECISION"}
