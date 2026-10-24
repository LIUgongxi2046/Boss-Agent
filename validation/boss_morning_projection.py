import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, available_timezones

from aiohttp import web

from business import checksum, now, require
from boss_owner_preferences import owner_profile
from boss_source_policy import source_validity

FINAL = {"CANCELED", "COMPLETED_CONFIRMED", "HELD", "DELETED", "CLOSED", "APPROVED", "REJECTED"}


def object_at(db, namespace, kind, identifier):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (namespace, kind, identifier)).fetchone()
    return json.loads(row[0]) if row else None


def order_key(day, initial):
    return day["date"] if day["timezone"] == initial["boss_profile"]["timezone"] else day["date"] + "|" + day["timezone"]


def _instant(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, "业务时间缺少时区", web.HTTPBadRequest)
    return result


def project(store, db, context, day):
    require(day["timezone"] in available_timezones(), "IANA时区无效", web.HTTPBadRequest)
    selected = date.fromisoformat(day["date"])
    require(selected < date.max, "业务日期超出允许范围", web.HTTPBadRequest)
    zone = ZoneInfo(day["timezone"])
    start, end = datetime.combine(selected, time.min, zone), datetime.combine(selected + timedelta(days=1), time.min, zone)
    ns, owner = context["namespace"], context["owner_id"]
    initial = store.get(db, ns, "initial", "snapshot")
    clock = store.get(db, ns, "clock", "current")
    profile = owner_profile(db, initial, ns)
    rules = object_at(db, ns, "rules", "current")
    rule_valid = rules is not None and rules.get("enabled", True) and (rules.get("valid_from") is None or _instant(rules["valid_from"]) <= _instant(clock["at"])) and (rules.get("valid_until") is None or _instant(clock["at"]) < _instant(rules["valid_until"]))
    rows = {}
    kinds = ("task", "self_commitment", "application", "meeting", "event", "private_calendar", "travel_plan")
    for kind in kinds:
        for identifier, body in db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind=? AND (json_extract(body,'$.owner_id') IS NULL OR json_extract(body,'$.owner_id')=?) ORDER BY id", (ns, kind, owner)).fetchall():
            row = json.loads(body)
            require(all(row.get(field, context[field]) == context[field] for field in ("dataset_id", "dataset_version"))
                    and row.get("execution_namespace", ns) == ns, "晨间对象不属于当前执行范围", web.HTTPForbidden)
            rows[kind, identifier] = row
    for kind, identifier, body in (("meeting", initial["meeting"]["meeting_id"], initial["meeting"]),
                                   ("private_calendar", initial["private_calendar"]["calendar_id"], initial["private_calendar"])):
        if (kind, identifier) not in rows:
            metadata = db.execute("SELECT json_extract(body,'$.owner_id') FROM objects WHERE namespace=? AND kind=? AND id=?", (ns, kind, identifier)).fetchone()
            require(metadata is None or metadata[0] in (None, owner), "当前资料对象无权访问", web.HTTPForbidden)
            rows[kind, identifier] = body
    historical = initial.get("historical_task")
    if historical and ("task", historical["task_id"]) not in rows:
        rows["historical_task", historical["task_id"]] = historical
    event = initial["event"]
    if ("event", event["event_id"]) not in rows:
        rows["event", event["event_id"]] = {**event, "state": event["status"]}
    items, excluded, sources, source_documents, preparation, measure_objects = [], [], {}, {}, [], {}
    missing = {"REGIONAL_COVERAGE_NOT_PROVIDED", "COMPLETE_EXTERNAL_CALENDAR_NOT_VERIFIED", "SOURCE_REFRESH_COVERAGE_NOT_PROVIDED"}
    if profile["owner_confirmation"] != "CONFIRMED":
        missing.add("OWNER_GOALS_NOT_SET")
    if rules is None:
        missing.add("PRIORITY_RULES_NOT_CONFIGURED")
    current_date = _instant(clock["at"]).astimezone(zone).date()
    if selected < current_date:
        missing.add("HISTORICAL_STATE_NOT_RECONSTRUCTED")
    elif selected > current_date:
        missing.add("FUTURE_STATE_NOT_PREDICTED")

    def source(identifier):
        if identifier in sources:
            return sources[identifier]
        metadata = db.execute("SELECT json_extract(body,'$.access_scope'),json_extract(body,'$.version') FROM objects WHERE namespace=? AND kind='document' AND id=?", (ns, identifier)).fetchone()
        if metadata is None or metadata[0] != owner:
            result = {"source_id": identifier, "version": None, "status": "MISSING" if metadata is None else "FORBIDDEN", "author_contact_id": None, "published_at": None, "observed_at": None, "locator": None}
        else:
            document = store.get(db, ns, "document", identifier)
            status = source_validity(document, clock["at"])
            if document.get("simulation_definition") == "si09-si10-business-v1":
                from boss_supply_quality import external_adoption
                adoption = external_adoption(db, ns, initial, clock["at"], document)
                if adoption["state"] != "CURRENT":
                    status = "NEEDS_REIMPORT"
            source_documents[identifier] = document
            result = {"source_id": identifier, "version": document["version"], "status": status,
                      "source_type": document.get("source_type"), "valid_from": document.get("valid_from"), "valid_until": document.get("valid_until"),
                      "author_contact_id": document.get("author_contact_id"), "published_at": document.get("published_at"),
                      "observed_at": document.get("observed_at"), "locator": document.get("original_locator")}
        sources[identifier] = result
        if result["status"] != "VALID":
            missing.add("SOURCE_" + result["status"] + ":" + identifier)
        return result

    def append(kind, identifier, row):
        state = row.get("status", row.get("state", "ACTIVE" if kind == "private_calendar" else "DRAFT"))
        version = row.get("version", "1")
        reason = None
        if state in FINAL or state in ("RECOVERED", "PAUSED"):
            reason = "TERMINAL_OR_NOT_ACTIVE"
        if kind == "application" and state not in ("PENDING_DECISION", "WAITING_MATERIAL"):
            reason = "TERMINAL_OR_NOT_ACTIVE"
        due = row.get("due_at")
        begin, finish = row.get("starts_at"), row.get("ends_at")
        preparation_due = row.get("preparation_due_at")
        if kind == "meeting":
            due = preparation_due or begin
        urgent = False
        if rule_valid and rules["important_escalation"]:
            for (event_kind, event_id), candidate in rows.items():
                if event_kind == "event" and candidate["state"] == "OPEN" and candidate.get("impact") == "IMPORTANT":
                    linked = candidate.get("task_id", candidate.get("commitment_id"))
                    valid_refs = all(source(ref if isinstance(ref, str) else ref["source_id"])["status"] == "VALID"
                                     and (isinstance(ref, str) or ref.get("version") == source(ref["source_id"])["version"]) for ref in candidate.get("source_refs", []))
                    urgent = urgent or valid_refs and (event_id == identifier and kind == "event" or linked == identifier and kind in ("task", "historical_task", "self_commitment"))
        if kind == "travel_plan":
            details = row.get("current")
            if details is None or state != "CONFIRMED":
                reason = "NO_CURRENT_CONFIRMED_TRAVEL"
            else:
                begin = (_instant(details["starts_at"]) - timedelta(minutes=details["buffer_minutes"])).isoformat()
                finish = (_instant(details["ends_at"]) + timedelta(minutes=details["buffer_minutes"])).isoformat()
        if begin is not None:
            if (_instant(begin) >= end and not (preparation_due and _instant(preparation_due) < end)) or (finish is not None and _instant(finish) <= start):
                reason = "OUTSIDE_SELECTED_DAY"
            elif finish is None and _instant(begin) < start:
                reason = "UNKNOWN_END_OUTSIDE_START_DAY"
                missing.add("UNKNOWN_END:" + identifier)
        not_before = row.get("not_before")
        if not_before is not None and _instant(not_before) >= end and not urgent:
            reason = "BEFORE_APPLICABLE_DAY"
        if reason:
            excluded.append({"kind": kind, "id": identifier, "version": version, "reason": reason})
            return
        category = "DECIDE" if kind == "application" or state == "RESULT_SUBMITTED" else "INFORM" if kind in ("event", "private_calendar") else "COORDINATE"
        participation = {"task": "交办仍需本人跟进负责人和期限", "historical_task": "本人需要核查历史承诺", "self_commitment": "本人承诺需要履行及证据核查", "application": "当前申请需要本人决定或补充材料", "meeting": "本人需要核查会议安排与准备材料", "private_calendar": "本人需要协调私人占用与工作时间", "event": "本人需要了解当前经营事件及已有措施", "travel_plan": "本人需要协调出行时间与会议"}[kind]
        raw_refs = list(row.get("source_refs", row.get("attachment_refs", [])))
        if row.get("source_id") and not any((ref if isinstance(ref, str) else ref["source_id"]) == row["source_id"] for ref in raw_refs):
            raw_refs.append({"source_id": row["source_id"], "version": row.get("source_version")})
        documents, object_refs = [], []
        assignment_binding = object_at(db, ns, "assignment_source_binding", identifier) if kind == "task" else None
        for reference in raw_refs:
            sid = reference if isinstance(reference, str) else reference["source_id"]
            info = source(sid)
            documents.append(info)
            if isinstance(reference, dict) and reference.get("version") != info["version"]:
                reason = "SOURCE_VERSION_CHANGED"
                missing.add("SOURCE_VERSION_CHANGED:" + sid)
            if kind == "task" and (assignment_binding is None or assignment_binding["source_versions"].get(sid) != info["version"]
                                   or sid in source_documents and assignment_binding["source_fingerprints"].get(sid) != checksum(source_documents[sid])):
                reason = "ASSIGNMENT_SOURCES_REQUIRE_REVIEW"
                missing.add("ASSIGNMENT_SOURCES_REQUIRE_REVIEW:" + identifier)
        for sid in row.get("material_ids", []):
            related = [(related_kind, related_row) for (related_kind, object_id), related_row in rows.items() if object_id == sid]
            if related:
                object_refs.extend({"kind": related_kind, "id": sid, "version": related_row.get("version", "1")} for related_kind, related_row in related)
                continue
            documents.append(source(sid))
        if reason or any(item["status"] != "VALID" for item in documents):
            excluded.append({"kind": kind, "id": identifier, "version": version, "reason": reason or "SOURCE_NOT_CURRENT"})
            return
        title = row.get("purpose", row.get("title", {"meeting": "会议与会前材料", "historical_task": "历史承诺", "event": "经营事件", "travel_plan": "本人出行安排"}.get(kind, "本人事项")))
        if kind == "private_calendar":
            title = "本人私人安排"
        goal_matches = [goal for goal in profile["goals"] if goal in title]
        item = {"item_id": kind + ":" + identifier, "kind": kind, "object_id": identifier, "version": version,
                "title": title, "category": category, "state": state, "reason": participation,
                "coordinator_id": row.get("coordinator_id", owner if kind in ("self_commitment", "private_calendar", "travel_plan", "application", "meeting") else None),
                "due_at": due, "starts_at": begin, "ends_at": finish, "important": False,
                "source_refs": [{"kind": kind, "id": identifier, "version": version}] + object_refs + [{"kind": "document", "id": item["source_id"], "version": item["version"]} for item in documents],
                "sorting_reasons": ["CATEGORY:" + category], "goal_matches": goal_matches,
                "existing_measures": [],
                "page_id": {"task": "F06", "historical_task": "F04", "self_commitment": "N05", "application": "F07", "meeting": "F04", "event": "F02", "private_calendar": "F12", "travel_plan": "F11"}[kind],
                "target_id": initial["meeting"]["meeting_id"] if kind == "historical_task" else row.get("related_meeting_id"), "read_only": kind == "historical_task"}
        if goal_matches:
            item["sorting_reasons"].append("MATCHES_CONFIRMED_OWNER_GOAL")
        if due:
            item["sorting_reasons"].append("OVERDUE_AT_SELECTED_DAY" if _instant(due) < start else "FUTURE_DEADLINE_BACKLOG" if _instant(due) >= end else "DUE_WITHIN_SELECTED_DAY")
        else:
            item["sorting_reasons"].append("NO_DEADLINE_PROVIDED")
        if begin and not finish:
            missing.add("UNKNOWN_END:" + identifier)
        preparation.append({"item_id": item["item_id"], "documents": documents, "requirements": row.get("evidence_requirements", []), "preparation_due_at": row.get("preparation_due_at")})
        if not documents:
            missing.add("DOCUMENT_SOURCE_NOT_PROVIDED:" + item["item_id"])
        items.append(item)

    for (kind, identifier), row in rows.items():
        if kind != "event":
            append(kind, identifier, row)
    for (kind, identifier), row in rows.items():
        if kind != "event":
            continue
        event_sources = row.get("source_refs", [])
        if any(source(ref if isinstance(ref, str) else ref["source_id"])["status"] != "VALID"
               or isinstance(ref, dict) and ref.get("version") != source(ref["source_id"])["version"] for ref in event_sources):
            excluded.append({"kind": kind, "id": identifier, "version": row["version"], "reason": "SOURCE_NOT_CURRENT"})
            continue
        related = row.get("task_id") or row.get("commitment_id")
        if identifier == initial["event"]["event_id"]:
            related = initial["event"].get("task_id")
        target = next((item for item in items if item["object_id"] == related and item["kind"] in ("task", "historical_task", "self_commitment")), None)
        if target is not None and row["state"] == "OPEN":
            target["source_refs"].append({"kind": "event", "id": identifier, "version": row["version"]})
        else:
            append(kind, identifier, row)
            target = next((item for item in items if item["item_id"] == "event:" + identifier), None)
        if target is not None and row["state"] == "OPEN" and row.get("impact") == "IMPORTANT" and rule_valid and rules["important_escalation"]:
            target["important"] = True
            target["sorting_reasons"].append("CURRENT_IMPORTANT_EVENT_RULE:" + rules["version"])
        if target is not None:
            for measure_kind, measure_id in (("owner_plan", row.get("owner_plan_id")), ("reminder", identifier)):
                measure = object_at(db, ns, measure_kind, measure_id) if measure_id is not None else None
                if measure is None:
                    continue
                require(measure.get("owner_id", owner) == owner, "当前处理措施无权访问", web.HTTPForbidden)
                ref = {"kind": measure_kind, "id": measure_id, "version": measure.get("version", "1")}
                auth = object_at(db, ns, "authorization", measure["authorization_id"]) if measure.get("authorization_id") else None
                target["existing_measures"].append({**ref, "state": measure["state"], "authorization_revoked": auth.get("revoked") if auth else None})
                target["source_refs"].append(ref)
                measure_objects[measure_kind + ":" + measure_id] = measure
    priority = {"DECIDE": 0, "COORDINATE": 1, "INFORM": 2}
    coverage = object_at(db, ns, "morning_coverage", order_key(day, initial))
    regions = []
    if coverage:
        require(coverage["owner_id"] == owner and coverage["execution_namespace"] == ns and coverage["dataset_id"] == context["dataset_id"] and coverage["dataset_version"] == context["dataset_version"], "晨间覆盖不属于当前范围", web.HTTPForbidden)
        info = source(coverage["source_id"])
        if info["status"] == "VALID" and info["version"] == coverage["source_version"]:
            regions = coverage["regions"]
            missing.discard("REGIONAL_COVERAGE_NOT_PROVIDED")
            missing.add("FULL_REGIONAL_COVERAGE_NOT_VERIFIED")
            missing.update("REGION_" + row["state"] + ":" + row["region_id"] for row in regions if row["state"] != "CURRENT")
    items.sort(key=lambda item: (not item["important"], priority[item["category"]], not bool(item["goal_matches"]), _instant(item["due_at"]).timestamp() if item["due_at"] else float("inf"), item["item_id"]))
    snapshot = checksum({"day": day, "clock": clock, "profile": profile, "rules": rules, "items": items, "excluded": excluded,
                         "source_statuses": sources, "source_documents": source_documents, "coverage": coverage, "measures": measure_objects, "objects": {kind + ":" + identifier: row for (kind, identifier), row in rows.items()}})
    preference = object_at(db, ns, "today_order", order_key(day, initial))
    if preference:
        positions = {identifier: index for index, identifier in enumerate(preference["item_ids"])}
        items.sort(key=lambda item: (not item["important"], positions.get(item["item_id"], len(positions))))
        for item in items:
            item["sorting_reasons"].append("OWNER_SAVED_ORDER" if item["item_id"] in positions else "NEW_ITEM_DEFAULT_ORDER")
    conflicts = []
    timed = [item for item in items if item["starts_at"] and item["ends_at"]]
    for index, left in enumerate(timed):
        for right in timed[index + 1:]:
            begin = max(_instant(left["starts_at"]), _instant(right["starts_at"]), start)
            finish = min(_instant(left["ends_at"]), _instant(right["ends_at"]), end)
            if begin < finish:
                conflicts.append({"item_ids": [left["item_id"], right["item_id"]], "starts_at": begin.astimezone(zone).isoformat(), "ends_at": finish.astimezone(zone).isoformat(), "scope": "PROVIDED_RANGES_ONLY"})
    unknown = any(item["starts_at"] and item["ends_at"] is None for item in items)
    result = {"source_type": "SIMULATED", **day, "day_start": start.isoformat(), "day_end": end.isoformat(), "business_clock": clock["at"], "read_at": now(),
              "data_as_of": max((item["observed_at"] for item in sources.values() if item["observed_at"]), default=None) if all(item["observed_at"] for item in sources.values()) else None,
              "items": items, "excluded_items": excluded, "snapshot_sha256": snapshot, "order_version": preference["version"] if preference else "0",
              "ordering_reason": "当前有效重要风险优先；其余采用本人日期及IANA时区内的次序，新增事项按分类、目标及期限排列",
              "coverage_state": "PARTIAL" if items else "UNAVAILABLE", "missing_sources": sorted(missing), "profile": profile,
              "conflict_state": "PARTIAL" if conflicts and unknown else "CONFLICTS_FOUND" if conflicts else "INSUFFICIENT_EVIDENCE" if unknown else "NO_CONFLICT_IN_PROVIDED_RANGES",
              "conflicts": conflicts, "source_statuses": list(sources.values()), "source_coverage": regions, "preparation_materials": preparation, "list_id": None, "list_version": None}
    return result, {"objects": {**{kind + ":" + identifier: row for (kind, identifier), row in rows.items()}, **measure_objects}, "documents": source_documents}
