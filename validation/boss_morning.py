import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, encode, now, require
from boss_morning_projection import project, object_at, order_key
from boss_simulation_api import _context

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "specs/morning.schema.json").read_text())
QUERY_ACTION = "boss.morning.query"
ORDER_ACTION = "boss.today.reorder"


def validate(name, value):
    require(not list(Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}, format_checker=FormatChecker()).iter_errors(value)), "晨间输入输出不符合Schema：" + name, web.HTTPBadRequest)
    return value


def _existing(db, ns, action, key, payload):
    row = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (ns, action, key)).fetchone()
    if row:
        require(row[0] == checksum(payload), "同一晨间请求编号的内容已经变化")
        return json.loads(row[1])
    require(db.execute("SELECT 1 FROM idempotency WHERE namespace<>? AND operation=? AND key=?", (ns, action, key)).fetchone() is None, "原晨间请求编号属于其他执行空间")
    return None


def _save_receipt(db, ns, action, key, payload, result):
    db.execute("INSERT INTO idempotency VALUES(?,?,?,?,?)", (ns, action, key, checksum(payload), encode(result)))
    db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)", (ns, action,
               encode({field: payload[field] for field in ("client_request_id", "date", "timezone", "list_id") if field in payload}),
               encode({field: result[field] for field in ("list_id", "list_version", "date", "timezone", "version", "authorization_id") if field in result}), now()))


class MorningAPI:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _role(role):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "BOSS", "晨间事项与私人资料仅限本人访问", web.HTTPForbidden)

    def read(self, role, day):
        self._role(role)
        validate("Day", day)
        with self.store.connect() as db:
            db.execute("BEGIN")
            result, _ = project(self.store, db, _context(db), day)
            return validate("View", result)

    def query(self, role, payload):
        self._role(role)
        validate("Query", payload)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            ns = context["namespace"]
            previous = _existing(db, ns, QUERY_ACTION, payload["client_request_id"], payload)
            if previous is not None:
                self._current(db, context, previous["list_id"])
                return previous
            day = {field: payload[field] for field in ("date", "timezone")}
            result, binding = project(self.store, db, context, day)
            key = order_key(day, self.store.get(db, ns, "initial", "snapshot"))
            sequence = object_at(db, ns, "morning_sequence", key)
            version = str(int(sequence["version"]) + 1) if sequence else "1"
            result.update(list_id="morning-" + str(uuid.uuid4()), list_version=version)
            validate("View", result)
            self.store.put(db, ns, "morning_list", result["list_id"], {"owner_id": context["owner_id"], "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"],
                "execution_namespace": ns, "session_id": payload["session_id"], "client_request_id": payload["client_request_id"], "result": result, "binding": binding})
            self.store.put(db, ns, "morning_sequence", key, {"version": version})
            _save_receipt(db, ns, QUERY_ACTION, payload["client_request_id"], payload, result)
            return result

    def _stored(self, db, context, list_id):
        validate("Id", list_id)
        row = self.store.get(db, context["namespace"], "morning_list", list_id)
        require(row["owner_id"] == context["owner_id"] and row["dataset_id"] == context["dataset_id"] and row["dataset_version"] == context["dataset_version"]
                and row["execution_namespace"] == context["namespace"], "晨间清单不属于当前本人范围", web.HTTPForbidden)
        return row

    def _current(self, db, context, list_id):
        stored = self._stored(db, context, list_id)
        result = stored["result"]
        current, binding = project(self.store, db, context, {field: result[field] for field in ("date", "timezone")})
        require(current["snapshot_sha256"] == result["snapshot_sha256"], "晨间对象、来源或范围已变化，需要重新查询")
        return stored, current, binding

    def read_list(self, role, list_id, historical=False):
        self._role(role)
        require(type(historical) is bool, "历史读取标识无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            stored = self._stored(db, context, list_id)
            saved = stored["result"]
            current, _ = project(self.store, db, context, {field: saved[field] for field in ("date", "timezone")})
            valid = current["snapshot_sha256"] == saved["snapshot_sha256"]
            require(valid or historical, "晨间对象或来源已变化，需要重新查询")
            result = saved
            if not valid:
                # 历史保留编号与版本；失效私人内容及派生时间不重新呈现。
                result = {**saved, "items": [], "preparation_materials": [], "conflicts": [], "profile": {"owner_confirmation": "REQUIRES_REQUERY"}, "source_statuses": [],
                          "excluded_items": [], "source_coverage": [], "missing_sources": ["HISTORICAL_CONTENT_REQUIRES_REQUERY"], "data_as_of": None,
                          "input_coverage": [], "category_counts": None,
                          "conflict_state": "INSUFFICIENT_EVIDENCE", "coverage_state": "UNAVAILABLE", "ordering_reason": "历史内容需要重新核查"}
            return validate("ReadList", {"adoption_state": "CURRENT" if valid else "HISTORICAL_REQUIRES_REQUERY", "result": result,
                    "binding_references": list({encode(ref): ref for item in saved["items"] for ref in item["source_refs"]}.values()),
                    "current_order": {"version": current["order_version"], "state": current["order_state"], "item_ids": [item["item_id"] for item in current["items"]]} if valid else None})

    def detail(self, role, list_id, item_id):
        self._role(role)
        validate("Id", item_id)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            stored, _, binding = self._current(db, context, list_id)
            item = next((item for item in stored["result"]["items"] if item["item_id"] == item_id), None)
            require(item is not None, "事项不属于当前清单", web.HTTPNotFound)
            objects = [{"reference": ref, "data": binding["objects"][ref["kind"] + ":" + ref["id"]]} for ref in item["source_refs"] if ref["kind"] != "document"]
            documents = [binding["documents"][ref["id"]] for ref in item["source_refs"] if ref["kind"] == "document"]
            return validate("Detail", {"source_type": "SIMULATED", "list_id": list_id, "list_version": stored["result"]["list_version"], "snapshot_sha256": stored["result"]["snapshot_sha256"],
                    "item": item, "objects": objects, "documents": documents, "business_authorization_granted": False})

    def reorder(self, role, payload):
        self._role(role)
        validate("Reorder", payload)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            ns = context["namespace"]
            previous = _existing(db, ns, ORDER_ACTION, payload["client_request_id"], payload)
            if previous is not None:
                return previous
            saved, view, _ = self._current(db, context, payload["list_id"])
            require(bool(view["items"]), "当前没有可保存次序的获准事项", web.HTTPBadRequest)
            require(all(payload[field] == view[field] for field in ("date", "timezone", "snapshot_sha256")) and payload["expected_version"] == view["order_version"], "日期、时区、集合快照或排序版本已变化")
            require(set(payload["item_ids"]) == {item["item_id"] for item in view["items"]}, "本人次序必须包含完整当前事项集合", web.HTTPBadRequest)
            version = str(int(view["order_version"]) + 1)
            authorization_id = str(uuid.uuid4())
            auth = {"authorization_id": authorization_id, "owner_id": context["owner_id"], "issuer_identity": "BOSS", "issuer": context["owner_id"],
                    "source_instruction_id": payload["client_request_id"], "source_instruction": "本人在已认证入口明确保存当前日期的事项次序",
                    "action": "today.reorder", "scope": ns, "target_id": payload["list_id"], "content_version": version, "payload": payload,
                    "version": "1", "revoked": False, "revoked_at": None, "valid_from": now(), "valid_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}
            result = {"source_type": "SIMULATED", "list_id": payload["list_id"], "list_version": saved["result"]["list_version"], "date": view["date"], "timezone": view["timezone"],
                      "version": version, "snapshot_sha256": view["snapshot_sha256"], "item_ids": payload["item_ids"], "authorization_id": authorization_id}
            initial = self.store.get(db, ns, "initial", "snapshot")
            validate("OrderResult", result)
            self.store.put(db, ns, "authorization", authorization_id, auth)
            self.store.put(db, ns, "today_order", order_key(view, initial), result)
            _save_receipt(db, ns, ORDER_ACTION, payload["client_request_id"], payload, result)
            return result

    def source(self, role, list_id, source_id):
        self._role(role)
        validate("Id", source_id)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            stored, view, binding = self._current(db, context, list_id)
            reference = next((row for row in view["source_statuses"] if row["source_id"] == source_id), None)
            require(reference is not None and reference["status"] == "VALID" and source_id in binding["documents"], "来源不属于当前可采用清单", web.HTTPForbidden)
            return validate("SourceDetail", {"source_type": "SIMULATED", "list_id": list_id, "list_version": stored["result"]["list_version"], "document": binding["documents"][source_id], "business_authorization_granted": False})

    def receipt(self, role, action, client_request_id):
        self._role(role)
        require(action in (QUERY_ACTION, ORDER_ACTION), "未知晨间动作", web.HTTPBadRequest)
        validate("Id", client_request_id)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (context["namespace"], action, client_request_id)).fetchone()
            result = json.loads(row[0]) if row else None
            if action == QUERY_ACTION and result is not None:
                result = {key: result[key] for key in ("list_id", "list_version", "date", "timezone", "snapshot_sha256")}
            return validate("Receipt", {"action": action, "client_request_id": client_request_id, "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "result": result})
