import json

import pytest

from business import Store, checksum

from boss_meeting_brief import compile_brief
from hermes_meeting_brief_audit import audit_meeting_brief
from hermes_meeting_brief_public import safe_section_audit, validate_safe_section_audit


def test_section_domain_support_reports_missing_fields_without_inference(tmp_path):
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
        {"kind": "MISSING", "text": "缺少原因贡献明细", "source_ids": []},
    ]
    audit = audit_meeting_brief(context, sections)
    by_kind = {item["kind"]: item for item in audit["sections"]}
    assert audit["meeting_id"] == "meeting-1"
    assert audit["meeting_version"] == data["meeting"]["version"]
    assert by_kind["AGENDA"]["status"] == "MISSING_DOMAIN_FIELD"
    assert by_kind["CONSENSUS"]["status"] == "MISSING_DOMAIN_FIELD"
    assert by_kind["DECISION"]["status"] == "MISSING_DOMAIN_FIELD"
    assert by_kind["CONFLICT"]["status"] not in {"SUPPORTED", "PASS"}
    assert by_kind["COMMITMENT"]["status"] == "UNVERIFIED_CONTENT"
    assert by_kind["FACT"]["status"] == "UNVERIFIED_CONTENT"
    assert by_kind["MISSING"]["status"] != "SUPPORTED"
    fact_source = by_kind["FACT"]["cited_sources"]
    assert fact_source == [{"source_id": "finance-note", "version": "1", "sha256": checksum(data["documents"][0])}]
    assert audit["completion_state"] == "BLOCKED"
    assert {gap["kind"] for gap in audit["gaps"]} >= {"AGENDA", "CONSENSUS", "DECISION"}

    finance = next(item for item in compiled["sources"] if item["source_id"] == "finance-note")
    exact = audit_meeting_brief(context, [{"kind": "FACT", "text": finance["excerpt"], "source_ids": ["finance-note"]}])
    assert exact["sections"][0]["status"] == "SUPPORTED"
    assert exact["completion_state"] == "BLOCKED"
    assert set(exact["missing_categories"]) == {"AGENDA", "CONSENSUS", "CONFLICT", "DECISION"}
    wrong_source = audit_meeting_brief(context, [{"kind": "FACT", "text": finance["excerpt"], "source_ids": ["meeting-minutes"]}])
    assert wrong_source["sections"][0]["status"] == "BLOCKED"
    assert any("另一个有效来源" in gap["reason"] for gap in wrong_source["gaps"])
    mixed = audit_meeting_brief(context, [{"kind": "FACT", "text": finance["excerpt"] + " 预计下季度增长20%", "source_ids": ["finance-note"]}])
    assert mixed["sections"][0]["status"] == "BLOCKED"
    assert mixed["completion_state"] == "BLOCKED"
    assert any("无依据内容" in gap["reason"] for gap in mixed["gaps"])

    empty = audit_meeting_brief(context, [])
    assert empty["sections"] == []
    assert empty["completion_state"] == "BLOCKED"
    assert set(empty["missing_categories"]) == {"AGENDA", "CONSENSUS", "CONFLICT", "DECISION"}

    commitment = next(item for item in compiled["commitments"] if item["task_id"] == "historical-1")
    canonical = {"task_id": commitment["task_id"], "status": commitment["status"], "due_at": commitment["due_at"],
                 "evidence_requirements": commitment["evidence_requirements"], "version": data["historical_task"]["version"],
                 "sha256": checksum(data["historical_task"])}
    text = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    verified = audit_meeting_brief(context, [{"kind": "COMMITMENT", "text": text, "source_ids": ["meeting-minutes"]}])
    assert verified["sections"][0]["status"] == "SUPPORTED"
    wrong_version = json.dumps({**canonical, "version": "2"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    changed = audit_meeting_brief(context, [{"kind": "COMMITMENT", "text": wrong_version, "source_ids": ["meeting-minutes"]}])
    assert changed["sections"][0]["status"] != "SUPPORTED"
    assert changed["completion_state"] != "PASS"

    safe = safe_section_audit(audit)
    assert set(safe) == {"audit_version", "completion_state", "section_count", "missing_categories", "blocked_kinds", "unverified_kinds"}
    assert safe["audit_version"] == 1
    assert safe["completion_state"] == "BLOCKED"
    assert safe["section_count"] == len(sections)
    assert {"AGENDA", "CONSENSUS", "DECISION"}.issubset(set(safe["blocked_kinds"]))
    assert "meeting_id" not in safe and "meeting_version" not in safe
    assert all(isinstance(item, str) for item in safe["blocked_kinds"] + safe["unverified_kinds"] + safe["missing_categories"])
    validate_safe_section_audit(safe)
    with pytest.raises(ValueError):
        validate_safe_section_audit({**safe, "meeting_id": "meeting-1"})
