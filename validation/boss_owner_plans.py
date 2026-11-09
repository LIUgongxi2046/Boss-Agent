import json
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiohttp import web

from business import checksum, now, require
from boss_command_api import BossCommandAPI

from boss_execution_scope import NAMESPACE as NS

PLAN_BUDGET_FIELDS = frozenset({"model_requests", "rounds", "tools", "seconds", "concurrency", "context_tokens", "files", "file_bytes", "open_files", "cpu_seconds"})


def valid_plan_budget(budget):
    return (isinstance(budget, dict) and set(budget) == PLAN_BUDGET_FIELDS
            and all(type(value) is int and value > 0 for value in budget.values()) and budget["open_files"] >= 16)


def valid_plan_execution_choices(outputs, method):
    from agent_run_method_selection import VALIDATOR as METHOD_VALIDATOR
    from agent_run_requirements import VALIDATOR as OUTPUTS_VALIDATOR
    return OUTPUTS_VALIDATOR.is_valid(outputs) and METHOD_VALIDATOR.is_valid(method)


def _items(db, kind):
    return [json.loads(row[0]) for row in db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (NS, kind),
    ).fetchall()]


def stop_business_until(stops):
    require(isinstance(stops, dict) and set(stops) == {"business_until"}
            and isinstance(stops["business_until"], str), "停止条件必须指定业务结束时间", web.HTTPBadRequest)
    until = datetime.fromisoformat(stops["business_until"])
    require(until.tzinfo is not None and until.utcoffset() is not None, "停止时间必须包含时区", web.HTTPBadRequest)
    return until.astimezone(timezone.utc)


def plan_authorization_status(store, db, ns, plan, physical_time):
    if plan.get("state") != "ACTIVE":
        return "OWNER_PLAN_" + str(plan.get("state"))
    auth = store.get(db, ns, "authorization", plan["authorization_id"])
    if auth.get("revoked") is not False:
        return "OWNER_PLAN_AUTHORIZATION_REVOKED"
    if (auth.get("authorization_id") != plan["authorization_id"] or auth.get("owner_id") != plan.get("owner_id")
            or auth.get("issuer") != plan.get("owner_id") or auth.get("issuer_identity") != "BOSS"
            or auth.get("scope") != ns or auth.get("target_id") != plan.get("plan_id")):
        return "OWNER_PLAN_AUTHORIZATION_INVALID"
    start = datetime.fromisoformat(auth["valid_from"])
    end = datetime.fromisoformat(auth["valid_until"])
    require(start.tzinfo is not None and start.utcoffset() is not None and end.tzinfo is not None
            and end.utcoffset() is not None and physical_time.tzinfo is not None and physical_time.utcoffset() is not None,
            "本人计划授权时间不可核查", web.HTTPConflict)
    if not start <= physical_time < end:
        return "OWNER_PLAN_AUTHORIZATION_EXPIRED"
    fields = ("purpose", "event_ids", "timezone", "not_before", "event_versions")
    extended = ("budget", "stop_conditions", "conversation_id", "source_refs", "scope_proof")
    has_extended = [field in plan for field in extended]
    if any(has_extended) and not all(has_extended):
        return "OWNER_PLAN_AUTHORIZATION_SCOPE_CHANGED"
    if all(has_extended):
        fields += extended
        choices = ("required_outputs", "method_selection")
        if any(field in plan for field in choices):
            if not all(field in plan for field in choices) or not valid_plan_execution_choices(plan["required_outputs"], plan["method_selection"]):
                return "OWNER_PLAN_AUTHORIZATION_SCOPE_CHANGED"
            fields += choices
    if any(field not in plan for field in fields):
        return "OWNER_PLAN_AUTHORIZATION_SCOPE_CHANGED"
    if auth.get("action") == "owner_plan.resume":
        version = plan.get("version")
        if not isinstance(version, str) or not version.isdecimal() or int(version) < 3:
            return "OWNER_PLAN_AUTHORIZATION_SCOPE_CHANGED"
        paused_version = str(int(version) - 1)
        previous_version = str(int(version) - 2)
        if (auth.get("content_version") != paused_version or auth.get("payload") != {"plan_id": plan["plan_id"], "expected_version": paused_version}
                or plan.get("last_action_authorization_id") != plan["authorization_id"]):
            return "OWNER_PLAN_AUTHORIZATION_SCOPE_CHANGED"
        paused = store.get(db, ns, "owner_plan_revision", plan["plan_id"] + ":" + paused_version)
        previous = store.get(db, ns, "owner_plan_revision", plan["plan_id"] + ":" + previous_version)
        if (paused.get("plan_id") != plan["plan_id"] or paused.get("version") != paused_version or paused.get("state") != "PAUSED"
                or previous.get("plan_id") != plan["plan_id"] or previous.get("version") != previous_version
                or previous.get("state") != "ACTIVE" or paused.get("authorization_id") != previous.get("authorization_id")
                or paused.get("owner_id") != plan.get("owner_id") or previous.get("owner_id") != plan.get("owner_id")
                or paused.get("source_type") != plan.get("source_type") or previous.get("source_type") != plan.get("source_type")
                or any(field not in paused or field not in previous or paused[field] != plan[field] or previous[field] != plan[field] for field in fields)):
            return "OWNER_PLAN_AUTHORIZATION_SCOPE_CHANGED"
        return plan_authorization_status(store, db, ns, previous, physical_time)
    if auth.get("action") != "owner_plan.save" or auth.get("content_version") != plan.get("version"):
        return "OWNER_PLAN_AUTHORIZATION_SCOPE_CHANGED"
    if auth.get("payload") != {field: plan[field] for field in fields}:
        return "OWNER_PLAN_AUTHORIZATION_SCOPE_CHANGED"
    return None


def suppression(store, db, ns, event, clock):
    identifier = event.get("owner_plan_id")
    if identifier is None:
        return None
    plan = store.get(db, ns, "owner_plan", identifier)
    if plan["state"] != "ACTIVE":
        return "OWNER_PLAN_" + plan["state"]
    if event["event_id"] not in plan["event_ids"]:
        return "OWNER_PLAN_SCOPE_CHANGED"
    if plan["event_versions"][event["event_id"]] != event["version"]:
        return "OWNER_PLAN_SOURCE_CHANGED"
    status = plan_authorization_status(store, db, ns, plan, datetime.now(timezone.utc))
    if status is not None:
        return status
    if "stop_conditions" in plan and clock >= stop_business_until(plan["stop_conditions"]):
        return "OWNER_PLAN_STOPPED"
    if "scope_proof" in plan:
        return "OWNER_PLAN_SCOPE_UNVERIFIED"
    if clock < datetime.fromisoformat(plan["not_before"]):
        return "OWNER_PLAN_NOT_DUE"
    return None


class OwnerPlansAPI:
    def _execution_selection(self, channel, scope_service):
        from agent_run_method_selection import AgentRunMethodSelection
        from agent_run_store import RunStore
        skills = channel.skills
        require(skills is not None, "计划方法服务尚未准备", web.HTTPServiceUnavailable)
        return AgentRunMethodSelection(RunStore(self.store.path, allow_migration=False), scope_service, skills.catalog, skills.drafts)

    def execution_methods(self, request, channel, scope_service, payload):
        from agent_run_scope import RunScopeService
        from boss_simulation_api import _context
        from role_channel import RoleChannel

        require(isinstance(request, web.Request) and isinstance(channel, RoleChannel) and isinstance(scope_service, RunScopeService), "需要实际本人请求及会话范围", web.HTTPUnauthorized)
        channel.require_run_api_role(request)
        require(channel.boss_commands is not None and channel.boss_commands.store.path.resolve() == self.store.path.resolve()
                and scope_service.store.path.resolve() == self.store.path.resolve() and channel.gateway.session_manager is scope_service.sources.sessions,
                "身份和计划服务不属于同一环境", web.HTTPForbidden)
        require(isinstance(payload, dict), "计划输入必须为对象", web.HTTPBadRequest)
        self.commands._exact(payload, {"plan_id", "expected_version", "conversation_id", "source_refs"})
        refs, chat_id = payload["source_refs"], payload["conversation_id"]
        require(isinstance(refs, list) and bool(refs) and all(isinstance(item, str) and item.strip() for item in refs) and len(set(refs)) == len(refs), "计划来源无效", web.HTTPBadRequest)
        channel.require_run_subscription(request, chat_id)
        selection = self._execution_selection(channel, scope_service)
        with selection.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            require(context["namespace"] == NS, "计划执行空间不符", web.HTTPForbidden)
            plan = self.store.get(db, NS, "owner_plan", payload["plan_id"])
            require(plan.get("plan_id") == payload["plan_id"] and plan.get("version") == payload["expected_version"] and plan.get("owner_id") == context["owner_id"] and plan.get("state") == "ACTIVE" and plan.get("source_type") == "SIMULATED", "计划状态或版本不可用")
            for event_id in plan["event_ids"]:
                event = self.store.get(db, NS, "event", event_id)
                require(event.get("owner_plan_id") == plan["plan_id"] and event.get("version") == plan["event_versions"].get(event_id) and event.get("state") != "CANCELED", "计划事件已经变化")
            proof = scope_service.prove_in_transaction(db, chat_id, refs)
            require((proof.owner_id, proof.namespace, proof.dataset_id, proof.dataset_version) == (context["owner_id"], context["namespace"], context["dataset_id"], context["dataset_version"]), "计划会话范围不符", web.HTTPForbidden)
            methods = selection.catalog_in_transaction(db)
            channel.require_run_subscription(request, chat_id)
            return {"plan_id": plan["plan_id"], "version": plan["version"], "conversation_id": chat_id, "source_refs": refs, "methods": methods}

    def __init__(self, store):
        self.store = store
        self.commands = BossCommandAPI(store)

    @staticmethod
    def _role(role):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "BOSS", "本人计划仅限本人访问", web.HTTPForbidden)

    def read(self, role):
        self._role(role)
        with self.store.connect() as db:
            self.store.active(db, NS)
            plans = _items(db, "owner_plan")
            events = _items(db, "event")
            return {
                "source_type": "SIMULATED", "plans": plans,
                "events": [{k: e[k] for k in ("event_id", "version", "state", "due_at")} for e in events],
                "results": [r for r in _items(db, "notification") if r.get("owner_plan_id")],
                "dispatches": [r for r in _items(db, "dispatch") if r.get("owner_plan_id")],
                "technical_schedule": {k: self.store.get(db, NS, "schedule", "current")[k]
                                       for k in ("version", "enabled", "canceled")},
                "execution_owner": "CronService", "external_delivery_verified": False,
            }

    def execute(self, role, action, payload):
        self._role(role)
        require(action in ("save", "pause", "resume", "cancel"), "未知计划操作", web.HTTPNotFound)
        require(isinstance(payload, dict), "计划输入必须为对象", web.HTTPBadRequest)
        operation = "boss.owner.plan." + action
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, NS)
            key, digest, previous = self.commands._check_existing(db, operation, payload)
            if previous is not None:
                return previous
            if action == "save":
                result = self._save(db, payload)
            else:
                result = self._status(db, action, payload)
            self.commands._record(db, operation, payload, key, digest, result)
            return result

    def bind_execution(self, request, channel, scope_service, payload):
        from agent_run_scope import RunScopeService
        from boss_simulation_api import _context
        from role_channel import RoleChannel

        require(isinstance(request, web.Request) and isinstance(channel, RoleChannel), "需要实际本人请求", web.HTTPUnauthorized)
        require(isinstance(scope_service, RunScopeService), "需要会话范围服务", web.HTTPServiceUnavailable)
        channel.require_run_api_role(request)
        require(channel.boss_commands is not None and channel.boss_commands.store.path.resolve() == self.store.path.resolve()
                and scope_service.store.path.resolve() == self.store.path.resolve()
                and channel.gateway.session_manager is scope_service.sources.sessions, "身份和计划服务不属于同一环境", web.HTTPForbidden)
        require(isinstance(payload, dict), "计划输入必须为对象", web.HTTPBadRequest)
        self.commands._exact(payload, {"client_request_id", "plan_id", "expected_version", "conversation_id", "source_refs", "budget", "stop_conditions", "authorization_id", "required_outputs", "method_selection"})
        refs, budget, stops, chat_id = payload["source_refs"], payload["budget"], payload["stop_conditions"], payload["conversation_id"]
        require(isinstance(refs, list) and bool(refs) and all(isinstance(item, str) and item.strip() for item in refs)
                and len(set(refs)) == len(refs), "计划来源无效", web.HTTPBadRequest)
        require(valid_plan_budget(budget), "计划预算无效", web.HTTPBadRequest)
        require(valid_plan_execution_choices(payload["required_outputs"], payload["method_selection"]), "计划成果要求或方法无效", web.HTTPBadRequest)
        stop_business_until(stops)
        channel.require_run_subscription(request, chat_id)
        operation = "boss.owner.plan.execution.bind"
        selection = self._execution_selection(channel, scope_service)
        with selection.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            selection._current_method(db, payload["method_selection"])
            context = _context(db)
            require(context["namespace"] == NS, "计划执行空间不符", web.HTTPForbidden)
            proof = scope_service.prove_in_transaction(db, chat_id, refs)
            require((proof.owner_id, proof.namespace, proof.dataset_id, proof.dataset_version) ==
                    (context["owner_id"], context["namespace"], context["dataset_id"], context["dataset_version"]), "计划会话范围不符", web.HTTPForbidden)
            saved_proof = json.loads(json.dumps(asdict(proof), ensure_ascii=False))
            key, digest, previous = self.commands._check_existing(db, operation, payload)
            if previous is not None:
                current_plan = self.store.get(db, NS, "owner_plan", previous["plan_id"])
                require(current_plan.get("version") == previous["version"] and current_plan.get("authorization_id") == previous["authorization_id"]
                        and current_plan.get("scope_proof") == saved_proof and current_plan.get("state") == "ACTIVE"
                        and current_plan.get("required_outputs") == payload["required_outputs"]
                        and current_plan.get("method_selection") == payload["method_selection"],
                        "原计划或会话范围已经变化")
                channel.require_run_subscription(request, chat_id)
                return previous
            identifier = payload["plan_id"]
            plan = self.store.get(db, NS, "owner_plan", identifier)
            require(plan.get("plan_id") == identifier and plan.get("owner_id") == context["owner_id"]
                    and plan.get("state") == "ACTIVE" and plan.get("source_type") == "SIMULATED"
                    and plan.get("version") == payload["expected_version"] and plan["version"].isdecimal(), "计划状态或版本不可用")
            require(stop_business_until(stops) > datetime.fromisoformat(plan["not_before"]).astimezone(timezone.utc), "停止时间必须晚于计划开始时间")
            for event_id in plan["event_ids"]:
                event = self.store.get(db, NS, "event", event_id)
                require(event.get("owner_plan_id") == identifier and event.get("version") == plan["event_versions"].get(event_id)
                        and event.get("state") != "CANCELED", "计划事件已经变化")
            next_version = str(int(plan["version"]) + 1)
            fields = ("purpose", "event_ids", "timezone", "not_before", "event_versions")
            bound = {**{name: plan[name] for name in fields}, "budget": budget, "stop_conditions": stops,
                     "conversation_id": chat_id, "source_refs": refs, "scope_proof": saved_proof,
                     "required_outputs": payload["required_outputs"], "method_selection": payload["method_selection"]}
            auth = self.store.get(db, NS, "authorization", payload["authorization_id"])
            start, end = datetime.fromisoformat(auth["valid_from"]), datetime.fromisoformat(auth["valid_until"])
            require(start.tzinfo is not None and end.tzinfo is not None and start <= datetime.now(timezone.utc) < end,
                    "本人授权已经过期", web.HTTPForbidden)
            require(auth.get("authorization_id") == payload["authorization_id"] and auth.get("owner_id") == context["owner_id"]
                    and auth.get("issuer_identity") == "BOSS" and auth.get("issuer") == context["owner_id"]
                    and isinstance(auth.get("source_instruction_id"), str) and bool(auth["source_instruction_id"])
                    and auth.get("scope") == NS and auth.get("target_id") == identifier and auth.get("action") == "owner_plan.save"
                    and auth.get("content_version") == next_version and auth.get("payload") == bound and auth.get("revoked") is False,
                    "本人授权内容或范围不符", web.HTTPForbidden)
            self.store.put(db, NS, "owner_plan_revision", identifier + ":" + plan["version"], plan)
            updated = {**plan, **bound, "version": next_version, "authorization_id": auth["authorization_id"], "updated_at": now()}
            self.store.put(db, NS, "owner_plan", identifier, updated)
            result = {"plan_id": identifier, "version": next_version, "authorization_id": auth["authorization_id"], "state": updated["state"]}
            channel.require_run_subscription(request, chat_id)
            current = scope_service.prove_in_transaction(db, chat_id, refs)
            require(json.loads(json.dumps(asdict(current), ensure_ascii=False)) == saved_proof, "计划会话来源已经变化")
            self.commands._record(db, operation, payload, key, digest, result)
            channel.require_run_subscription(request, chat_id)
            return result

    def preview_execution(self, request, channel, scope_service, payload):
        from agent_run_scope import RunScopeService
        from boss_simulation_api import _context
        from hermes_schedule_adapter import HermesScheduleAdapter
        from role_channel import RoleChannel

        require(isinstance(request, web.Request) and isinstance(channel, RoleChannel), "需要实际本人请求", web.HTTPUnauthorized)
        require(isinstance(scope_service, RunScopeService), "需要会话范围服务", web.HTTPServiceUnavailable)
        channel.require_run_api_role(request)
        require(channel.boss_commands is not None and channel.boss_commands.store.path.resolve() == self.store.path.resolve()
                and scope_service.store.path.resolve() == self.store.path.resolve()
                and channel.gateway.session_manager is scope_service.sources.sessions, "身份和计划服务不属于同一环境", web.HTTPForbidden)
        require(isinstance(payload, dict), "计划输入必须为对象", web.HTTPBadRequest)
        self.commands._exact(payload, {"plan_id", "expected_version", "conversation_id", "source_refs", "budget", "stop_conditions", "required_outputs", "method_selection"})
        refs, budget, stops, chat_id = payload["source_refs"], payload["budget"], payload["stop_conditions"], payload["conversation_id"]
        require(isinstance(refs, list) and bool(refs) and all(isinstance(item, str) and item.strip() for item in refs)
                and len(set(refs)) == len(refs), "计划来源无效", web.HTTPBadRequest)
        require(valid_plan_budget(budget), "计划预算无效", web.HTTPBadRequest)
        require(valid_plan_execution_choices(payload["required_outputs"], payload["method_selection"]), "计划成果要求或方法无效", web.HTTPBadRequest)
        stop_business_until(stops)
        channel.require_run_subscription(request, chat_id)
        selection = self._execution_selection(channel, scope_service)
        with selection.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            selection._current_method(db, payload["method_selection"])
            HermesScheduleAdapter._require_schema(db)
            context = _context(db)
            require(context["namespace"] == NS, "计划执行空间不符", web.HTTPForbidden)
            proof = scope_service.prove_in_transaction(db, chat_id, refs)
            require((proof.owner_id, proof.namespace, proof.dataset_id, proof.dataset_version) ==
                    (context["owner_id"], context["namespace"], context["dataset_id"], context["dataset_version"]), "计划会话范围不符", web.HTTPForbidden)
            identifier = payload["plan_id"]
            plan = self.store.get(db, NS, "owner_plan", identifier)
            require(plan.get("plan_id") == identifier and plan.get("owner_id") == context["owner_id"]
                    and plan.get("state") == "ACTIVE" and plan.get("source_type") == "SIMULATED"
                    and plan.get("version") == payload["expected_version"] and plan["version"].isdecimal(), "计划状态或版本不可用")
            require(stop_business_until(stops) > datetime.fromisoformat(plan["not_before"]).astimezone(timezone.utc), "停止时间必须晚于计划开始时间")
            for event_id in plan["event_ids"]:
                event = self.store.get(db, NS, "event", event_id)
                require(event.get("owner_plan_id") == identifier and event.get("version") == plan["event_versions"].get(event_id)
                        and event.get("state") != "CANCELED", "计划事件已经变化")
            fields = ("purpose", "event_ids", "timezone", "not_before", "event_versions")
            bound = {**{name: plan[name] for name in fields}, "budget": budget, "stop_conditions": stops,
                     "conversation_id": chat_id, "source_refs": refs,
                     "scope_proof": json.loads(json.dumps(asdict(proof), ensure_ascii=False)),
                     "required_outputs": payload["required_outputs"], "method_selection": payload["method_selection"]}
            current = scope_service.prove_in_transaction(db, chat_id, refs)
            require(json.loads(json.dumps(asdict(current), ensure_ascii=False)) == bound["scope_proof"], "计划会话来源已经变化")
            channel.require_run_subscription(request, chat_id)
            preview_id = str(uuid.uuid4())
            result = {"preview_id": preview_id, "plan_id": identifier, "expected_version": plan["version"],
                      "content_version": str(int(plan["version"]) + 1), "action": "owner_plan.save",
                      "payload": bound, "payload_sha256": checksum(bound)}
            db.execute("INSERT INTO hermes_schedule_previews (preview_id,owner_id,namespace,plan_id,plan_sha256,payload_sha256,preview,created_at) VALUES (?,?,?,?,?,?,?,?)",
                       (preview_id, context["owner_id"], context["namespace"], identifier, checksum(plan), result["payload_sha256"],
                        json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False), datetime.now(timezone.utc).isoformat()))
            channel.require_run_subscription(request, chat_id)
            return result

    def decide_execution(self, request, channel, scope_service, payload):
        from agent_run_scope import RunScopeService
        from boss_simulation_api import _context
        from hermes_schedule_adapter import HermesScheduleAdapter
        from role_channel import RoleChannel

        require(isinstance(request, web.Request) and isinstance(channel, RoleChannel), "需要实际本人请求", web.HTTPUnauthorized)
        require(isinstance(scope_service, RunScopeService), "需要会话范围服务", web.HTTPServiceUnavailable)
        channel.require_run_api_role(request)
        require(channel.boss_commands is not None and channel.boss_commands.store.path.resolve() == self.store.path.resolve()
                and scope_service.store.path.resolve() == self.store.path.resolve()
                and channel.gateway.session_manager is scope_service.sources.sessions, "身份和计划服务不属于同一环境", web.HTTPForbidden)
        require(isinstance(payload, dict), "本人决定必须为对象", web.HTTPBadRequest)
        self.commands._exact(payload, {"preview_id", "payload_sha256", "decision", "client_request_id"})
        require(payload["decision"] in ("CONFIRM", "REJECT") and isinstance(payload["preview_id"], str)
                and isinstance(payload["payload_sha256"], str) and isinstance(payload["client_request_id"], str)
                and 8 <= len(payload["client_request_id"]) <= 128, "本人决定字段无效", web.HTTPBadRequest)
        selection = self._execution_selection(channel, scope_service)
        with selection.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            HermesScheduleAdapter._require_schema(db)
            context = _context(db)
            row = db.execute("SELECT owner_id,namespace,plan_id,plan_sha256,payload_sha256,preview,created_at,decision,authorization_id,decision_request_id FROM hermes_schedule_previews WHERE preview_id=?", (payload["preview_id"],)).fetchone()
            require(row is not None and row[0] == context["owner_id"] and row[1] == context["namespace"] == NS, "计划预览不可用", web.HTTPNotFound)
            saved = json.loads(row[5])
            bound = saved["payload"]
            require(valid_plan_budget(bound.get("budget")), "计划预览缺少完整预算", web.HTTPConflict)
            require(valid_plan_execution_choices(bound.get("required_outputs"), bound.get("method_selection")), "计划预览缺少成果要求或方法", web.HTTPConflict)
            selection._current_method(db, bound["method_selection"])
            chat_id, refs = bound["conversation_id"], bound["source_refs"]
            channel.require_run_subscription(request, chat_id)
            require(row[4] == payload["payload_sha256"] == checksum(bound), "计划预览摘要不符")
            if row[7] is not None:
                require((row[7], row[9]) == (payload["decision"], payload["client_request_id"]), "本人决定已经记录")
                return {"preview_id": payload["preview_id"], "decision": row[7], "authorization_id": row[8]}
            require(datetime.now(timezone.utc) < datetime.fromisoformat(row[6]) + timedelta(minutes=15), "计划预览已经过期")
            plan = self.store.get(db, NS, "owner_plan", row[2])
            require(checksum(plan) == row[3] and plan.get("state") == "ACTIVE" and plan.get("version") == saved["expected_version"], "本人计划已经变化")
            for event_id in plan["event_ids"]:
                event = self.store.get(db, NS, "event", event_id)
                require(event.get("owner_plan_id") == row[2] and event.get("version") == plan["event_versions"].get(event_id)
                        and event.get("state") != "CANCELED", "计划事件已经变化")
            proof = scope_service.prove_in_transaction(db, chat_id, refs)
            require(json.loads(json.dumps(asdict(proof), ensure_ascii=False)) == bound["scope_proof"]
                    and (proof.owner_id, proof.namespace, proof.dataset_id, proof.dataset_version) ==
                    (context["owner_id"], context["namespace"], context["dataset_id"], context["dataset_version"]), "计划会话来源已经变化")
            auth_id = None
            if payload["decision"] == "CONFIRM":
                require(context["owner_id"] == "boss-1", "本人身份与授权服务不符", web.HTTPForbidden)
                auth_id = self.commands._authorize(db, "owner_plan.save", bound, row[2], saved["content_version"])
            channel.require_run_subscription(request, chat_id)
            db.execute("UPDATE hermes_schedule_previews SET decision=?,authorization_id=?,decision_request_id=?,decided_at=? WHERE preview_id=?",
                       (payload["decision"], auth_id, payload["client_request_id"], datetime.now(timezone.utc).isoformat(), payload["preview_id"]))
            channel.require_run_subscription(request, chat_id)
            return {"preview_id": payload["preview_id"], "decision": payload["decision"], "authorization_id": auth_id}

    def execution_receipt(self, request, channel, scope_service, *, plan_id, client_request_id, operation):
        from agent_run_scope import RunScopeService
        from boss_execution_transition import pending_transition
        from boss_simulation_api import _context
        from hermes_schedule_adapter import HermesScheduleAdapter
        from role_channel import RoleChannel

        require(isinstance(request, web.Request) and isinstance(channel, RoleChannel), "需要实际本人请求", web.HTTPUnauthorized)
        require(isinstance(scope_service, RunScopeService), "需要会话范围服务", web.HTTPServiceUnavailable)
        channel.require_run_api_role(request)
        require(channel.boss_commands is not None and channel.boss_commands.store.path.resolve() == self.store.path.resolve()
                and scope_service.store.path.resolve() == self.store.path.resolve()
                and channel.gateway.session_manager is scope_service.sources.sessions, "身份和计划服务不属于同一环境", web.HTTPForbidden)
        require(isinstance(plan_id, str) and 0 < len(plan_id) <= 128 and isinstance(client_request_id, str)
                and 8 <= len(client_request_id) <= 128 and operation in ("decision", "binding"), "原请求参数无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            db.execute("BEGIN")
            HermesScheduleAdapter._require_schema(db)
            context = _context(db)
            require(context["namespace"] == NS and pending_transition(db, NS) is None, "计划执行空间不可用", web.HTTPForbidden)
            if operation == "decision":
                row = db.execute("SELECT preview_id,preview,decision,authorization_id FROM hermes_schedule_previews WHERE owner_id=? AND namespace=? AND plan_id=? AND decision_request_id=?", (context["owner_id"], NS, plan_id, client_request_id)).fetchone()
                require(row is not None and row[2] in ("CONFIRM", "REJECT"), "原决定回执不存在", web.HTTPNotFound)
                preview = json.loads(row[1])
                require(preview.get("plan_id") == plan_id and checksum(preview["payload"]) == preview["payload_sha256"], "原计划预览不可核查")
                chat_id = preview["payload"]["conversation_id"]
                if row[2] == "CONFIRM":
                    auth = self.store.get(db, NS, "authorization", row[3])
                    require(auth.get("owner_id") == context["owner_id"] and auth.get("issuer") == context["owner_id"]
                            and auth.get("issuer_identity") == "BOSS" and auth.get("scope") == NS
                            and auth.get("target_id") == plan_id and auth.get("action") == "owner_plan.save"
                            and auth.get("content_version") == preview["content_version"] and auth.get("payload") == preview["payload"], "原决定授权不可核查")
                else:
                    require(row[3] is None, "原拒绝决定不可核查")
                receipt = {"preview_id": row[0], "decision": row[2], "authorization_id": row[3]}
            else:
                row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (NS, "boss.owner.plan.execution.bind", client_request_id)).fetchone()
                require(row is not None, "原绑定回执不存在", web.HTTPNotFound)
                receipt = json.loads(row[0])
                require(receipt.get("plan_id") == plan_id, "原绑定回执不存在", web.HTTPNotFound)
                plan = self.store.get(db, NS, "owner_plan", plan_id)
                if plan.get("version") != receipt.get("version"):
                    plan = self.store.get(db, NS, "owner_plan_revision", plan_id + ":" + receipt["version"])
                require(plan.get("owner_id") == context["owner_id"] and plan.get("version") == receipt["version"]
                        and plan.get("authorization_id") == receipt["authorization_id"], "原计划绑定不可核查")
                auth = self.store.get(db, NS, "authorization", receipt["authorization_id"])
                fields = ("purpose", "event_ids", "timezone", "not_before", "event_versions", "budget", "stop_conditions", "conversation_id", "source_refs", "scope_proof")
                if "required_outputs" in plan or "method_selection" in plan:
                    fields += ("required_outputs", "method_selection")
                require(auth.get("owner_id") == context["owner_id"] and auth.get("issuer") == context["owner_id"]
                        and auth.get("issuer_identity") == "BOSS" and auth.get("scope") == NS and auth.get("target_id") == plan_id
                        and auth.get("content_version") == receipt["version"] and auth.get("action") == "owner_plan.save"
                        and all(field in plan for field in fields) and auth.get("payload") == {field: plan[field] for field in fields}, "原绑定授权不可核查")
                chat_id = plan["conversation_id"]
            channel.require_run_subscription(request, chat_id)
            return {"plan_id": plan_id, "client_request_id": client_request_id, "operation": operation, "receipt": receipt}

    def _save(self, db, payload):
        self.commands._exact(payload, {
            "client_request_id", "plan_id", "expected_version", "purpose",
            "event_ids", "timezone", "not_before",
        })
        identifier = payload["plan_id"]
        require(isinstance(identifier, str) and len(identifier) <= 128, "计划标识无效", web.HTTPBadRequest)
        current = self.store.get(db, NS, "owner_plan", identifier) if identifier else None
        require(payload["expected_version"] == (current["version"] if current else "0"), "本人计划版本冲突")
        require(not current or current["state"] != "CANCELED", "已取消计划不能修改")
        purpose = payload["purpose"]
        require(isinstance(purpose, str) and 0 < len(purpose.strip()) <= 400, "计划用途缺少或过长", web.HTTPBadRequest)
        require(payload["timezone"] == "Asia/Shanghai", "当前业务时钟使用 Asia/Shanghai", web.HTTPBadRequest)
        instant = datetime.fromisoformat(payload["not_before"])
        require(instant.tzinfo is not None and instant.utcoffset() == instant.astimezone(ZoneInfo(payload["timezone"])).utcoffset(),
                "计划时间必须与时区一致", web.HTTPBadRequest)
        clock = datetime.fromisoformat(self.store.get(db, NS, "clock", "current")["at"])
        require(instant > clock, "计划时间必须晚于当前业务时间", web.HTTPBadRequest)
        require((instant - clock).total_seconds() <= 366 * 86400, "本人计划时间不能超过366天", web.HTTPBadRequest)
        identifiers = payload["event_ids"]
        require(isinstance(identifiers, list) and 1 <= len(identifiers) <= 32
                and all(isinstance(e, str) and 0 < len(e) <= 128 for e in identifiers)
                and len(set(identifiers)) == len(identifiers), "事件范围缺少、重复或无效", web.HTTPBadRequest)
        events = [self.store.get(db, NS, "event", e) for e in identifiers]
        identifier = identifier or str(uuid.uuid4())
        for event in events:
            require(event["state"] != "CANCELED", "已取消事件不能加入计划")
            other = event.get("owner_plan_id")
            if other and other != identifier:
                require(self.store.get(db, NS, "owner_plan", other)["state"] == "CANCELED", "事件已有本人计划")
        version = str(int(current["version"]) + 1) if current else "1"
        content = {k: payload[k] for k in ("purpose", "event_ids", "timezone", "not_before")}
        content["event_versions"] = {e["event_id"]: e["version"] for e in events}
        auth = self.commands._authorize(db, "owner_plan.save", content, identifier, version)
        plan = {**content, "plan_id": identifier, "version": version,
                "state": current["state"] if current else "ACTIVE", "authorization_id": auth,
                "owner_id": "boss-1", "source_type": "SIMULATED", "updated_at": now(),
                "execution_owner": "CronService"}
        if current:
            self.store.put(db, NS, "owner_plan_revision", identifier + ":" + current["version"], current)
        self.store.put(db, NS, "owner_plan", identifier, plan)
        for event in events:
            self.store.put(db, NS, "event", event["event_id"], {**event, "owner_plan_id": identifier})
        return plan

    def _status(self, db, action, payload):
        self.commands._exact(payload, {"client_request_id", "plan_id", "expected_version"})
        plan = self.store.get(db, NS, "owner_plan", payload["plan_id"])
        require(plan["version"] == payload["expected_version"], "本人计划版本冲突")
        allowed = {"pause": ("ACTIVE",), "resume": ("PAUSED",), "cancel": ("ACTIVE", "PAUSED")}
        require(plan["state"] in allowed[action], "当前计划状态不支持该操作")
        self.store.put(db, NS, "owner_plan_revision", plan["plan_id"] + ":" + plan["version"], plan)
        auth = self.commands._authorize(db, "owner_plan." + action, {
            "plan_id": plan["plan_id"], "expected_version": plan["version"],
        }, plan["plan_id"], plan["version"])
        plan = {**plan, "version": str(int(plan["version"]) + 1),
                "state": {"pause": "PAUSED", "resume": "ACTIVE", "cancel": "CANCELED"}[action],
                "updated_at": now(), "last_action_authorization_id": auth}
        if action == "resume":
            plan["authorization_id"] = auth
        self.store.put(db, NS, "owner_plan", plan["plan_id"], plan)
        return plan
