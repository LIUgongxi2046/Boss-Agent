import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import available_timezones

from aiohttp import web

from business import checksum, encode, now, require
from boss_morning import validate, _existing, _save_receipt
from boss_morning_projection import object_at, order_key
from boss_simulation_api import _context

MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "specs/morning-coverage.json").read_text())
LOAD_ACTION = "boss.simulation.morning_coverage.load"


class MorningInputAPI:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _role(role):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "MAINTAINER", "只有维护身份可以载入明确模拟覆盖", web.HTTPForbidden)

    def catalog(self, role):
        self._role(role)
        return MANIFEST

    def load(self, role, payload):
        self._role(role)
        validate("CoverageLoad", payload)
        require(payload["timezone"] in available_timezones(), "IANA时区无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = _context(db)
            ns = context["namespace"]
            previous = _existing(db, ns, LOAD_ACTION, payload["client_request_id"], payload)
            if previous is not None:
                return previous
            initial = self.store.get(db, ns, "initial", "snapshot")
            day = {field: payload[field] for field in ("date", "timezone")}
            identifier = order_key(day, initial)
            saved = object_at(db, ns, "morning_coverage", identifier)
            require(payload["expected_version"] == (saved["version"] if saved else "0"), "晨间覆盖版本冲突")
            source_id = "sim-morning-coverage:" + checksum(day)
            version, timestamp = str(int(payload["expected_version"]) + 1), now()
            clock = self.store.get(db, ns, "clock", "current")["at"]
            if saved:
                old = self.store.get(db, ns, "document", source_id)
                require(old["access_scope"] == context["owner_id"] and old["version"] == saved["version"], "晨间覆盖来源范围或版本不符")
                require(not old.get("withdrawn"), "已撤销覆盖来源不能重新启用", web.HTTPGone)
                self.store.put(db, ns, "document_history", source_id + ":" + old["version"], old)
            else:
                require(object_at(db, ns, "document", source_id) is None, "晨间覆盖来源编号冲突")
            regions = [{"region_id": row["region_id"], "state": row["state"],
                        "as_of": (datetime.fromisoformat(clock) - timedelta(days=row["as_of_days_before_clock"])).isoformat() if row["as_of_days_before_clock"] is not None else None,
                        "source_id": source_id, "source_version": version} for row in MANIFEST["regions"]]
            provenance = {"source_type": "SIMULATED", "generator_version": MANIFEST["generator_version"], "seed": MANIFEST["seed"], "manifest_sha256": checksum(MANIFEST),
                          "allowed_use": MANIFEST["allowed_use"], "author_kind": "SIMULATED_GENERATOR", "real_enterprise_data": False,
                          "third_party_authorization": False, "business_authorization_granted": False}
            document = {**provenance, "source_id": source_id, "version": version, "access_scope": context["owner_id"], "owner_id": context["owner_id"],
                        "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"], "execution_namespace": ns,
                        "author_contact_id": "sim-morning-generator:FC03-COVERAGE-1", "author_display_name": "晨间覆盖本地确定性模拟生成器", "created_by_role": "MAINTAINER",
                        "published_at": timestamp, "received_at": timestamp, "observed_at": clock, "valid_from": clock,
                        "valid_until": (datetime.fromisoformat(clock) + timedelta(days=30)).isoformat(), "withdrawn": False, "validity_state": "VALID",
                        "original_locator": "sqlite:morning-coverage/" + identifier,
                        "content": encode({**provenance, **day, "regions": regions, "description": MANIFEST["description"]})}
            self.store.put(db, ns, "document", source_id, document)
            self.store.put(db, ns, "morning_coverage", identifier, {**provenance, **day, "version": version, "owner_id": context["owner_id"], "dataset_id": context["dataset_id"],
                "dataset_version": context["dataset_version"], "execution_namespace": ns, "source_id": source_id, "source_version": version, "regions": regions})
            db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (ns, source_id))
            db.execute("INSERT INTO knowledge VALUES(?,?,?)", (ns, source_id, document["content"]))
            result = {**provenance, **day, "version": version, "source_id": source_id, "source_version": version, "client_request_id": payload["client_request_id"], "external_service_invoked": False}
            validate("CoverageResult", result)
            _save_receipt(db, ns, LOAD_ACTION, payload["client_request_id"], payload, result)
            return result

    def receipt(self, role, client_request_id):
        self._role(role)
        validate("Id", client_request_id)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (context["namespace"], LOAD_ACTION, client_request_id)).fetchone()
            return {"action": LOAD_ACTION, "client_request_id": client_request_id, "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "result": json.loads(row[0]) if row else None}
