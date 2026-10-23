import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, now, require
from boss_memory import confirmed_memory
from boss_owner_preferences import effective_owner_goals, effective_owner_notice, owner_profile
from boss_source_policy import source_validity
from boss_supply_quality import DEFINITION, ENTITY_CONFIG, bound_source_references

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "specs/simulation-query.schema.json").read_text())
VALIDATOR = Draft202012Validator({**SCHEMA, "$ref": "#/$defs/Query"}, format_checker=FormatChecker())
KINDS = {
    "SI01": ("owner_goals_draft", "owner_goals_active", "owner_notice_draft", "owner_notice_active"),
    "SI02": ("person_brief", "contact"),
    "SI03": ("meeting", "meeting_draft", "private_calendar", "calendar_share", "travel_plan"),
    "SI04": ("message_draft", "message_outbox", "message_reply", "outbox"),
    "SI05": ("meeting", "meeting_brief", "minutes", "minutes_assignment_link"),
    "SI06": ("task", "self_commitment", "feedback"),
    "SI07": ("query",), "SI08": ("query",),
    "SI09": tuple(kind for kind, config in ENTITY_CONFIG.items() if config["interface"] == "SI09"),
    "SI10": tuple(kind for kind, config in ENTITY_CONFIG.items() if config["interface"] == "SI10"),
    "SI11": ("application", "application_decision"),
    "SI12": ("research",), "SI13": ("document", "memory"),
    "SI14": ("event", "reminder", "dispatch", "delivery", "notification"),
}
MISSING = {
    "SI01": ["COMPLETE_ORGANIZATION_NOT_PROVIDED"],
    "SI02": ["EXTERNAL_RELATIONSHIP_SOURCES_NOT_PROVIDED"],
    "SI03": ["EXTERNAL_BOOKING_NOT_VERIFIED"],
    "SI04": ["REAL_EXTERNAL_DELIVERY_NOT_VERIFIED"],
    "SI05": ["MULTIPLE_MEETING_SOURCE_COVERAGE_NOT_PROVIDED"],
    "SI06": ["ONLY_APPROVED_SELECTION_AND_CURRENT_OWNER_ACTIONS"],
    "SI07": ["ONLY_TWO_APPROVED_TEN_DAY_PERIODS", "CAUSE_CONTRIBUTIONS_NOT_PROVIDED"],
    "SI08": ["CASH_NOT_PROVIDED", "RECEIVABLE_AGING_NOT_PROVIDED", "SETTLEMENT_DETAIL_NOT_PROVIDED"],
    "SI09": ["SIMULATED_EXTERNAL_SERVICE_ONLY", "FULL_BUSINESS_COVERAGE_NOT_VERIFIED"],
    "SI10": ["SIMULATED_EXTERNAL_SERVICE_ONLY", "FULL_BUSINESS_COVERAGE_NOT_VERIFIED"],
    "SI11": ["ONLY_APPROVED_SIMULATED_APPLICATIONS"],
    "SI12": ["PUBLIC_MARKET_WEATHER_POLICY_SOURCES_NOT_PROVIDED", "EXTERNAL_RETRIEVAL_NOT_CONFIGURED"],
    "SI13": ["ONLY_CURRENT_APPROVED_DOCUMENTS_AND_CONFIRMED_MEMORY"],
    "SI14": ["SYSTEM_NOTIFICATION_DELIVERY_NOT_VERIFIED", "FULL_RECURRING_PLANS_NOT_IMPLEMENTED"],
}
DETAIL_FILTERS = {"period_start", "period_end", "region_id", "product_ids", "legal_entity_id", "customer_id", "currency", "source_version"}
SUPPLY_QUALITY_FILTERS = {"material_id", "asset_owner_id", "cost_owner_id", "ownership_type", "product_ids", "legal_entity_id", "customer_id", "batch_id", "currency", "source_version", "period_start", "period_end"}
MAX_RECORDS = 1000
ID_FIELDS = {
    "profile": "owner_id", "contact": "contact_id", "metric_detail": "record_id",
    "owner_goals_draft": "id", "owner_goals_active": "id", "owner_notice_draft": "id", "owner_notice_active": "id",
    "meeting": "meeting_id", "meeting_draft": "meeting_id", "meeting_brief": "brief_id", "minutes": "minute_id",
    "minutes_assignment_link": "link_id", "private_calendar": "calendar_id", "calendar_share": "share_id",
    "person_brief": "brief_id", "travel_plan": "travel_id", "message_draft": "draft_id", "message_outbox": "message_id",
    "message_reply": "reply_id", "outbox": "message_id", "task": "task_id", "self_commitment": "commitment_id",
    "feedback": "feedback_id", "query": "query_id", "application": "application_id", "application_decision": "decision_id",
    "research": "research_id", "document": "source_id", "memory": "memory_id", "event": "event_id",
    "reminder": "event_id", "dispatch": "event_id", "delivery": "event_id",
}


def _object(db, namespace, kind, identifier):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (namespace, kind, identifier)).fetchone()
    return json.loads(row[0]) if row else None


def _context(db):
    rows = db.execute("SELECT namespace FROM spaces WHERE active=1").fetchall()
    require(len(rows) == 1, "当前有效执行空间无法唯一确定")
    namespace = rows[0][0]
    row = db.execute("SELECT json_extract(body,'$.owner_id'),json_extract(body,'$.dataset_id'),json_extract(body,'$.dataset_version'),"
                     "json_extract(body,'$.source_type'),json_extract(body,'$.boss_profile.timezone'),json_extract(body,'$.periods') "
                     "FROM objects WHERE namespace=? AND kind='initial' AND id='snapshot'", (namespace,)).fetchone()
    require(row is not None and row[3] == "SIMULATED", "当前空间没有获准模拟资料")
    require(row[0] == "boss-1" and row[1] == "selection" and row[2] == "1", "当前本人或数据版本不在获准资料范围", web.HTTPForbidden)
    clock = db.execute("SELECT json_extract(body,'$.at') FROM objects WHERE namespace=? AND kind='clock' AND id='current'", (namespace,)).fetchone()
    require(clock is not None, "当前空间缺少业务时钟")
    return {"namespace": namespace, "owner_id": row[0], "dataset_id": row[1], "dataset_version": row[2],
            "timezone": row[4], "periods": json.loads(row[5]), "clock": clock[0]}


def _filters(payload, context):
    require(not list(VALIDATOR.iter_errors(payload)), "模拟查询参数不符合Schema", web.HTTPBadRequest)
    interface = payload["interface_id"]
    supported = DETAIL_FILTERS if interface in ("SI07", "SI08") else SUPPLY_QUALITY_FILTERS if interface in ("SI09", "SI10") else {"source_version"} if interface == "SI13" else set()
    filters = payload["filters"]
    require(set(filters) <= supported, "当前接口不支持所提交的筛选字段", web.HTTPBadRequest)
    if "period_start" in filters or "period_end" in filters:
        require("period_start" in filters and "period_end" in filters, "期间需要完整起止日期", web.HTTPBadRequest)
        if interface in ("SI07", "SI08"):
            require([filters["period_start"], filters["period_end"]] in context["periods"].values(),
                    "期间必须完整匹配获准明细的一个期间", web.HTTPBadRequest)
        else:
            require(filters["period_start"] <= filters["period_end"] < "9999-12-31", "报告查询期间无效", web.HTTPBadRequest)
    if interface in ("SI07", "SI08"):
        require("currency" not in filters or filters["currency"] == "CNY", "当前资料只有CNY，不能换算其他币种", web.HTTPBadRequest)


def _wanted(kind, identifier, ids):
    return not ids or identifier in ids or kind + ":" + identifier in ids


def _detail_matches(body, filters, context):
    if any(body[field] != filters[field] for field in ("region_id", "legal_entity_id", "customer_id") if field in filters):
        return False
    if "product_ids" in filters and body["product_id"] not in filters["product_ids"]:
        return False
    return "period_start" not in filters or context["periods"][body["period"]] == [filters["period_start"], filters["period_end"]]


def _http_payload(query_string):
    require(isinstance(query_string, str), "模拟查询参数格式无效", web.HTTPBadRequest)
    require(len(query_string.encode("utf-8")) <= 4096, "模拟查询地址超过长度限制", web.HTTPRequestURITooLong)
    parameters = parse_qs(query_string, keep_blank_values=True)
    fields = set(SCHEMA["$defs"]["Query"]["properties"]["filters"]["properties"])
    require(set(parameters) <= fields | {"interface_id", "object_ids"} and "interface_id" in parameters,
            "模拟查询参数缺少接口标识或包含额外字段", web.HTTPBadRequest)
    require(all(len(values) == 1 for name, values in parameters.items() if name not in ("object_ids", "product_ids")),
            "模拟查询的单值参数重复", web.HTTPBadRequest)
    return {"interface_id": parameters["interface_id"][0], "object_ids": parameters.get("object_ids", []),
            "filters": {name: values if name == "product_ids" else values[0] for name, values in parameters.items() if name in fields}}


def _metadata(kind, identifier, body):
    object_id = body.get(ID_FIELDS[kind]) if kind in ID_FIELDS else None
    if object_id is None:
        object_id = identifier
    require(isinstance(object_id, str) and 0 < len(object_id) <= 128, "当前业务对象的编号格式无效")
    return {"record_id": kind + ":" + object_id, "object_id": object_id, "storage_id": identifier, "entity_type": kind,
            "version": body.get("version", body.get("memory_version")), "state": body.get("state", body.get("status", body.get("confirmation_state"))),
            "content_state": "STORED_RECORD", "data": body, "source_refs": [], "business_authorization_granted": False}


class SimulationAPI:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _role(role, expected):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == expected, "当前身份不能读取此模拟查询投影", web.HTTPForbidden)

    def query(self, role, payload):
        self._role(role, "BOSS")
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self.project_in_transaction(role, db, payload)

    def inspect(self, role, payload):
        self._role(role, "MAINTAINER")
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            _filters(payload, context)
            records = self._records(db, context, payload, technical=True)
            return self._result(context, payload, records, "TECHNICAL_METADATA")

    def query_http(self, role, query_string):
        self._role(role, "BOSS")
        return self.query(role, _http_payload(query_string))

    def inspect_http(self, role, query_string):
        self._role(role, "MAINTAINER")
        return self.inspect(role, _http_payload(query_string))

    def project_in_transaction(self, role, db, payload):
        self._role(role, "BOSS")
        context = _context(db)
        _filters(payload, context)
        records = self._records(db, context, payload, technical=False)
        for record in records:
            self._protect(db, context, record)
        if "source_version" in payload["filters"]:
            version = payload["filters"]["source_version"]
            records = [record for record in records if any(ref["version"] == version and ref["status"] == "VALID"
                       and (record["data"] is None or record["data"].get("simulation_definition") != DEFINITION or ref["source_id"] == record["data"]["source_id"])
                       for ref in record["source_refs"]) and not (record["data"] is None and payload["interface_id"] in ("SI09", "SI10"))]
        return self._result(context, payload, records, "BOSS_ONLY")

    def _records(self, db, context, payload, technical):
        interface, namespace, ids = payload["interface_id"], context["namespace"], payload["object_ids"]
        records = []
        for kind in KINDS[interface]:
            if technical and interface == "SI13" and "source_version" in payload["filters"] and kind != "document":
                continue
            id_field = ID_FIELDS.get(kind)
            canonical_id = "json_extract(body,'$." + id_field + "')" if id_field else "id"
            metadata_fields = ",'" + id_field + "'," + canonical_id if id_field else ""
            columns = "id,json_object('version',json_extract(body,'$.version'),'state',coalesce(json_extract(body,'$.state'),json_extract(body,'$.status'),json_extract(body,'$.confirmation_state'))" + metadata_fields + ")" if technical else "id,body"
            statement = "SELECT " + columns + " FROM objects WHERE namespace=? AND kind=? AND (json_extract(body,'$.owner_id') IS NULL OR json_extract(body,'$.owner_id')=?) AND (json_extract(body,'$.access_scope') IS NULL OR json_extract(body,'$.access_scope')=?)"
            parameters = [namespace, kind, context["owner_id"], context["owner_id"]]
            if ids:
                marks = ",".join("?" for _ in ids)
                candidates = ["id", "kind||':'||id"]
                if id_field:
                    candidates.extend((canonical_id, "kind||':'||" + canonical_id))
                statement += " AND (" + " OR ".join(candidate + " IN (" + marks + ")" for candidate in candidates) + ")"
                for _ in candidates:
                    parameters.extend(ids)
            if kind == "document":
                statement += " AND json_extract(body,'$.source_type')='SIMULATED'"
                if "source_version" in payload["filters"]:
                    statement += " AND json_extract(body,'$.version')=?"
                    parameters.append(payload["filters"]["source_version"])
            if interface in ("SI09", "SI10"):
                filters = payload["filters"]
                for field in SUPPLY_QUALITY_FILTERS - {"product_ids", "source_version", "batch_id", "period_start", "period_end"}:
                    if field in filters:
                        statement += " AND json_extract(body,'$.data." + field + "')=?"
                        parameters.append(filters[field])
                if "period_start" in filters:
                    # 日期范围采用本人业务时区，仅返回完整包含的报告，不能分摊未知期间金额。
                    zone = ZoneInfo(context["timezone"])
                    start = datetime.combine(date.fromisoformat(filters["period_start"]), time.min, zone)
                    end = datetime.combine(date.fromisoformat(filters["period_end"]) + timedelta(days=1), time.min, zone)
                    statement += " AND julianday(json_extract(body,'$.data.period_start'))>=julianday(?) AND julianday(json_extract(body,'$.data.period_end'))<=julianday(?)"
                    parameters.extend((start.isoformat(), end.isoformat()))
                if "batch_id" in filters:
                    statement += " AND (json_extract(body,'$.data.batch_id')=? OR json_extract(body,'$.data.input_batch_id')=? OR json_extract(body,'$.data.output_batch_id')=? OR EXISTS(SELECT 1 FROM json_each(objects.body,'$.data.batch_ids') WHERE value=?))"
                    parameters.extend([filters["batch_id"]] * 4)
                if "product_ids" in filters:
                    statement += " AND json_extract(body,'$.data.product_id') IN (" + ",".join("?" for _ in filters["product_ids"]) + ")"
                    parameters.extend(filters["product_ids"])
                if "source_version" in filters:
                    statement += " AND json_extract(body,'$.source_version')=?"
                    parameters.append(filters["source_version"])
            statement += " ORDER BY id LIMIT ?"
            parameters.append(MAX_RECORDS + 1)
            candidates = db.execute(statement, parameters).fetchall()
            if len(candidates) > MAX_RECORDS:
                raise web.HTTPRequestEntityTooLarge(max_size=MAX_RECORDS, actual_size=len(candidates), text="模拟查询候选超过上限，请指定object_ids缩小范围")
            for identifier, body in candidates:
                if kind == "query" and payload["filters"]:
                    refs = db.execute("SELECT json_extract(body,'$.detail_refs') FROM objects WHERE namespace=? AND kind='query' AND id=?", (namespace, identifier)).fetchone()
                    identifiers = json.loads(refs[0])
                    dimension_fields = ("record_id", "period", "region_id", "product_id", "legal_entity_id", "customer_id")
                    projection = "json_object(" + ",".join("'" + field + "',json_extract(value,'$." + field + "')" for field in dimension_fields) + ")"
                    details = [json.loads(row[0]) for row in db.execute("SELECT " + projection + " FROM objects,json_each(objects.body,'$.details') WHERE objects.namespace=? AND objects.kind='initial' AND objects.id='snapshot'", (namespace,)).fetchall()]
                    selected = [detail for detail in details if detail["record_id"] in identifiers]
                    if len(selected) != len(identifiers) or not all(_detail_matches(detail, payload["filters"], context) for detail in selected):
                        continue
                    if technical and "source_version" in payload["filters"]:
                        saved_source = db.execute("SELECT json_extract(body,'$.source_version') FROM objects WHERE namespace=? AND kind='query_source_binding' AND id=?", (namespace, identifier)).fetchone()
                        if saved_source is None or saved_source[0] != payload["filters"]["source_version"]:
                            continue
                value = json.loads(body)
                if technical and kind == "document":
                    source = self._source(db, context, identifier)
                    value["state"] = source_validity(source, context["clock"])
                records.append(_metadata(kind, identifier, value))
        records.extend(self._initial_records(db, context, payload, technical))
        if len(records) > MAX_RECORDS:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_RECORDS, actual_size=len(records), text="模拟查询记录超过上限，请指定object_ids缩小范围")
        records.sort(key=lambda record: record["record_id"])
        if technical:
            for record in records:
                record.update(content_state="METADATA_ONLY", data=None)
        return records

    def _initial_records(self, db, context, payload, technical):
        namespace, interface, ids = context["namespace"], payload["interface_id"], payload["object_ids"]
        definitions = {
            "SI01": [("profile", "$.boss_profile", "owner_id", False)],
            "SI02": [("contact", "$.contacts", "contact_id", True)],
            "SI03": [("meeting", "$.meeting", "meeting_id", False), ("private_calendar", "$.private_calendar", "calendar_id", False)],
            "SI05": [("meeting", "$.meeting", "meeting_id", False)],
            "SI06": [("task", "$.historical_task", "task_id", False)],
            "SI07": [("metric_detail", "$.details", "record_id", True)],
            "SI08": [("metric_detail", "$.details", "record_id", True)],
            "SI14": [("event", "$.event", "event_id", False)],
        }
        records = []
        for kind, path, id_field, many in definitions.get(interface, []):
            if many:
                statement = "SELECT value FROM objects,json_each(objects.body,?) WHERE objects.namespace=? AND objects.kind='initial' AND objects.id='snapshot'"
            else:
                statement = "SELECT json_extract(body,?) FROM objects WHERE namespace=? AND kind='initial' AND id='snapshot'"
            if technical and kind == "metric_detail":
                fields = ("record_id", "version", "period", "region_id", "product_id", "legal_entity_id", "customer_id")
                expression = "json_object(" + ",".join("'" + field + "',json_extract(value,'$." + field + "')" for field in fields) + ")"
                statement = "SELECT " + expression + " FROM objects,json_each(objects.body,?) WHERE objects.namespace=? AND objects.kind='initial' AND objects.id='snapshot'"
                parameters = (path, namespace)
            elif technical:
                expression = "value" if many else "json_extract(body,?)"
                statement = statement.replace("SELECT value" if many else "SELECT json_extract(body,?)",
                    "SELECT json_object('" + id_field + "',json_extract(" + expression + ",'$." + id_field + "'),'version',json_extract(" + expression + ",'$.version'))")
                parameters = (path, namespace) if many else (path, path, namespace)
            else:
                parameters = (path, namespace)
            for row in db.execute(statement, parameters).fetchall():
                body = json.loads(row[0])
                identifier = body[id_field]
                if not _wanted(kind, identifier, ids):
                    continue
                exists = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind=? AND id=?", (namespace, kind, identifier)).fetchone()
                if exists:
                    continue
                if kind == "metric_detail":
                    filters = payload["filters"]
                    period = context["periods"][body["period"]]
                    if not _detail_matches(body, filters, context):
                        continue
                    body = {**body, "period_start": period[0], "period_end": period[1], "currency": "CNY"}
                    if technical:
                        source = self._source(db, context, "finance-note")
                        if "source_version" in filters and (source is None or source["version"] != filters["source_version"]):
                            continue
                records.append(_metadata(kind, identifier, body))
        return records

    @staticmethod
    def _source(db, context, source_id):
        row = db.execute("SELECT json_object('source_id',json_extract(body,'$.source_id'),'version',json_extract(body,'$.version'),"
                         "'source_type',json_extract(body,'$.source_type'),'access_scope',json_extract(body,'$.access_scope'),"
                         "'withdrawn',CASE WHEN json_type(body,'$.withdrawn')='true' THEN 1 ELSE 0 END,"
                         "'validity_state',CASE WHEN json_type(body,'$.validity_state') IS NULL THEN 'VALID' ELSE json_extract(body,'$.validity_state') END,"
                         "'published_at',json_extract(body,'$.published_at'),'valid_from',json_extract(body,'$.valid_from'),"
                         "'valid_until',json_extract(body,'$.valid_until')) FROM objects WHERE namespace=? AND kind='document' AND id=?",
                         (context["namespace"], source_id)).fetchone()
        if row is None:
            return None
        source = json.loads(row[0])
        source["withdrawn"] = source["withdrawn"] == 1
        return source

    def _references(self, db, context, record):
        body, kind = record["data"], record["entity_type"]
        refs = []
        if body.get("simulation_definition") == DEFINITION and kind in ENTITY_CONFIG:
            references = bound_source_references(db, context, kind, body)
            if references is None:
                record["content_state"] = "NEEDS_REVIEW"
                return []
            return references
        if kind == "document":
            refs.append({"source_id": record["object_id"], "version": body["version"]})
        if kind == "metric_detail":
            source = self._source(db, context, "finance-note")
            refs.append({"source_id": "finance-note", "version": source["version"] if source else None})
        for field in ("attachment_refs", "completion_evidence"):
            refs.extend(body.get(field, []))
        if kind == "task" and body.get("source_refs"):
            binding = _object(db, context["namespace"], "assignment_source_binding", record["object_id"])
            if binding is None:
                record["content_state"] = "NEEDS_REVIEW"
            else:
                require(binding["task_id"] == record["object_id"] and binding["owner_id"] == context["owner_id"] and binding["dataset_id"] == context["dataset_id"]
                        and binding["dataset_version"] == context["dataset_version"], "交办来源绑定不属于当前空间", web.HTTPForbidden)
                if body.get("origin_source_id"):
                    origin = binding.get("origin_source")
                    if origin is None or origin["source_id"] != body["origin_source_id"]:
                        record["content_state"] = "NEEDS_REVIEW"
                    else:
                        refs.append({"source_id": origin["source_id"], "version": origin["version"], "source_sha256": origin["sha256"]})
            refs.extend({"source_id": identifier, "version": binding["source_versions"].get(identifier) if binding else None,
                         "source_sha256": binding["source_fingerprints"].get(identifier) if binding else None} for identifier in body["source_refs"])
        else:
            refs.extend(body.get("source_refs", []))
        if body.get("source_id") and kind != "document":
            refs.append({"source_id": body["source_id"], "version": body.get("source_version")})
        if kind == "feedback":
            refs.extend({"source_id": identifier, "version": body.get("evidence_versions", {}).get(identifier),
                         "source_sha256": body.get("evidence_fingerprints", {}).get(identifier)} for identifier in body.get("evidence_refs", []))
        if kind == "query":
            binding = _object(db, context["namespace"], "query_source_binding", record["object_id"])
            if binding is None:
                record["content_state"] = "NEEDS_REVIEW"
            else:
                require(binding["query_id"] == record["object_id"] and binding["owner_id"] == context["owner_id"]
                        and binding["dataset_id"] == context["dataset_id"] and binding["dataset_version"] == context["dataset_version"],
                        "查询来源绑定不属于当前空间", web.HTTPForbidden)
                refs.append({"source_id": binding["source_id"], "version": binding["source_version"], "source_sha256": binding["source_sha256"]})
                initial = self.store.get(db, context["namespace"], "initial", "snapshot")
                details = [row for row in initial["details"] if row["record_id"] in body["detail_refs"]]
                if len(details) != len(body["detail_refs"]) or any(binding["detail_fingerprints"].get(row["record_id"]) != checksum(row) for row in details):
                    record["content_state"] = "NEEDS_REVIEW"
        if kind in ("meeting_brief", "person_brief"):
            refs.extend(body["compiled"]["sources"])
        if kind == "research":
            refs.extend(body["matched_sources"])
        if kind == "meeting_draft":
            refs.extend(body["details"]["source_refs"])
        if kind == "travel_plan":
            for details in (body.get("current"), body.get("pending", {}).get("details") if body.get("pending") else None):
                if details:
                    refs.extend(details["transport_refs"])
        return refs

    def _protect(self, db, context, record):
        body, kind = record["data"], record["entity_type"]
        namespace = context["namespace"]
        if kind == "profile":
            initial = self.store.get(db, namespace, "initial", "snapshot")
            record["data"] = {"owner_id": context["owner_id"], **owner_profile(db, initial, namespace)}
            record["version"] = record["data"]["active_version"]
            return
        if kind == "private_calendar" and body.get("status") == "DELETED":
            record.update(content_state="INACTIVE", data=None)
            return
        if kind == "memory" and confirmed_memory(db, namespace, body, context["owner_id"]) is None:
            record.update(content_state="INACTIVE", data=None)
            return
        if kind in ("owner_goals_active", "owner_notice_active"):
            reader = effective_owner_goals if kind == "owner_goals_active" else effective_owner_notice
            if reader(db, context, namespace) is None:
                record.update(content_state="INACTIVE", data=None)
                return
        references = self._references(db, context, record)
        for reference in list(references):
            document = _object(db, namespace, "document", reference["source_id"])
            if document is not None and document.get("simulation_definition") == DEFINITION:
                external = _object(db, namespace, document["external_entity_type"], document["external_record_id"])
                if external is None:
                    record["content_state"] = "NEEDS_REVIEW"
                    continue
                dependencies = bound_source_references(db, context, document["external_entity_type"], external)
                if dependencies is None:
                    record["content_state"] = "NEEDS_REVIEW"
                else:
                    references.extend(dependencies)
        unique = {checksum(reference): reference for reference in references}
        for ref in unique.values():
            require(isinstance(ref, dict) and isinstance(ref.get("source_id"), str), "来源引用字段不完整")
            source = self._source(db, context, ref["source_id"])
            status = "MISSING" if source is None else "FORBIDDEN" if source["source_id"] != ref["source_id"] or source["source_type"] != "SIMULATED" or source["access_scope"] != context["owner_id"] else source_validity(source, context["clock"])
            current_version = source["version"] if source and status != "FORBIDDEN" else None
            if status == "VALID":
                current = _object(db, namespace, "document", ref["source_id"])
                if ref.get("version") != current_version or (ref.get("source_sha256") is not None and ref["source_sha256"] != checksum(current)):
                    status = "CHANGED"
                if "excerpt" in ref and ref["excerpt"] != current["content"][:len(ref["excerpt"] or "")]:
                    status = "CHANGED"
                if "quote" in ref and ref["quote"] != current["content"][ref["quote_start"]:ref["quote_end"]]:
                    status = "CHANGED"
                if "published_at" in ref and ref["published_at"] != current.get("published_at"):
                    status = "CHANGED"
            record["source_refs"].append({"source_id": ref["source_id"], "version": ref.get("version"), "current_version": current_version, "status": status})
            if status != "VALID":
                record["content_state"] = "NEEDS_REVIEW"
        if record["content_state"] != "NEEDS_REVIEW" and kind in ("meeting_brief", "person_brief", "meeting_draft", "travel_plan"):
            if namespace != "ui-check" or not self._cached_context_current(db, context, record):
                record["content_state"] = "NEEDS_REVIEW"
        if record["content_state"] == "NEEDS_REVIEW":
            record["data"] = None

    def _cached_context_current(self, db, context, record):
        from boss_command_api import BossCommandAPI
        from boss_meeting_brief import compile_brief
        from boss_meetings import MeetingAPI, meeting_materials
        from boss_people import _compile, _payload_refs
        from boss_travel import _details, _impact
        data = meeting_materials(db, self.store.get(db, context["namespace"], "initial", "snapshot"))
        body, kind = record["data"], record["entity_type"]
        if kind == "meeting_brief":
            return checksum(body["compiled"]) == checksum(compile_brief(db, data))
        if kind == "meeting_draft":
            _, digest = MeetingAPI(self.store)._preview(db, data, body["details"])
            return body["meeting_version"] == data["meeting"]["version"] and body["review_sha256"] == digest
        commands = BossCommandAPI(self.store)
        if kind == "person_brief":
            saved = body["compiled"]
            contacts = [contact for contact in data["contacts"] if contact["contact_id"] == saved["contact"]["contact_id"]]
            today = datetime.fromisoformat(context["clock"]).date().isoformat()
            if len(contacts) != 1 or not contacts[0]["valid_from"] <= today <= contacts[0]["valid_until"]:
                return False
            return checksum(_compile(commands, db, data, contacts[0]["contact_id"], _payload_refs(saved), saved["purpose"], saved["meeting"]["meeting_id"])) == body["compiled_sha256"]
        if body.get("pending") is None:
            return True
        pending = body["pending"]
        if datetime.fromisoformat(pending["details"]["starts_at"]) <= datetime.fromisoformat(context["clock"]):
            return False
        contacts = [contact for contact in data["contacts"] if contact["contact_id"] == pending["details"]["host_contact_id"]]
        today = datetime.fromisoformat(context["clock"]).date().isoformat()
        if len(contacts) != 1 or not contacts[0]["valid_from"] <= today <= contacts[0]["valid_until"]:
            return False
        details = _details(commands, db, data, pending["details"])
        return checksum({"details": details, "impact": _impact(commands, db, data, details, body["travel_id"]), "dataset_version": data["dataset_version"]}) == pending["review_sha256"]

    @staticmethod
    def _result(context, payload, records, access):
        missing = list(MISSING[payload["interface_id"]])
        found = {identifier for record in records for identifier in (record["object_id"], record["record_id"], record["storage_id"], record["entity_type"] + ":" + record["storage_id"])}
        missing.extend("OBJECT_NOT_IN_APPROVED_RESULT:" + identifier for identifier in payload["object_ids"] if identifier not in found)
        missing.extend("CURRENT_CONTENT_WITHHELD:" + record["record_id"] for record in records if record["content_state"] in ("NEEDS_REVIEW", "INACTIVE"))
        sources = {(ref["source_id"], ref["current_version"]) for record in records for ref in record["source_refs"] if ref["status"] == "VALID"}
        business_at = context["clock"]
        if payload["interface_id"] in ("SI07", "SI08"):
            periods = [record["data"]["period_end"] for record in records if record["data"] is not None and record["entity_type"] == "metric_detail"]
            business_at = datetime.combine(datetime.fromisoformat(max(periods)).date(), time(23, 59, 59), ZoneInfo(context["timezone"])).isoformat() if periods else None
            if business_at is None:
                saved_times = [source["business_as_of"] for record in records if record["data"] is not None and record["entity_type"] == "query" for source in record["data"]["sources"]]
                business_at = max(saved_times, key=datetime.fromisoformat) if saved_times else None
        return {"source_type": "SIMULATED", "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"],
                "execution_namespace": context["namespace"], "interface_id": payload["interface_id"],
                "availability": "PARTIAL" if records else "UNAVAILABLE", "access": access, "records": records,
                "sources": [{"source_id": identifier, "version": version} for identifier, version in sorted(sources)],
                "missing_fields": sorted(set(missing)), "business_as_of": business_at, "read_at": now(),
                "business_actions_performed": False, "external_retrieval_performed": False}
