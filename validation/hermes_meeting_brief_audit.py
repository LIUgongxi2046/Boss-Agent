import json

from business import checksum


SECTION_FIELDS = {
    "AGENDA": None,
    "CONSENSUS": None,
    "DECISION": None,
    "CONFLICT": ("travel_impacts", "people_meeting_impacts"),
    "COMMITMENT": ("commitments",),
    "FACT": ("sources", "metrics"),
    "MISSING": ("missing_items",),
}
REQUIRED_KINDS = ("AGENDA", "CONSENSUS", "CONFLICT", "DECISION")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_facts(compiled):
    facts = []
    for source in compiled["sources"]:
        if source.get("status") == "CURRENT" and isinstance(source.get("excerpt"), str) and source["excerpt"].strip():
            facts.append((source["excerpt"].strip(), source["source_id"]))
    for period in compiled.get("metrics", {}).get("values", []):
        facts.append((_canonical(period), "finance-note"))
    return facts


def _canonical_commitments(compiled, members):
    results = []
    for item in compiled.get("commitments", []):
        member = members.get(("task", item["task_id"]))
        if member is None or not member.get("version") or not member.get("sha256"):
            continue
        results.append((_canonical({"task_id": item.get("task_id"), "status": item.get("status"),
                                    "due_at": item.get("due_at"), "evidence_requirements": item.get("evidence_requirements"),
                                    "version": member["version"], "sha256": member["sha256"]}), item["task_id"]))
    return results


def audit_meeting_brief(context, sections):
    meeting = context["meeting"]
    compiled = context["compiled"]
    sources = {item["source_id"]: {"version": item.get("version"), "sha256": item.get("source_sha256")}
               for item in compiled["sources"]}
    facts = _canonical_facts(compiled)
    commitments = _canonical_commitments(compiled, {(item["entity_type"], item["object_id"]): item
                                                     for item in context.get("members", [])})
    missing = [item for item in compiled.get("missing_items", []) if isinstance(item, str) and item]
    present = {section["kind"] for section in sections}
    missing_categories = [kind for kind in REQUIRED_KINDS if kind not in present]
    results = []
    gaps = [{"kind": kind, "reason": "MISSING_REQUIRED_CATEGORY"} for kind in missing_categories]
    hard_blocked = bool(missing_categories)
    for section in sections:
        kind = section["kind"]
        text = section["text"].strip()
        cited = []
        for source_id in section["source_ids"]:
            source = sources.get(source_id)
            if source is None:
                gaps.append({"kind": kind, "source_id": source_id, "reason": "SOURCE_NOT_IN_DOMAIN_BRIEF"})
                continue
            if not isinstance(source["version"], str) or not source["version"] or not isinstance(source["sha256"], str):
                gaps.append({"kind": kind, "source_id": source_id, "reason": "SOURCE_VERSION_OR_DIGEST_MISSING"})
                continue
            cited.append({"source_id": source_id, **source})
        status = "UNVERIFIED_CONTENT"
        reason = "当前字段无法与本段自由正文逐项比对"
        fields = SECTION_FIELDS.get(kind)
        candidates = []
        if fields is None:
            status = "MISSING_DOMAIN_FIELD"
            reason = "当前领域会议对象没有该字段"
            hard_blocked = True
        elif kind == "CONFLICT":
            schedule = [item for key in fields for item in compiled.get(key, [])]
            if not schedule:
                status = "MISSING_DOMAIN_FIELD"
                reason = "当前领域没有会议安排冲突记录"
                hard_blocked = True
            else:
                status = "UNVERIFIED_CONTENT"
                reason = "只覆盖会议安排影响，会议讨论冲突没有逐项正文比对"
        elif kind == "COMMITMENT":
            if not compiled.get("commitments"):
                status = "MISSING_DOMAIN_FIELD"
                reason = "当前领域没有会议承诺记录"
                hard_blocked = True
            else:
                candidates = commitments
                if not candidates:
                    status = "BLOCKED"
                    reason = "承诺任务版本或摘要未绑定"
                    hard_blocked = True
        elif kind == "FACT":
            if not facts:
                status = "MISSING_DOMAIN_FIELD"
                reason = "当前领域没有会议事实来源"
                hard_blocked = True
            else:
                candidates = facts
        elif kind == "MISSING":
            if not missing:
                status = "MISSING_DOMAIN_FIELD"
                reason = "当前领域没有缺失项记录"
                hard_blocked = True
            else:
                candidates = [(item, None) for item in missing]
        if status not in {"MISSING_DOMAIN_FIELD", "BLOCKED"} and candidates:
            matching = [(candidate, source_id) for candidate, source_id in candidates if text == candidate]
            exact = next(((candidate, source_id) for candidate, source_id in matching
                          if source_id is None or kind == "COMMITMENT" or source_id in {item["source_id"] for item in cited}), None)
            if exact is not None:
                status = "SUPPORTED"
                reason = "正文与领域字段逐项一致"
            elif matching:
                status = "BLOCKED"
                reason = "正文事实绑定了另一个有效来源"
                hard_blocked = True
            elif any(candidate and candidate in text for candidate, _ in candidates):
                status = "BLOCKED"
                reason = "正文混入已核查字段之外的无依据内容"
                hard_blocked = True
            else:
                gaps.append({"kind": kind, "reason": "CONTENT_NOT_COMPARABLE_TO_DOMAIN_FIELD"})
        if status == "SUPPORTED" and kind != "MISSING" and not cited:
            status = "BLOCKED"
            reason = "会议整理缺少可核查来源版本"
            hard_blocked = True
        if status == "SUPPORTED" and any(gap["kind"] == kind and gap.get("source_id") for gap in gaps):
            status = "BLOCKED"
            reason = "会议整理引用了无效来源"
            hard_blocked = True
        if status in {"MISSING_DOMAIN_FIELD", "BLOCKED"}:
            gaps.append({"kind": kind, "reason": reason})
        elif status == "UNVERIFIED_CONTENT":
            gaps.append({"kind": kind, "reason": reason})
        results.append({"kind": kind, "status": status, "reason": reason, "cited_sources": cited})
    if hard_blocked:
        completion = "BLOCKED"
    elif any(item["status"] == "UNVERIFIED_CONTENT" for item in results):
        completion = "UNVERIFIED"
    else:
        completion = "PASS"
    return {
        "meeting_id": meeting["meeting_id"],
        "meeting_version": meeting["version"],
        "meeting_sha256": checksum(meeting),
        "sections": results,
        "gaps": gaps,
        "missing_categories": missing_categories,
        "completion_state": completion,
    }
