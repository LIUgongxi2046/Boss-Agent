from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from aiohttp import web

from business import checksum, encode, now, require
from boss_alert_policy import DEFINITION, GENERATOR, MANIFEST, get, validate
from boss_metrics import aggregate_metrics
from boss_simulation_api import _context
from boss_source_access import require_current_business_source


def scope(db):
    context = _context(db)
    require(context["namespace"] == "ui-check" and context["owner_id"] == "boss-1", "当前经营提醒执行范围不符", web.HTTPForbidden)
    return context


def commands_for(store):
    from boss_command_api import BossCommandAPI
    return BossCommandAPI(store)


def receipt_for(store, operation, client_request_id):
    validate("Id", client_request_id)
    with store.connect() as db:
        db.execute("BEGIN")
        ns = scope(db)["namespace"]
        row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (ns, operation, client_request_id)).fetchone()
        import json
        return validate("Receipt", {"action": operation, "client_request_id": client_request_id, "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "result": json.loads(row[0]) if row else None})


class BusinessAlertRulesAPI:
    def __init__(self, store):
        self.store = store
        self.commands = commands_for(store)

    def read(self, role):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        with self.store.connect() as db:
            db.execute("BEGIN")
            ns = scope(db)["namespace"]
            draft, active = get(db, ns, "business_alert_rule_draft", "current"), get(db, ns, "business_alert_rule", "current")
            return validate("RuleRead", {"source_type": "SIMULATED", "definition": MANIFEST, "draft": draft if role == "BOSS" or draft and draft["created_by_role"] == role else None,
                "active": active if role == "BOSS" or active and active["created_by_role"] == role else None,
                "active_version": active["version"] if active else "0", "business_authorization_granted": False})

    def execute(self, role, action, payload):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(action in ("save", "validate", "activate", "disable"), "未知经营规则动作", web.HTTPNotFound)
        validate({"save": "RuleSave", "validate": "RuleVersion", "activate": "RuleActivate", "disable": "RuleVersion"}[action], payload)
        operation = ("boss.alert.rule." if role == "BOSS" else "boss.simulation.alert.rule.") + action
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = scope(db)
            ns = context["namespace"]
            key, digest, previous = self.commands._check_existing(db, operation, payload)
            if previous is not None:
                return previous
            draft, active = get(db, ns, "business_alert_rule_draft", "current"), get(db, ns, "business_alert_rule", "current")
            if action == "save":
                cfg = payload["configuration"]
                require(Decimal(cfg["threshold_pp"]) > 0, "经营阈值必须大于零", web.HTTPBadRequest)
                require(role == "BOSS" or cfg == MANIFEST["configuration"], "维护只能采用获准固定演示规则", web.HTTPForbidden)
                require(role == "BOSS" or draft is None or draft["created_by_role"] == role, "维护不能修改本人规则草稿", web.HTTPForbidden)
                require(payload["expected_version"] == (draft["version"] if draft else "0"), "经营规则草稿版本变化")
                result = {"source_type": "SIMULATED", "version": str(int(payload["expected_version"]) + 1), "state": "DRAFT", "configuration": cfg,
                    "owner_id": context["owner_id"], "namespace": ns, "created_by_role": role, "definition_version": DEFINITION}
                self.store.put(db, ns, "business_alert_rule_draft", "current", result)
            elif action == "validate":
                require(draft is not None and draft["version"] == payload["expected_version"] and draft["state"] == "DRAFT", "经营规则草稿不符")
                require(role == "BOSS" or draft["created_by_role"] == role, "维护不能采用本人规则", web.HTTPForbidden)
                validate("Configuration", draft["configuration"])
                result = {**draft, "version": str(int(draft["version"]) + 1), "state": "VALIDATED", "validated_sha256": checksum(draft["configuration"])}
                self.store.put(db, ns, "business_alert_rule_draft", "current", result)
            elif action == "activate":
                require(draft is not None and draft["state"] == "VALIDATED" and draft["version"] == payload["expected_version"]
                        and draft["validated_sha256"] == checksum(draft["configuration"]), "只能启用当前已校验规则")
                require(payload["expected_active_version"] == (active["version"] if active else "0"), "当前经营规则版本变化")
                require(role == "BOSS" or draft["created_by_role"] == role and draft["configuration"] == MANIFEST["configuration"], "维护不能扩大本人规则", web.HTTPForbidden)
                require(role == "BOSS" or active is None or active["created_by_role"] == role, "维护不能替代当前本人规则", web.HTTPForbidden)
                version = str(int(payload["expected_active_version"]) + 1)
                auth = self.commands._authorize(db, "business_alert.rule.activate", {"configuration_sha256": checksum(draft["configuration"]), "draft_version": draft["version"]}, "business-alert-rule", version) if role == "BOSS" else None
                result = {**draft, "version": version, "draft_version": draft["version"], "state": "ACTIVE", "created_by_role": role,
                    "authorization_id": auth, "activated_at": now(), "business_authorization_granted": False}
                if active:
                    self.store.put(db, ns, "business_alert_rule_revision", active["version"], active)
                self.store.put(db, ns, "business_alert_rule", "current", result)
            else:
                require(active is not None and active["state"] == "ACTIVE" and active["version"] == payload["expected_version"], "当前经营规则不可停用")
                require(role == "BOSS" or active["created_by_role"] == role, "维护不能替代本人规则决定", web.HTTPForbidden)
                result = {**active, "version": str(int(active["version"]) + 1), "state": "DISABLED"}
                if role == "BOSS":
                    result["last_action_authorization_id"] = self.commands._authorize(db, "business_alert.rule.disable", {"expected_version": active["version"]}, "business-alert-rule", active["version"])
                self.store.put(db, ns, "business_alert_rule_revision", active["version"], active)
                self.store.put(db, ns, "business_alert_rule", "current", result)
            saved = {field: result[field] for field in ("source_type", "version", "state")}
            if role == "BOSS" and action in ("activate", "disable"):
                saved["authorization_id"] = result["authorization_id"] if action == "activate" else result["last_action_authorization_id"]
            validate("RuleResult", saved)
            self.commands._record(db, operation, payload, key, digest, saved)
            return saved

    def receipt(self, role, action, client_request_id):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(action in ("save", "validate", "activate", "disable"), "未知经营规则动作", web.HTTPNotFound)
        operation = ("boss.alert.rule." if role == "BOSS" else "boss.simulation.alert.rule.") + action
        return receipt_for(self.store, operation, client_request_id)


class BusinessAlertInputAPI:
    def __init__(self, store):
        self.store = store
        self.commands = commands_for(store)

    def receipt(self, role, client_request_id):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "MAINTAINER", "演示载入回执仅限维护身份", web.HTTPForbidden)
        return receipt_for(self.store, "boss.simulation.alert.load", client_request_id)

    def load(self, role, payload):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "MAINTAINER", "演示资料载入仅限维护身份", web.HTTPForbidden)
        validate("Load", payload)
        operation = "boss.simulation.alert.load"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = scope(db)
            ns = context["namespace"]
            require(context["dataset_id"] == "selection" and context["dataset_version"] == "1", "生成定义不适用于当前资料", web.HTTPForbidden)
            key, digest, previous = self.commands._check_existing(db, operation, payload)
            if previous is not None:
                return previous
            event_id = MANIFEST["event_id"]
            original = get(db, ns, "event", event_id)
            require(payload["expected_version"] == (original["version"] if original else "0"), "经营观察版本变化")
            require(original is None or original["state"] != "CANCELED", "已取消经营事件不能重新启用")
            data = self.store.get(db, ns, "initial", "snapshot")
            require(db.execute("SELECT snapshot FROM spaces WHERE namespace=?", (ns,)).fetchone()[0] == checksum(data), "获准初始资料已变化，需要核查来源")
            finance = require_current_business_source(self.store, db, ns, data["owner_id"], "finance-note")
            data_as_of = self.store.source(finance, data, None)["business_as_of"]
            clock = self.store.get(db, ns, "clock", "current")["at"]
            require(original is None or datetime.fromisoformat(clock) > datetime.fromisoformat(original["observed_at"]), "新的观察必须具有递增业务时间")
            base_rows, current_rows = ([row for row in data["details"] if row["period"] == period] for period in ("BASE", "CURRENT"))
            base_metrics = aggregate_metrics(base_rows)["metrics"]
            current_metrics = aggregate_metrics(current_rows)["metrics"]
            base, current = base_metrics["gross_margin"][0], current_metrics["gross_margin"][0]
            frame = payload["frame"]
            with localcontext() as numeric:
                numeric.prec = 80
                recovery_cost = None
                if frame == "RECOVERY":
                    base_revenue, base_cost, current_revenue = base_metrics["revenue"][0], base_metrics["cost"][0], current_metrics["revenue"][0]
                    recovery_cost = current_revenue * base_cost / base_revenue if base_revenue and base_cost is not None and current_revenue is not None else None
                    current = (current_revenue - recovery_cost) / current_revenue * 100 if current_revenue and recovery_cost is not None else None
                change = current - base if current is not None and base is not None else None
            facts = {"metric_id": "gross_margin", "base_value": str(base) if base is not None else None, "current_value": str(current) if current is not None else None,
                "change_pp": str(change) if change is not None else None, "unit": "%", "change_unit": "百分点", "comparison_periods": data["periods"],
                "scope": "region-1 EXTERNAL_SALES CNY", "metric_data_as_of": data_as_of, "complete": change is not None, "confidence": "LOW" if frame == "LOW_CONFIDENCE" else "HIGH",
                "handler_id": None if frame == "MISSING_HANDLER" else "coordinator-1", "impact": "IMPORTANT" if frame == "RESOURCE_SHORTAGE" else "NORMAL",
                "impact_amount": None, "impact_currency": None,
                "participation": "INFORM_ONLY" if frame == "PROGRESS" else "CROSS_FUNCTION_RESOURCE_SHORTAGE" if frame == "RESOURCE_SHORTAGE" else "THRESHOLD_ESCALATION",
                "participation_reason": "一般进展进入汇总" if frame == "PROGRESS" else "演示资料明确报告跨职责资源不足，需要本人协调" if frame == "RESOURCE_SHORTAGE" else "比较期间毛利变化需要按有效关注规则核查",
                "frame": frame, "source_type": "SIMULATED"}
            version, sid = str(int(payload["expected_version"]) + 1), "fc04-observation:" + event_id
            old_document = get(db, ns, "document", sid)
            if old_document:
                require(old_document.get("source_type") == "SIMULATED" and old_document.get("access_scope") == data["owner_id"]
                        and old_document.get("simulation_definition") == DEFINITION and not old_document.get("withdrawn"), "原演示报告无权更新或已经撤销", web.HTTPGone)
                require(original is not None and checksum(old_document) == original["source_fingerprints"][sid], "当前演示原文已变化")
                self.store.put(db, ns, "document_history", sid + ":" + old_document["version"], old_document)
            provenance = {field: MANIFEST[field] for field in ("definition_version", "seed", "source_type", "author_kind", "allowed_use", "real_enterprise_data", "third_party_authorization")}
            document = {**provenance, "source_id": sid, "version": version, "access_scope": data["owner_id"], "owner_id": data["owner_id"],
                "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"], "execution_namespace": ns,
                "input_source_refs": [{"source_id": finance["source_id"], "version": finance["version"]}],
                "input_source_fingerprints": {finance["source_id"]: checksum(finance)}, "initial_snapshot_sha256": checksum(data),
                "simulation_definition": DEFINITION, "created_by_role": role, "published_at": now(), "received_at": now(), "observed_at": clock, "valid_from": clock,
                "valid_until": (datetime.fromisoformat(clock) + timedelta(days=30)).isoformat(), "withdrawn": False,
                "author_contact_id": "simulated-generator:FC04-ALERT-1", "original_locator": "sqlite:business-alert-observation/" + event_id + ":v" + version,
                "content": encode({**provenance, "facts": facts, "observed_at": clock, "description": MANIFEST["description"],
                    "initial_snapshot_sha256": checksum(data), "basis_records": base_rows + current_rows,
                    "simulated_recovery_current_cost_cny": str(recovery_cost) if recovery_cost is not None else None}), "business_authorization_granted": False}
            self.store.put(db, ns, "document", sid, document)
            event = {"event_id": event_id, "version": version, "state": "CANCELED" if frame == "CANCELED" else "RECOVERED" if frame == "RECOVERY" else "OPEN",
                "generated_by": GENERATOR, "source_type": "SIMULATED", "owner_id": data["owner_id"], "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"], "execution_namespace": ns,
                "due_at": clock, "observed_at": clock, "data_as_of": data_as_of, "impact": facts["impact"], "facts": facts,
                "basis_sha256": checksum({"snapshot": checksum(data), "periods": data["periods"], "finance": checksum(finance), "scope": facts["scope"]}),
                "source_refs": [{"source_id": row["source_id"], "version": row["version"]} for row in (finance, document)],
                "source_fingerprints": {row["source_id"]: checksum(row) for row in (finance, document)},
                **({"owner_plan_id": original["owner_plan_id"]} if original and original.get("owner_plan_id") else {})}
            self.store.put(db, ns, "event", event_id, event)
            self.store.put(db, ns, "business_alert_observation", event_id + ":v" + version, event)
            db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (ns, sid))
            db.execute("INSERT INTO knowledge VALUES(?,?,?)", (ns, sid, document["content"]))
            result = {"source_type": "SIMULATED", "event_id": event_id, "event_version": version, "source_id": sid, "source_version": version,
                "definition_version": DEFINITION, "business_authorization_granted": False, "external_service_invoked": False}
            validate("LoadResult", result)
            self.commands._record(db, operation, payload, key, digest, result)
            return result
