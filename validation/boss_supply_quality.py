import json
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from urllib.parse import parse_qs
import uuid
from zoneinfo import available_timezones

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from business import checksum, encode, now, require, validate
from boss_source_access import require_current_simulated_source
from boss_source_policy import source_validity

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "specs/simulated-supply-quality.schema.json").read_text())
RESULT_PATH = ROOT / "specs/supply-quality-results.schema.json"
RESULT_SCHEMA = {**json.loads(RESULT_PATH.read_text()), "$id": RESULT_PATH.as_uri()}
RESULT_RESOURCES = [RESULT_PATH, ROOT / "specs/simulation-query.schema.json", ROOT / "specs/simulated-supply-quality.schema.json"]
RESULT_REGISTRY = Registry().with_resources((path.as_uri(), Resource.from_contents({**json.loads(path.read_text()), "$id": path.as_uri()})) for path in RESULT_RESOURCES)
ENTITY_CONFIG = SCHEMA["x-entity-config"]
DEFINITION = "si09-si10-business-v1"
IMPORT_ACTION = "boss.simulation.supply_quality.import"
WITHDRAW_ACTION = "boss.simulation.supply_quality.withdraw"
COORDINATE_ACTION = "boss.supply_quality.coordinate"
ACTION_INPUTS = {IMPORT_ACTION: ("MAINTAINER", "ImportInput"), WITHDRAW_ACTION: ("MAINTAINER", "WithdrawInput"), COORDINATE_ACTION: ("BOSS", "CoordinateInput")}
ACTION_RESULTS = {IMPORT_ACTION: "ImportResult", WITHDRAW_ACTION: "WithdrawResult", COORDINATE_ACTION: "CoordinateResult"}
TERMINAL_STATES = {"material_quote": {"SUPERSEDED"}, "material_contract": {"FULFILLED_REPORTED", "CANCELED_REPORTED"},
                   "inventory_lot": {"REJECTED"}, "material_consumption": {"CANCELED"}, "production_batch": {"COMPLETED", "CANCELED"},
                   "production_event": {"CLOSED_REPORTED"}, "feed_formula": {"SUPERSEDED"}, "business_order": {"DELIVERED_REPORTED", "CANCELED"}}
IDENTITY_FIELDS = {
    "contact": ("contact_id",), "material_quote": ("material_id", "origin", "price_unit", "currency"),
    "material_contract": ("legal_entity_id", "supplier_id", "material_id", "quantity_unit", "currency"),
    "inventory_lot": ("batch_id", "material_id", "product_id", "legal_entity_id", "asset_owner_id", "ownership_type", "customer_id", "quantity_unit"),
    "material_consumption": ("material_id", "legal_entity_id", "inventory_id", "quantity_unit", "currency"),
    "production_batch": ("batch_type", "material_id", "product_id", "legal_entity_id", "customer_id", "ownership_type", "asset_owner_id", "quantity_unit"),
    "quality_trace": ("input_batch_id", "output_batch_id", "processing_id", "inventory_id", "customer_id", "quantity_unit"),
    "professional_record": ("author_contact_id", "batch_id", "event_id"), "customer_feedback": ("customer_id", "author_contact_id", "batch_id"),
    "production_event": ("legal_entity_id",), "agriculture_observation": ("batch_id", "unit_id", "metric_id", "unit", "author_contact_id"),
    "feed_formula": ("product_id", "species", "purpose", "stage"),
    "production_capacity": ("legal_entity_id", "factory_id", "process_stage_id", "product_id", "period_start", "period_end", "timezone", "quantity_unit"),
    "business_order": ("legal_entity_id", "customer_id", "product_id", "region_id", "quantity_unit", "trade_type", "currency"),
}


def source_id(kind, identifier):
    return "sim-business:" + kind + ":" + identifier


def validate_result(name, result):
    Draft202012Validator({**RESULT_SCHEMA, "$ref": "#/$defs/" + name}, registry=RESULT_REGISTRY, format_checker=FormatChecker()).validate(result)
    return result


def binding_id(kind, identifier):
    return kind + ":" + identifier


def _object(db, namespace, kind, identifier):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (namespace, kind, identifier)).fetchone()
    return json.loads(row[0]) if row else None


def external_records(db, namespace):
    return {(kind, identifier): json.loads(body) for kind, identifier, body in db.execute(
        "SELECT kind,id,body FROM objects WHERE namespace=? AND json_extract(body,'$.simulation_definition')=? ORDER BY kind,id", (namespace, DEFINITION)).fetchall()
        if kind in ENTITY_CONFIG}


def _direct_dependencies(record, initial_contacts):
    kind, data = record["entity_type"], record["data"]
    result = set()
    if record["author_contact_id"] not in initial_contacts:
        result.add(("contact", record["author_contact_id"]))
    mapping = {
        "inventory_lot": {"batch_id": "production_batch", "contract_id": "material_contract"},
        "material_consumption": {"inventory_id": "inventory_lot"},
        "quality_trace": {"input_batch_id": "production_batch", "output_batch_id": "production_batch", "inventory_id": "inventory_lot", "professional_record_id": "professional_record", "complaint_id": "customer_feedback"},
        "professional_record": {"batch_id": "production_batch"},
        "customer_feedback": {"batch_id": "production_batch"},
        "production_event": {"professional_record_id": "professional_record", "complaint_id": "customer_feedback"},
        "agriculture_observation": {"batch_id": "production_batch"}, "feed_formula": {"professional_record_id": "professional_record"},
    }
    for field, target in mapping.get(kind, {}).items():
        if data[field] is not None:
            result.add((target, data[field]))
    if kind == "professional_record":
        result.update(("agriculture_observation", identifier) for identifier in data["observation_ids"])
    if kind == "production_event":
        result.update(("production_batch", identifier) for identifier in data["batch_ids"])
    return result


def _dependency_closure(db, root, dependencies):
    edges = [(encode(child), encode(parent)) for child, parents in dependencies.items() for parent in parents]
    nodes = {encode(key): key for key in set(dependencies) | {parent for parents in dependencies.values() for parent in parents}}
    if not edges:
        return {root}
    values = ",".join("(?,?)" for _ in edges)
    statement = "WITH RECURSIVE edges(child,parent) AS (VALUES " + values + "), reached(node) AS (SELECT ? UNION SELECT edges.parent FROM edges JOIN reached ON edges.child=reached.node) SELECT node FROM reached"
    parameters = [value for edge in edges for value in edge] + [encode(root)]
    return {nodes[row[0]] for row in db.execute(statement, parameters).fetchall()}


def bound_source_references(db, context, kind, record):
    binding = _object(db, context["namespace"], "external_record_binding", binding_id(kind, record["record_id"]))
    if binding is None:
        return None
    require(binding["entity_type"] == kind and binding["record_id"] == record["record_id"] and binding["version"] == record["version"]
            and binding["owner_id"] == context["owner_id"] and binding["execution_namespace"] == context["namespace"]
            and binding["dataset_id"] == context["dataset_id"] and binding["dataset_version"] == context["dataset_version"],
            "外部记录来源绑定不属于当前范围", web.HTTPForbidden)
    return binding["sources"]


def require_external_source_dependencies(store, db, namespace, initial, document):
    kind, identifier = document["external_entity_type"], document["external_record_id"]
    record = store.get(db, namespace, kind, identifier)
    context = {"namespace": namespace, "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"]}
    references = bound_source_references(db, context, kind, record)
    require(references is not None, "外部记录缺少来源绑定，需要重新导入")
    clock = store.get(db, namespace, "clock", "current")["at"]
    for reference in references:
        current = require_current_simulated_source(store.get(db, namespace, "document", reference["source_id"]), initial["owner_id"], clock)
        require(current["version"] == reference["version"] and checksum(current) == reference["source_sha256"],
                "外部记录引用已经变化，需要重新导入当前资料")


def external_adoption(db, namespace, initial, clock, document):
    if document is None or document.get("simulation_definition") != DEFINITION:
        return {"state": "NOT_APPLICABLE", "dependencies": []}
    kind, identifier = document["external_entity_type"], document["external_record_id"]
    record = _object(db, namespace, kind, identifier)
    if record is None:
        return {"state": "NEEDS_REIMPORT", "dependencies": []}
    context = {"namespace": namespace, "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"]}
    references = bound_source_references(db, context, kind, record)
    rows = []
    for reference in references or []:
        current = _object(db, namespace, "document", reference["source_id"])
        status = "MISSING" if current is None else "FORBIDDEN" if current.get("source_id") != reference["source_id"] or current.get("source_type") != "SIMULATED" or current.get("access_scope") != initial["owner_id"] else source_validity(current, clock)
        if status == "VALID" and (current["version"] != reference["version"] or checksum(current) != reference["source_sha256"]):
            status = "CHANGED"
        rows.append({"source_id": reference["source_id"], "version": reference["version"], "status": status})
    return {"state": "CURRENT" if references and all(row["status"] == "VALID" for row in rows) else "NEEDS_REIMPORT", "dependencies": rows}


class SupplyQualityAPI:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _role(role, expected):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == expected, "当前身份不能执行此业务操作", web.HTTPForbidden)

    def execute(self, role, action, payload):
        require(action in ACTION_INPUTS, "未知模拟业务动作", web.HTTPNotFound)
        expected, name = ACTION_INPUTS[action]
        self._role(role, expected)
        validator = Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}, format_checker=FormatChecker())
        require(not list(validator.iter_errors(payload)), "模拟业务输入不符合Schema", web.HTTPBadRequest)
        size = len(encode(payload).encode("utf-8"))
        if size > 1048576:
            raise web.HTTPRequestEntityTooLarge(max_size=1048576, actual_size=size)
        from boss_simulation_api import _context
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            namespace = context["namespace"]
            key = payload["client_request_id"]
            digest = checksum({"action": action, "payload": {field: value for field, value in payload.items() if field != "client_request_id"}})
            previous = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (namespace, action, key)).fetchone()
            if previous is not None:
                require(previous[0] == digest, "同一请求编号的内容已经变化")
                result = json.loads(previous[1])
            else:
                require(db.execute("SELECT 1 FROM idempotency WHERE namespace<>? AND operation=? AND key=?", (namespace, action, key)).fetchone() is None,
                        "原请求编号属于其他执行空间，需要基于当前空间重新提交")
                if action == IMPORT_ACTION:
                    result = self._import(db, context, payload)
                elif action == WITHDRAW_ACTION:
                    result = self._withdraw(db, context, payload)
                else:
                    result = self._coordinate(db, context, payload)
                validate_result(ACTION_RESULTS[action], result)
                db.execute("INSERT INTO idempotency VALUES(?,?,?,?,?)", (namespace, action, key, digest, encode(result)))
                safe_result = {field: result[field] for field in ("state", "record_count", "record_id", "version", "source_id", "task_id", "source_type", "external_service_invoked", "error_code") if field in result}
                db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)", (namespace, action,
                    encode({"role": role, "client_request_id": key, "payload_sha256": digest, "source_type": "SIMULATED"}), encode(safe_result), now()))
        if result.get("state") == "FAILED":
            raise web.HTTPBadGateway(text="明确模拟的外部资料失败；原结果已经保存")
        if result.get("state") == "TIMED_OUT":
            raise web.HTTPGatewayTimeout(text="明确模拟的外部资料超时；原结果已经保存")
        return result

    def _import(self, db, context, payload):
        namespace, received = context["namespace"], now()
        initial = self.store.get(db, namespace, "initial", "snapshot")
        initial_contacts = {contact["contact_id"]: contact for contact in initial["contacts"]}
        world = external_records(db, namespace)
        incoming, documents, previous_rows = {}, {}, {}
        identifiers = [(entry["entity_type"], entry["data"][ENTITY_CONFIG[entry["entity_type"]]["id"]]) for entry in payload["records"]]
        require(len(identifiers) == len(set(identifiers)), "同一次导入的业务对象编号重复", web.HTTPBadRequest)
        for entry in payload["records"]:
            kind, data, provenance = entry["entity_type"], entry["data"], entry["source"]
            identifier = data[ENTITY_CONFIG[kind]["id"]]
            key = kind, identifier
            require(key not in incoming, "同一次导入的业务对象编号重复", web.HTTPBadRequest)
            require(not (kind == "contact" and identifier in initial_contacts), "不能覆盖初始获准联系人", web.HTTPForbidden)
            previous = _object(db, namespace, kind, identifier)
            if previous is not None:
                require(previous.get("simulation_definition") == DEFINITION and previous["owner_id"] == context["owner_id"]
                        and previous["execution_namespace"] == namespace, "不能覆盖其他来源的业务对象", web.HTTPForbidden)
                require(previous["record_state"] == "ACTIVE", "已撤销外部记录不能在原编号上重新启用")
                previous_document = self.store.get(db, namespace, "document", previous["source_id"])
                require(previous_document.get("withdrawn") is not True, "已撤销来源不能通过导入重新启用")
                require(previous_document["source_id"] == previous["source_id"] and previous_document["access_scope"] == context["owner_id"]
                        and previous_document.get("simulation_definition") == DEFINITION, "原始来源不属于当前模拟资料范围", web.HTTPForbidden)
                require(previous_document["version"] == previous["source_version"], "来源已经通过其他入口更新，需要核查当前记录版本")
            require(entry["expected_version"] == (previous["version"] if previous else "0"), "外部记录版本已经变化")
            version = str(int(entry["expected_version"]) + 1)
            record = {"record_id": identifier, "entity_type": kind, "version": version, "record_state": "ACTIVE",
                "state": data[ENTITY_CONFIG[kind]["state"]] if ENTITY_CONFIG[kind]["state"] else "ACTIVE",
                "owner_id": context["owner_id"], "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"],
                "execution_namespace": namespace, "source_type": "SIMULATED", "simulation_definition": DEFINITION,
                **provenance, "received_at": received, "source_id": source_id(kind, identifier), "source_version": version, "data": data}
            self._validate_record(record, previous, initial, context)
            require(previous is not None or _object(db, namespace, "document", record["source_id"]) is None,
                    "外部来源编号已经被其他资料使用")
            document = {"source_id": record["source_id"], "version": version, "source_type": "SIMULATED",
                "access_scope": context["owner_id"], "author_contact_id": provenance["author_contact_id"],
                "published_at": received, "valid_from": provenance["valid_from"], "valid_until": provenance["valid_until"],
                "validity_state": "VALID", "withdrawn": False, "observed_at": provenance["observed_at"], "received_at": received,
                "original_locator": "sqlite:simulated-business/" + kind + "/" + identifier,
                "simulation_definition": DEFINITION, "external_entity_type": kind, "external_record_id": identifier,
                "created_by_role": "MAINTAINER", "content": encode({"source_type": "SIMULATED", "simulation_definition": DEFINITION, "entity_type": kind, "data": data})}
            incoming[key], documents[key], previous_rows[key] = record, document, previous
        world.update(incoming)
        dependencies = {key: _direct_dependencies(record, initial_contacts) for key, record in world.items()}
        for key, record in incoming.items():
            self._validate_relationships(record, world, initial_contacts, initial)
            for dependency in dependencies[key]:
                require(dependency in world and world[dependency]["record_state"] == "ACTIVE", "引用的当前外部记录不存在", web.HTTPNotFound)
            for dependency in _dependency_closure(db, key, dependencies) - incoming.keys():
                require(dependency in world and world[dependency]["record_state"] == "ACTIVE", "引用的关联外部记录不存在或已经撤销", web.HTTPNotFound)
                parent = world[dependency]
                references = bound_source_references(db, context, dependency[0], parent)
                require(references is not None, "引用资料缺少采用记录，需要重新导入")
                for reference in references:
                    current = next((document for document in documents.values() if document["source_id"] == reference["source_id"]), None)
                    if current is None:
                        current = self.store.get(db, namespace, "document", reference["source_id"])
                    require_current_simulated_source(current, initial["owner_id"], context["clock"])
                    require(current["version"] == reference["version"] and checksum(current) == reference["source_sha256"],
                            "引用资料采用的来源已经变化，需要明确重新导入该资料")
        self._validate_processing(world)
        for key, record in incoming.items():
            previous = previous_rows[key]
            kind, identifier = key
            if previous is not None:
                self.store.put(db, namespace, kind + "_revision", identifier + ":v" + previous["version"], previous)
                prior_document = self.store.get(db, namespace, "document", previous["source_id"])
                self.store.put(db, namespace, "document_revision", previous["source_id"] + ":v" + prior_document["version"], prior_document)
            self.store.put(db, namespace, kind, identifier, record)
            self.store.put(db, namespace, "document", record["source_id"], documents[key])
            db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (namespace, record["source_id"]))
            db.execute("INSERT INTO knowledge(namespace,source_id,content) VALUES(?,?,?)", (namespace, record["source_id"], documents[key]["content"]))
        for key, record in incoming.items():
            references = []
            closure = _dependency_closure(db, key, dependencies)
            for dependency in [key] + sorted(closure - {key}):
                parent = world[dependency]
                parent_source = self.store.get(db, namespace, "document", parent["source_id"])
                references.append({"source_id": parent_source["source_id"], "version": parent_source["version"], "source_sha256": checksum(parent_source)})
            self.store.put(db, namespace, "external_record_binding", binding_id(*key), {
                "entity_type": key[0], "record_id": key[1], "version": record["version"], "owner_id": context["owner_id"],
                "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"], "execution_namespace": namespace, "sources": references})
        result = {"source_type": "SIMULATED", "simulation_definition": DEFINITION, "execution_namespace": namespace,
            "import_id": "import-" + str(uuid.uuid4()), "state": payload["outcome"], "error_code": payload["error_code"],
            "record_count": len(incoming), "external_service_invoked": False, "received_at": received,
            "records": [{"entity_type": kind, "record_id": identifier, "version": record["version"], "source_id": record["source_id"]} for (kind, identifier), record in sorted(incoming.items())]}
        self.store.put(db, namespace, "external_import", result["import_id"], result)
        return result

    @staticmethod
    def _validate_processing(world):
        groups = {}
        for (kind, _), record in world.items():
            if kind == "quality_trace" and record["record_state"] == "ACTIVE" and record["state"] == "CONFIRMED":
                groups.setdefault(record["data"]["processing_id"], []).append(record["data"])
        for rows in groups.values():
            for field in ("input_batch_id", "output_batch_id", "quantity_unit", "input_quantity", "output_quantity", "loss_quantity"):
                known = {Decimal(row[field]) if field.endswith("_quantity") else row[field] for row in rows if row[field] is not None}
                require(len(known) <= 1, "同一加工编号的已确认数量或批次关系冲突", web.HTTPBadRequest)
            destinations = [(row["inventory_id"], row["customer_id"]) for row in rows if row["inventory_id"] is not None or row["customer_id"] is not None]
            require(len(destinations) == len(set(destinations)), "同一加工编号的流向重复", web.HTTPBadRequest)
            if all(row["destination_quantity"] is not None for row in rows):
                outputs = [Decimal(row["output_quantity"]) for row in rows if row["output_quantity"] is not None]
                with localcontext() as decimal_context:
                    decimal_context.prec = 80
                    require(not outputs or sum(Decimal(row["destination_quantity"]) for row in rows) <= outputs[0], "流向总量超过加工产出量", web.HTTPBadRequest)

    def _validate_record(self, record, previous, initial, context):
        kind, data = record["entity_type"], record["data"]
        observed = datetime.fromisoformat(record["observed_at"])
        start = datetime.fromisoformat(record["valid_from"])
        end = datetime.fromisoformat(record["valid_until"]) if record["valid_until"] else None
        require(observed <= datetime.fromisoformat(context["clock"]) and (end is None or start < end), "外部资料观察或有效时间不合法", web.HTTPBadRequest)
        if previous:
            for field in IDENTITY_FIELDS[kind]:
                require(previous["data"][field] is None or previous["data"][field] == data[field], "已知业务身份不能改为其他对象")
            require(previous["state"] not in TERMINAL_STATES.get(kind, set()) or previous["state"] == record["state"], "已终止的外部业务状态不能重新启用")
        dimensions = {"legal_entity_id": "legal_entity_id", "customer_id": "customer_id", "product_id": "product_id", "region_id": "region_id"}
        for field, source_field in dimensions.items():
            if data.get(field) is not None:
                require(data[field] in {row[source_field] for row in initial["details"]}, "外部资料维度不属于当前获准范围", web.HTTPForbidden)
        if "ownership_type" in data:
            require(data["ownership_type"] != "COMPANY" or data["asset_owner_id"] == data["legal_entity_id"], "公司资产归属不符", web.HTTPBadRequest)
            require(data["ownership_type"] != "CUSTOMER" or data["customer_id"] is not None and data["asset_owner_id"] == data["customer_id"], "客户资产归属不符", web.HTTPBadRequest)
        if "author_contact_id" in data:
            require(data["author_contact_id"] == record["author_contact_id"], "业务作者和来源署名不符", web.HTTPBadRequest)
        if kind in ("inventory_lot", "production_batch"):
            require((data["material_id"] is None) != (data["product_id"] is None), "原料与成品维度必须明确且互斥", web.HTTPBadRequest)
        if kind == "production_batch":
            require((data["batch_type"] == "RAW_MATERIAL") == (data["material_id"] is not None), "批次类别与资料维度不符", web.HTTPBadRequest)
        if kind == "inventory_lot":
            require(data["quantity"] is None or data["available_quantity"] is None or Decimal(data["available_quantity"]) <= Decimal(data["quantity"]), "可用量超过报告库存量", web.HTTPBadRequest)
            require(data["quality_state"] == "RELEASED" and not data["in_transit"] or data["available_quantity"] is None or Decimal(data["available_quantity"]) == 0,
                    "待检、限制或在途库存不能报告可用数量", web.HTTPBadRequest)
        if kind == "contact":
            require(date.fromisoformat(data["valid_from"]) <= observed.date() <= date.fromisoformat(data["valid_until"]), "联系人职责在观察时无效", web.HTTPBadRequest)
        if kind == "material_quote":
            require(datetime.fromisoformat(data["quoted_at"]) <= observed, "报价时间晚于来源观察时间", web.HTTPBadRequest)
        if kind in ("material_consumption", "production_capacity"):
            require(datetime.fromisoformat(data["period_start"]) < datetime.fromisoformat(data["period_end"]), "业务期间的起止时间不合法", web.HTTPBadRequest)
        if kind == "production_capacity":
            require(data["timezone"] in available_timezones(), "时区不属于有效IANA范围", web.HTTPBadRequest)
        if kind == "material_contract":
            require(datetime.fromisoformat(data["delivery_window"]["starts_at"]) < datetime.fromisoformat(data["delivery_window"]["ends_at"]), "交付时间范围不合法", web.HTTPBadRequest)
        if kind == "feed_formula":
            require(len({row["material_id"] for row in data["ingredients"]}) == len(data["ingredients"]), "原料比例的编号重复", web.HTTPBadRequest)
            ratios = [Decimal(row["ratio"]) for row in data["ingredients"] if row["ratio"] is not None]
            require(all(ratio <= 1 for ratio in ratios), "原料比例超过单位范围", web.HTTPBadRequest)
            require(not data["composition_complete"] or len(ratios) == len(data["ingredients"]) and sum(ratios) == 1,
                    "完整比例资料必须具有全部数值且总和为1", web.HTTPBadRequest)
            require(data["valid_until"] is None or datetime.fromisoformat(data["valid_from"]) < datetime.fromisoformat(data["valid_until"]), "比例资料有效时间不合法", web.HTTPBadRequest)
        if kind == "quality_trace":
            require(data["trace_state"] != "CONFIRMED" or all(data[field] is not None for field in ("input_batch_id", "output_batch_id", "processing_id")), "已确认关系缺少稳定批次或加工编号", web.HTTPBadRequest)
            if data["trace_state"] == "CONFIRMED" and all(data[field] is not None for field in ("input_quantity", "output_quantity", "loss_quantity")):
                with localcontext() as decimal_context:
                    decimal_context.prec = 80
                    require(Decimal(data["input_quantity"]) == Decimal(data["output_quantity"]) + Decimal(data["loss_quantity"]), "已确认投入产出数量不平衡", web.HTTPBadRequest)

    def _validate_relationships(self, record, world, initial_contacts, initial):
        kind, data, author = record["entity_type"], record["data"], record["author_contact_id"]
        author_data = initial_contacts.get(author)
        if author_data is None:
            require(("contact", author) in world, "来源作者不在当前联系人资料内", web.HTTPNotFound)
            author_data = world[("contact", author)]["data"]
        observed_date = datetime.fromisoformat(record["observed_at"]).date().isoformat()
        require(author_data["valid_from"] <= observed_date <= author_data["valid_until"], "来源作者在观察时已经失效", web.HTTPForbidden)
        if kind in ("professional_record", "agriculture_observation", "feed_formula"):
            require(author_data.get("record_authority") == "SIMULATED_PROFESSIONAL", "专业资料需要明确的模拟专业作者", web.HTTPForbidden)
        for dependency in _direct_dependencies(record, initial_contacts):
            require(dependency in world, "引用的外部记录不存在", web.HTTPNotFound)
        if kind == "professional_record" and data["event_id"] is not None:
            require(("production_event", data["event_id"]) in world, "专业记录关联的事件不存在", web.HTTPNotFound)
        if kind == "inventory_lot":
            batch = world[("production_batch", data["batch_id"])]["data"]
            require(all(batch[field] == data[field] for field in ("material_id", "product_id", "legal_entity_id", "ownership_type", "asset_owner_id", "quantity_unit")),
                    "库存与原始批次的身份、归属或单位不符", web.HTTPBadRequest)
            if data["contract_id"] is not None:
                contract = world[("material_contract", data["contract_id"])]["data"]
                require(all(contract[field] == data[field] for field in ("material_id", "legal_entity_id", "quantity_unit", "currency")), "库存和合同范围不符", web.HTTPBadRequest)
        if kind == "material_consumption" and data["inventory_id"] is not None:
            inventory = world[("inventory_lot", data["inventory_id"])]["data"]
            require(all(inventory[field] == data[field] for field in ("material_id", "legal_entity_id", "quantity_unit", "currency")), "耗用与库存范围不符", web.HTTPBadRequest)
        if kind == "quality_trace" and data["trace_state"] == "CONFIRMED":
            input_batch, output_batch = world[("production_batch", data["input_batch_id"])]["data"], world[("production_batch", data["output_batch_id"])]["data"]
            require(input_batch["quantity_unit"] == output_batch["quantity_unit"] == data["quantity_unit"] and input_batch["legal_entity_id"] == output_batch["legal_entity_id"], "已确认追溯范围或单位不一致", web.HTTPBadRequest)
            if data["inventory_id"] is not None:
                require(world[("inventory_lot", data["inventory_id"])]["data"]["batch_id"] == data["output_batch_id"], "追溯库存不属于该产出批次", web.HTTPBadRequest)
            require(data["inventory_id"] is None or data["customer_id"] is None, "同一流向记录必须分别表达库存和客户数量", web.HTTPBadRequest)
        if kind == "feed_formula" and data["professional_state"] == "PROFESSIONALLY_CONFIRMED":
            require(data["professional_record_id"] is not None and world[("professional_record", data["professional_record_id"])]["data"]["state"] in ("PROFESSIONALLY_CONFIRMED", "REVIEW_RESULT_REPORTED"),
                    "比例资料缺少对应的专业报告状态", web.HTTPBadRequest)

    def _withdraw(self, db, context, payload):
        kind, identifier, namespace = payload["entity_type"], payload["record_id"], context["namespace"]
        record = self.store.get(db, namespace, kind, identifier)
        require(record.get("simulation_definition") == DEFINITION and record["owner_id"] == context["owner_id"], "当前记录不属于模拟外部资料范围", web.HTTPForbidden)
        require(record["version"] == payload["expected_version"] and record["record_state"] == "ACTIVE", "记录版本已经变化或已经撤销")
        document = self.store.get(db, namespace, "document", record["source_id"])
        self.store.put(db, namespace, kind + "_revision", identifier + ":v" + record["version"], record)
        self.store.put(db, namespace, "document_revision", record["source_id"] + ":v" + document["version"], document)
        updated = {**record, "version": str(int(record["version"]) + 1), "source_version": str(int(record["version"]) + 1), "record_state": "WITHDRAWN", "state": "WITHDRAWN"}
        withdrawn = {**document, "version": updated["version"], "withdrawn": True, "withdrawn_at": now(), "withdrawal_reason_sha256": checksum(payload["reason"])}
        self.store.put(db, namespace, kind, identifier, updated)
        self.store.put(db, namespace, "document", record["source_id"], withdrawn)
        previous_binding = self.store.get(db, namespace, "external_record_binding", binding_id(kind, identifier))
        references = [{"source_id": reference["source_id"], "version": withdrawn["version"], "source_sha256": checksum(withdrawn)} if reference["source_id"] == withdrawn["source_id"] else reference for reference in previous_binding["sources"]]
        self.store.put(db, namespace, "external_record_binding", binding_id(kind, identifier), {**previous_binding, "version": updated["version"], "sources": references})
        db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (namespace, record["source_id"]))
        return {"source_type": "SIMULATED", "entity_type": kind, "record_id": identifier, "version": updated["version"], "record_state": "WITHDRAWN", "source_id": record["source_id"], "external_service_invoked": False}

    def _coordinate(self, db, context, payload):
        from boss_supply_quality_views import read_projection
        namespace, kind = context["namespace"], payload["origin_entity_type"]
        require(kind in ENTITY_CONFIG and ENTITY_CONFIG[kind]["interface"] == payload["interface_id"], "协调来源与当前接口不符", web.HTTPBadRequest)
        view = read_projection(self.store, db, context, payload["interface_id"])
        require(payload["review_sha256"] == view["review_sha256"], "当前资料或协调任务已经变化，需要重新核查")
        origin = next((record for record in view["records"] if record["entity_type"] == kind and record["record_id"] == payload["origin_record_id"]), None)
        require(origin is not None and origin["version"] == payload["origin_version"], "协调来源已经失效或版本变化")
        require(not any(link["review_sha256"] == payload["review_sha256"] for link in view["coordination_links"]), "当前核查已经创建协调任务，请读取原结果")
        initial = self.store.get(db, namespace, "initial", "snapshot")
        references = bound_source_references(db, context, kind, origin)
        require(references is not None, "当前来源缺少采用依据")
        source_ids = [reference["source_id"] for reference in references]
        documents = self.store.assignment_sources(db, namespace, initial, source_ids)
        content = {field: payload[field] for field in ("purpose", "coordinator_id", "due_at", "timezone", "evidence_requirements")}
        content.update(content_version="1", related_meeting_id=None, related_event_ids=[], source_refs=source_ids)
        authorization_id = self.store.authorize_in_transaction(db, namespace, "create_assignment", content)
        authorization = self.store.get(db, namespace, "authorization", authorization_id)
        self.store.require_current_authorization(authorization, namespace, initial, "create_assignment", content)
        tool_input = {**content, "authorization_id": authorization_id, "idempotency_key": payload["client_request_id"],
                      "envelope": {"request_id": payload["client_request_id"], "session_id": "supply-quality-coordination",
                                   "owner_id": context["owner_id"], "execution_namespace": namespace,
                                   "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"]}}
        validate("assignment_input", tool_input)
        result = self.store.create_assignment(db, namespace, initial, tool_input)
        validate("assignment_output", result)
        task = self.store.get(db, namespace, "task", result["task_id"])
        task["source_versions"] = {identifier: document["version"] for identifier, document in documents.items()}
        self.store.put(db, namespace, "task", result["task_id"], task)
        link = {"link_id": "supply-quality-" + result["task_id"], "task_id": result["task_id"], "interface_id": payload["interface_id"],
                "origin_entity_type": kind, "origin_record_id": origin["record_id"], "origin_version": origin["version"],
                "review_sha256": payload["review_sha256"], "created_at": result["persisted_at"], "source_type": "SIMULATED"}
        self.store.put(db, namespace, "supply_quality_coordination", link["link_id"], link)
        return {**result, "source_type": "SIMULATED", "coordination_link": link, "external_service_invoked": False,
                "purchase_executed": False, "quality_release_executed": False}

    def read(self, role, interface_id):
        self._role(role, "BOSS")
        require(interface_id in ("SI09", "SI10"), "查询接口不属于采购库存或生产质量", web.HTTPBadRequest)
        from boss_simulation_api import _context
        from boss_supply_quality_views import read_projection
        with self.store.connect() as db:
            db.execute("BEGIN")
            return validate_result("Projection", read_projection(self.store, db, _context(db), interface_id))

    def read_http(self, role, query_string):
        self._role(role, "BOSS")
        require(isinstance(query_string, str) and len(query_string.encode("utf-8")) <= 4096, "业务读取参数无效或过长", web.HTTPBadRequest)
        parameters = parse_qs(query_string, keep_blank_values=True)
        require(set(parameters) == {"interface_id"} and len(parameters["interface_id"]) == 1, "只允许单项接口标识", web.HTTPBadRequest)
        return self.read(role, parameters["interface_id"][0])

    def receipt(self, role, action, client_request_id):
        require(action in ACTION_INPUTS, "未知模拟业务动作", web.HTTPNotFound)
        self._role(role, ACTION_INPUTS[action][0])
        validator = Draft202012Validator({**SCHEMA, "$ref": "#/$defs/ClientId"})
        require(not list(validator.iter_errors(client_request_id)), "请求编号格式无效", web.HTTPBadRequest)
        from boss_simulation_api import _context
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (context["namespace"], action, client_request_id)).fetchone()
            return validate_result("Receipt", {"source_type": "SIMULATED", "action": action, "client_request_id": client_request_id,
                    "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "result": json.loads(row[0]) if row else None})

    def receipt_http(self, role, query_string):
        require(isinstance(query_string, str) and len(query_string.encode("utf-8")) <= 4096, "回执读取参数无效或过长", web.HTTPBadRequest)
        parameters = parse_qs(query_string, keep_blank_values=True)
        require(set(parameters) == {"action", "client_request_id"} and all(len(values) == 1 for values in parameters.values()), "回执读取参数不完整或重复", web.HTTPBadRequest)
        return self.receipt(role, parameters["action"][0], parameters["client_request_id"][0])
