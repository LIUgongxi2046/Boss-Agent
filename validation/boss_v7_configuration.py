import json
from datetime import datetime, timezone

from aiohttp import web
from jsonschema import Draft202012Validator

from business import OPERATIONS, SPEC, checksum, encode, now, require
from boss_v7_store import NAMESPACE, optional, rows, text
from boss_v7_metrics import METRICS, builtin_metric, effective_configuration, options as metric_options, recompute, validate_values as validate_metric_values

CONFIG_DOMAINS = {"access", "tools", "metrics"}
TECHNICAL_SCOPES = ("relationships", "audit", "knowledge", "models", "datasets", "evaluation", "simulation-events", "local-system", "tools", "metrics", "scheduler", "prompts", "skills", "simulation", "memory-status")
SIDE_EFFECTS = {"query_metrics": "QUERY_RECORD", "read_evidence": "AUDIT_ONLY", "read_assignment": "AUDIT_ONLY",
                "create_assignment": "TASK_WRITE", "send_assignment": "OUTBOX_WRITE"}
PERMISSIONS = {name: "BOSS_CURRENT_AUTHORIZATION" if name in {"create_assignment", "send_assignment"} else "BOSS_CURRENT_SCOPE" for name in OPERATIONS}


def _choices(values):
    return [{"id": value, "label": value} for value in values]


def operation_schema(operation, direction):
    return {**SPEC["io_schema"], "$ref": OPERATIONS[operation][direction + "_schema"]}


def builtin_tool(operation):
    values = {"name": operation, "operation_id": operation, "description": OPERATIONS[operation].get("description", operation),
              "connection_id": "LOCAL_CONTROL_STORE", "input_schema": encode(operation_schema(operation, "input")),
              "output_schema": encode(operation_schema(operation, "output")), "side_effect": SIDE_EFFECTS[operation],
              "permission": PERMISSIONS[operation], "timeout_seconds": 120, "idempotency_field": "idempotency_key" if operation in {"create_assignment", "send_assignment"} else "envelope.request_id",
              "error_schema": encode({"type": "object", "required": ["error"], "properties": {"error": {"type": "string"}}}),
              "change_note": "当前业务服务提供的工具定义"}
    return {"version": "builtin-1", "values": values, "content_sha256": checksum(values), "state": "BUILTIN", "created_at": None}


def current_config(db, domain, identifier, namespace=NAMESPACE):
    active = optional(db, "technical_active", domain + ":" + identifier, namespace)
    if active is None and domain == "tools":
        return builtin_tool(identifier)
    if active is None and domain == "metrics":
        return builtin_metric(identifier)
    return active


def read_configuration(store, db, snapshot, domain):
    drafts = {row["object_id"]: row for row in rows(db, "technical_draft") if row["domain"] == domain}
    identifiers = sorted(OPERATIONS) if domain == "tools" else sorted(METRICS) if domain == "metrics" else ["maintainer-access"]
    items = []
    history = rows(db, "technical_revision")
    for identifier in identifiers:
        active = current_config(db, domain, identifier)
        draft = drafts.get(identifier)
        items.append({"id": identifier, "title": (draft or active)["values"]["name"] if draft or active else "技术维护身份访问",
                      "current": active, "draft": draft,
                      "history": sorted([row for row in history if row["domain"] == domain and row["object_id"] == identifier],
                                        key=lambda row: int(row["version"]), reverse=True)})
        if domain == "metrics":
            effective = effective_configuration(db, NAMESPACE, identifier)
            items[-1]["effective_version"] = effective["version"] if effective else "builtin-1"
            items[-1]["activation_state"] = "EFFECTIVE" if effective and effective["version"] == active["version"] else "SCHEDULED" if active["state"] == "ACTIVE" else "BUILTIN"
    options = {"maintainers": [{"id": "MAINTAINER", "label": "当前技术维护身份"}],
               "object_scopes": _choices(TECHNICAL_SCOPES), "technical_permissions": _choices(["READ", "WRITE"]),
               "operations": _choices(sorted(OPERATIONS)), "connections": _choices(["LOCAL_CONTROL_STORE"]),
               "side_effects": _choices(sorted(set(SIDE_EFFECTS.values()))), "tool_permissions": _choices(sorted(set(PERMISSIONS.values())))}
    if domain == "metrics":
        options.update(metric_options())
    return {"items": items, "options": options, "uses": [row for row in rows(db, "technical_use") if row["domain"] == domain],
            "access": {"owner_id": snapshot["owner_id"], "maintainer_id": "MAINTAINER",
                       "owner_confirmation_state": "OWNER_AUTHORIZATION_REQUIRED", "business_authority_granted": False}}


def _time(value):
    parsed = datetime.fromisoformat(text(value, "配置时间", 80))
    require(parsed.tzinfo is not None, "配置时间必须包含时区", web.HTTPBadRequest)
    return parsed


def _local_schema_references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"}:
                require(isinstance(child, str) and child.startswith("#"), "Schema引用必须指向当前定义", web.HTTPBadRequest)
            _local_schema_references(child)
    elif isinstance(value, list):
        for child in value:
            _local_schema_references(child)


def _validate_values(values, domain):
    require(isinstance(values, dict), "配置内容必须为对象", web.HTTPBadRequest)
    text(values.get("name"), "配置名称", 120)
    text(values.get("change_note"), "变更说明", 2000)
    if domain == "metrics":
        return validate_metric_values(values)
    if domain == "access":
        require(set(values) == {"name", "subject_id", "object_scopes", "permissions", "valid_from", "valid_until", "change_note"},
                "访问配置字段无效", web.HTTPBadRequest)
        require(values["subject_id"] == "MAINTAINER", "配置只能约束当前技术维护身份", web.HTTPForbidden)
        for key, choices in (("object_scopes", TECHNICAL_SCOPES), ("permissions", ("READ", "WRITE"))):
            selected = values[key]
            require(isinstance(selected, list) and bool(selected) and all(isinstance(value, str) and value in choices for value in selected)
                    and len(selected) == len(set(selected)), "技术权限范围无效", web.HTTPBadRequest)
        require("READ" in values["permissions"], "技术访问需要包含读取权限", web.HTTPBadRequest)
        require(_time(values["valid_from"]) < _time(values["valid_until"]), "有效期限需要晚于开始时间", web.HTTPBadRequest)
    else:
        operation = values.get("operation_id")
        require(isinstance(operation, str) and operation in OPERATIONS, "工具接口不存在", web.HTTPBadRequest)
        require(set(values) == set(builtin_tool(operation)["values"]), "工具配置字段无效", web.HTTPBadRequest)
        require(values["name"] == operation and values["connection_id"] == "LOCAL_CONTROL_STORE", "工具需要关联已注册的本地业务接口", web.HTTPBadRequest)
        text(values["description"], "工具说明", 4000)
        require(values["side_effect"] == SIDE_EFFECTS[operation] and values["permission"] == PERMISSIONS[operation],
                "工具副作用及授权必须符合业务接口", web.HTTPForbidden)
        require(type(values["timeout_seconds"]) is int and 1 <= values["timeout_seconds"] <= 300, "工具超时范围无效", web.HTTPBadRequest)
        require(values["idempotency_field"] == builtin_tool(operation)["values"]["idempotency_field"], "幂等字段需要采用业务接口定义", web.HTTPBadRequest)
        for key in ("input_schema", "output_schema", "error_schema"):
            schema = json.loads(text(values[key], key, 200000))
            require(isinstance(schema, dict), "Schema必须为JSON对象", web.HTTPBadRequest)
            _local_schema_references(schema)
            Draft202012Validator.check_schema(schema)
        input_schema = json.loads(values["input_schema"])
        require(set(input_schema) == set(operation_schema(operation, "input"))
                and input_schema["$ref"] == operation_schema(operation, "input")["$ref"],
                "输入Schema需要保留当前接口根引用和定义结构", web.HTTPBadRequest)
    return values


def mutate_configuration(api, db, snapshot, domain, action, payload):
    if action == "save":
        api._exact(payload, {"client_request_id", "object_id", "expected_version", "values"})
        values = _validate_values(payload["values"], domain)
        identifier = "maintainer-access" if domain == "access" else values["metric_id"] if domain == "metrics" else values["operation_id"]
        require(payload["object_id"] in (None, identifier), "配置对象与内容不一致", web.HTTPBadRequest)
        key = domain + ":" + identifier
        previous = optional(db, "technical_draft", key)
        require(payload["expected_version"] == (previous["version"] if previous else "0"), "配置草稿版本已经变化")
        version = str(int(previous["version"]) + 1) if previous else "1"
        if previous:
            api.store.put(db, NAMESPACE, "technical_revision", key + ":" + previous["version"], previous)
        draft = {"domain": domain, "object_id": identifier, "version": version, "values": values,
                 "content_sha256": checksum(values), "state": "DRAFT", "created_at": now()}
        api.store.put(db, NAMESPACE, "technical_draft", key, draft)
        return {"object_id": identifier, "version": version, "state": "DRAFT"}
    api._exact(payload, {"client_request_id", "object_id", "expected_version", "expected_content_sha256", "expected_active_version"})
    identifier = text(payload["object_id"], "配置对象", 128)
    key = domain + ":" + identifier
    draft = api.store.get(db, NAMESPACE, "technical_draft", key)
    active = current_config(db, domain, identifier)
    require(draft["version"] == payload["expected_version"] and draft["content_sha256"] == payload["expected_content_sha256"], "配置内容或版本已经变化")
    require((active["version"] if active else "0") == payload["expected_active_version"], "当前启用版本已经变化")
    _validate_values(draft["values"], domain)
    if action == "validate":
        require(draft["state"] == "DRAFT", "只有已保存的草稿可以校验")
        draft["validation"] = {"state": "PASSED", "checked_at": now(), "checks": [
            {"name": "字段与业务权限", "state": "PASSED", "message": "配置符合当前身份、业务接口和Schema范围"},
        ]}
        if domain == "metrics":
            source = api.store._metric_source(db, NAMESPACE, snapshot)
            draft["validation"] = recompute(snapshot, draft["values"])
            draft["validation"]["source_sha256"] = checksum(source)
        draft["state"] = "VALIDATED"
    else:
        require(action == "activate" and draft["state"] == "VALIDATED", "只能启用已经校验的草稿")
        require(not any(row["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT"} and row.get("finished_at") is None for row in rows(db, "runtime_run")),
                "当前仍有进行中的运行，配置暂不能启用")
        if domain == "access":
            require(_time(draft["values"]["valid_until"]) > datetime.now(timezone.utc), "访问配置已经到期")
        if domain == "metrics":
            require(draft["validation"]["input_sha256"] == checksum(snapshot["details"]), "指标复算资料已经变化，请重新保存并校验")
            require(draft["validation"]["source_sha256"] == checksum(api.store._metric_source(db, NAMESPACE, snapshot)),
                    "指标复算来源已经变化，请重新保存并校验")
        draft.update(state="ACTIVE", activated_at=now())
        api.store.put(db, NAMESPACE, "technical_active", key, draft)
    api.store.put(db, NAMESPACE, "technical_draft", key, draft)
    api.store.put(db, NAMESPACE, "technical_revision", key + ":" + draft["version"], draft)
    return {"object_id": identifier, "version": draft["version"], "state": draft["state"]}


def record_use(store, db, domain, identifier, version, run_id, namespace=NAMESPACE, details=None):
    identifier_key = checksum({"domain": domain, "object_id": identifier, "version": version, "run_id": run_id})
    store.put(db, namespace, "technical_use", identifier_key, {"id": identifier_key, "domain": domain, "object_id": identifier,
              "version": version, "run_id": run_id, "state": "ADOPTED", "at": now(), **({"details": details} if details is not None else {})})


def check_technical_access(db, domain, permission):
    if domain == "access":
        return None
    require(domain in TECHNICAL_SCOPES, "技术资料范围无效", web.HTTPForbidden)
    active = current_config(db, "access", "maintainer-access")
    if active is None:
        return None
    values = active["values"]
    at = datetime.now(timezone.utc)
    require(_time(values["valid_from"]) <= at < _time(values["valid_until"]), "技术访问配置尚未生效或已经到期", web.HTTPForbidden)
    require(domain in values["object_scopes"] and permission in values["permissions"], "当前配置未授予该技术范围", web.HTTPForbidden)
    return active


def authorize_technical(store, domain, permission):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.active(db, NAMESPACE)
        active = check_technical_access(db, domain, permission)
        if active is not None:
            record_use(store, db, "access", "maintainer-access", active["version"], permission + ":" + domain + ":" + now())


def technical_scope(target):
    for prefix, domain in (("boss.knowledge.", "knowledge"), ("boss.prompt.", "prompts"), ("boss.scheduler.", "scheduler"),
                           ("boss.sop.", "skills"), ("boss.runtime.", "models"), ("boss.simulation.", "simulation")):
        if target.startswith(prefix):
            return domain
    suffix = target.rsplit("/", 1)[-1]
    aliases = {"dataset": "datasets", "source-index": "knowledge", "tool-catalog": "tools", "metric-definitions": "metrics",
               "prompt-versions": "prompts", "runtime-configuration": "models", "model-health": "models", "model-usage": "models",
               "runtime-records": "audit", "system": "local-system", "maintenance": "local-system", "sop-method": "skills",
               "sop-history": "skills", "sop-operation-status": "skills", "simulation-query": "simulation", "simulation-inspect": "simulation",
               "morning-coverage": "simulation", "morning-coverage-receipt": "simulation", "bi-scenarios": "simulation",
               "bi-scenario-receipt": "simulation", "business-alert-input": "simulation", "approval-admin": "simulation", "message-admin": "simulation"}
    return aliases.get(suffix, suffix if suffix in TECHNICAL_SCOPES else None)


def tool_policy(db, operation, namespace):
    active = current_config(db, "tools", operation, namespace)
    return active if active["state"] == "ACTIVE" else None


def validate_tool_value(policy, direction, value):
    if policy is not None:
        schema = json.loads(policy["values"][direction + "_schema"])
        errors = list(Draft202012Validator(schema).iter_errors(value))
        require(not errors, "工具" + direction + "不符合已启用Schema", web.HTTPBadRequest)
