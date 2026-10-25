import json
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, encode, now, require
from boss_source_access import require_current_simulated_source
from boss_source_policy import source_validity

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "specs/bi-scenarios.json").read_text())
SCHEMA = json.loads((ROOT / "specs/bi-scenario-input.schema.json").read_text())
LOAD_ACTION = "boss.simulation.bi_scenario.load"


def _validate(name, payload):
    validator = Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}, format_checker=FormatChecker())
    require(not list(validator.iter_errors(payload)), "经营场景输入不符合Schema", web.HTTPBadRequest)


def _document(store, db, ns, identifier):
    document = store.get(db, ns, "document", identifier)
    require(document["source_id"] == identifier and document.get("simulation_definition") == MANIFEST["generator_version"], "场景来源标识或用途不符", web.HTTPForbidden)
    return document


def query_inputs(store, db, ns, initial, payload):
    scenario_id = payload.get("scenario_id")
    if scenario_id is None:
        selected = set(payload.get("source_ids", ["finance-note"])) | set(payload.get("comparison_scope", {}).get("source_ids", []))
        require(selected <= {"finance-note"}, "来源不属于当前基准资料", web.HTTPForbidden)
        return initial, [store._metric_source(db, ns, initial)]
    scenario = store.get(db, ns, "bi_scenario", scenario_id)
    require(scenario["owner_id"] == initial["owner_id"] and scenario["dataset_id"] == initial["dataset_id"]
            and scenario["dataset_version"] == initial["dataset_version"] and scenario["execution_namespace"] == ns
            and scenario["allowed_use"] == "FC02_BEHAVIOR_VALIDATION", "经营场景范围不符", web.HTTPForbidden)
    selected_ids = set(payload.get("source_ids", scenario["source_ids"])) | set(payload.get("comparison_scope", {}).get("source_ids", []))
    require(selected_ids <= set(scenario["source_ids"]), "所选来源不属于当前场景", web.HTTPForbidden)
    documents = [_document(store, db, ns, identifier) for identifier in sorted(selected_ids)]
    if "business_basis" in payload and "source_ids" not in payload and "source_ids" not in payload.get("comparison_scope", {}):
        bases = {payload["business_basis"], payload.get("comparison_scope", {}).get("business_basis", payload["business_basis"])}
        matching = [document for document in documents if document["business_basis"] in bases]
        if matching:
            documents = matching
            selected_ids = {document["source_id"] for document in documents}
    clock = store.get(db, ns, "clock", "current")["at"]
    for document in documents:
        require_current_simulated_source(document, initial["owner_id"], clock)
    return {**initial, "details": [row for row in scenario["records"] if row["source_id"] in selected_ids], "bi_scenario_id": scenario_id}, documents


def binding_current(store, db, ns, initial, binding, enforce=True):
    scenario = store.get(db, ns, "bi_scenario", binding["scenario_id"])
    require(scenario["owner_id"] == initial["owner_id"] and scenario["dataset_id"] == initial["dataset_id"]
            and scenario["dataset_version"] == initial["dataset_version"] and scenario["execution_namespace"] == ns, "经营场景范围不符", web.HTTPForbidden)
    valid = binding["definitions_sha256"] == checksum(initial["metric_definitions"])
    clock = store.get(db, ns, "clock", "current")["at"]
    for saved in binding["document_snapshots"]:
        current = _document(store, db, ns, saved["source_id"])
        require(current["access_scope"] == initial["owner_id"], "当前来源无权访问", web.HTTPForbidden)
        if enforce:
            require_current_simulated_source(current, initial["owner_id"], clock)
        valid = valid and source_validity(current, clock) == "VALID" and checksum(current) == checksum(saved)
    fingerprints = {row["record_id"]: checksum(row) for row in scenario["records"]}
    valid = valid and all(fingerprints.get(identifier) == digest for identifier, digest in binding["detail_fingerprints"].items())
    if enforce:
        require(valid, "当前经营资料已经变化，需要重新查询")
    return valid


class BIScenarioAPI:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _role(role):
        require(role in ("MAINTAINER", "BOSS"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "MAINTAINER", "只有维护身份可以载入模拟资料", web.HTTPForbidden)

    def catalog(self, role):
        self._role(role)
        return {key: MANIFEST[key] for key in ("source_type", "generator_version", "seed", "allowed_use", "author_kind", "real_enterprise_data", "third_party_authorization", "description", "scenarios")}

    def execute(self, role, action, payload):
        require(action == LOAD_ACTION, "未知经营场景动作", web.HTTPNotFound)
        return self.load(role, payload)

    def receipt(self, role, client_request_id):
        self._role(role)
        require(isinstance(client_request_id, str) and 0 < len(client_request_id) <= 128, "载入请求编号格式无效", web.HTTPBadRequest)
        from boss_simulation_api import _context
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (context["namespace"], LOAD_ACTION, client_request_id)).fetchone()
            return {"action": LOAD_ACTION, "client_request_id": client_request_id, "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "result": json.loads(row[0]) if row else None}

    def load(self, role, payload):
        self._role(role)
        _validate("Load", payload)
        from boss_simulation_api import _context
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            ns, identifier = context["namespace"], payload["scenario_id"]
            digest = checksum(payload)
            previous = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (ns, LOAD_ACTION, payload["client_request_id"])).fetchone()
            if previous:
                require(previous[0] == digest, "原场景载入编号的内容已经变化")
                return json.loads(previous[1])
            require(db.execute("SELECT 1 FROM idempotency WHERE namespace<>? AND operation=? AND key=?", (ns, LOAD_ACTION, payload["client_request_id"])).fetchone() is None,
                    "原场景请求编号属于其他执行空间")
            saved = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='bi_scenario' AND id=?", (ns, identifier)).fetchone()
            original = json.loads(saved[0]) if saved else None
            require(payload["expected_version"] == (original["version"] if original else "0"), "经营场景版本冲突")
            if original:
                require(original["owner_id"] == context["owner_id"], "经营场景不属于当前本人范围", web.HTTPForbidden)
                for source in original["source_ids"]:
                    current = _document(self.store, db, ns, source)
                    require(current["access_scope"] == context["owner_id"], "场景来源不属于当前本人范围", web.HTTPForbidden)
                    require(current["version"] == original["version"], "场景来源版本已经变化")
                    require(not current.get("withdrawn"), "已撤销的场景来源不能重新启用", web.HTTPGone)
                self.store.put(db, ns, "bi_scenario_history", identifier + ":" + original["version"], original)
            version, timestamp = str(int(payload["expected_version"]) + 1), now()
            initial = self.store.get(db, ns, "initial", "snapshot")
            definition = MANIFEST["scenarios"][identifier]
            records, documents = [], []
            for series in definition["series"]:
                basis = series["business_basis"]
                source_id = "sim-bi:" + identifier + ":" + basis
                series_records = []
                for period, dates in initial["periods"].items():
                    for index, values in enumerate(series["rows"]):
                        record = {**values, "record_id": source_id + ":" + period + ":" + str(index), "version": version,
                            "source_type": "SIMULATED", "source_id": source_id, "source_version": version, "scenario_id": identifier,
                            "period": period, "period_start": dates[0], "period_end": dates[1], "region_id": "region-1", "legal_entity_id": "entity-1",
                            "trade_type": "EXTERNAL_SALES", "currency": "CNY", "quantity_unit": "tonne", "definition_version": "1",
                            "business_basis": basis, "settlement_state": "SETTLED", "sync_state": series["sync_state"]}
                        _validate("Record", record)
                        series_records.append(record)
                source = {"source_id": source_id, "version": version, "source_type": "SIMULATED", "access_scope": context["owner_id"],
                    "owner_id": context["owner_id"], "execution_namespace": ns, "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"],
                    "author_contact_id": "sim-bi-generator:" + basis, "author_kind": "SIMULATED_GENERATOR", "generator_version": MANIFEST["generator_version"],
                    "author_display_name": "FC02本地确定性模拟资料生成器", "generator_author_id": "code:validation/boss_bi_scenarios.py@FC02-BI-1",
                    "created_by_role": "MAINTAINER",
                    "business_basis_description": definition["purpose"] + "；独立模拟口径：" + basis,
                    "coverage": "SIMULATED FC02 " + identifier + " / " + basis + "；仅用于程序行为验证",
                    "authorization_basis": "用户授权FC02内部行为验证；没有第三方授权声明", "business_authorization_granted": False,
                    "generator_parameters": {"scenario_id": identifier, "seed": payload["seed"], "manifest_sha256": checksum(MANIFEST)},
                    "allowed_use": MANIFEST["allowed_use"], "real_enterprise_data": False, "third_party_authorization": False,
                    "published_at": timestamp, "received_at": timestamp, "observed_at": context["clock"], "valid_from": context["clock"],
                    "valid_until": (datetime.fromisoformat(context["clock"]) + timedelta(days=30)).isoformat(),
                    "validity_state": "VALID", "withdrawn": False, "simulation_definition": MANIFEST["generator_version"],
                    "business_basis": basis, "original_locator": "sqlite:bi-scenario/" + identifier + "/" + basis,
                    "content": encode({"source_type": "SIMULATED", "purpose": definition["purpose"], "author_kind": "SIMULATED_GENERATOR", "business_basis": basis,
                                       "generator_version": MANIFEST["generator_version"], "parameters": series, "records": series_records,
                                       "metric_definitions": initial["metric_definitions"],
                                       "real_enterprise_data": False, "third_party_authorization": False})}
                if original:
                    old = _document(self.store, db, ns, source_id)
                    self.store.put(db, ns, "document_history", source_id + ":" + old["version"], old)
                else:
                    require(db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='document' AND id=?", (ns, source_id)).fetchone() is None, "场景来源编号冲突")
                self.store.put(db, ns, "document", source_id, source)
                db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (ns, source_id))
                db.execute("INSERT INTO knowledge VALUES(?,?,?)", (ns, source_id, source["content"]))
                documents.append(source)
                records.extend(series_records)
            scenario = {"scenario_id": identifier, "version": version, "owner_id": context["owner_id"], "source_type": "SIMULATED",
                        "execution_namespace": ns, "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"],
                        "allowed_use": MANIFEST["allowed_use"], "source_ids": [source["source_id"] for source in documents], "records": records,
                        "generator_version": MANIFEST["generator_version"], "seed": payload["seed"], "manifest_sha256": checksum(MANIFEST)}
            self.store.put(db, ns, "bi_scenario", identifier, scenario)
            result = {"action": LOAD_ACTION, "client_request_id": payload["client_request_id"], "scenario_id": identifier, "version": version,
                      "source_type": "SIMULATED", "source_ids": scenario["source_ids"], "source_versions": {source["source_id"]: version for source in documents},
                      "record_count": len(records), "generator_version": MANIFEST["generator_version"], "seed": payload["seed"], "manifest_sha256": checksum(MANIFEST),
                      "allowed_use": MANIFEST["allowed_use"], "external_service_invoked": False}
            _validate("LoadResult", result)
            db.execute("INSERT INTO idempotency VALUES(?,?,?,?,?)", (ns, LOAD_ACTION, payload["client_request_id"], digest, encode(result)))
            db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)", (ns, LOAD_ACTION,
                       encode({key: payload[key] for key in ("client_request_id", "scenario_id", "generator_version", "seed", "expected_version")}), encode(result), timestamp))
            return result
