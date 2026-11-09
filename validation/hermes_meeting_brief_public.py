SAFE_AUDIT_VERSION = 1
SAFE_AUDIT_FIELDS = {"audit_version", "completion_state", "section_count", "missing_categories", "blocked_kinds", "unverified_kinds"}
AUDIT_KINDS = {"AGENDA", "FACT", "COMMITMENT", "CONSENSUS", "CONFLICT", "DECISION", "MISSING"}


def safe_section_audit(value):
    if not isinstance(value, dict) or value.get("completion_state") not in {"PASS", "UNVERIFIED", "BLOCKED"}:
        raise ValueError("会议简报段落审计状态无效")
    missing_categories, sections = value.get("missing_categories"), value.get("sections")
    if not isinstance(missing_categories, list) or any(item not in AUDIT_KINDS for item in missing_categories):
        raise ValueError("会议简报段落审计缺失类别无效")
    if not isinstance(sections, list) or any(not isinstance(item, dict) or item.get("kind") not in AUDIT_KINDS or item.get("status") not in {"SUPPORTED", "UNVERIFIED_CONTENT", "MISSING_DOMAIN_FIELD", "BLOCKED"} for item in sections):
        raise ValueError("会议简报段落审计段落无效")
    blocked = sorted({item["kind"] for item in sections if item["status"] in {"MISSING_DOMAIN_FIELD", "BLOCKED"}})
    unverified = sorted({item["kind"] for item in sections if item["status"] == "UNVERIFIED_CONTENT"})
    return {
        "audit_version": SAFE_AUDIT_VERSION,
        "completion_state": value["completion_state"],
        "section_count": len(sections),
        "missing_categories": list(missing_categories),
        "blocked_kinds": blocked,
        "unverified_kinds": unverified,
    }


def validate_safe_section_audit(value):
    if not isinstance(value, dict) or set(value) != SAFE_AUDIT_FIELDS:
        raise ValueError("会议简报段落审计公开字段无效")
    if value.get("audit_version") != SAFE_AUDIT_VERSION or value.get("completion_state") not in {"PASS", "UNVERIFIED", "BLOCKED"}:
        raise ValueError("会议简报段落审计公开状态无效")
    if type(value.get("section_count")) is not int or value["section_count"] < 0:
        raise ValueError("会议简报段落审计公开数量无效")
    for key in ("missing_categories", "blocked_kinds", "unverified_kinds"):
        items = value.get(key)
        if not isinstance(items, list) or any(item not in AUDIT_KINDS for item in items) or len(set(items)) != len(items):
            raise ValueError("会议简报段落审计公开类别无效")
