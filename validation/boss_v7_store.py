import json
from datetime import datetime

from aiohttp import web

from business import encode, now, require

from boss_execution_scope import NAMESPACE


def rows(db, kind, namespace=NAMESPACE):
    return [json.loads(row[0]) for row in db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (namespace, kind)
    ).fetchall()]


def optional(db, kind, identifier, namespace=NAMESPACE):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
                     (namespace, kind, identifier)).fetchone()
    return json.loads(row[0]) if row else None


def text(value, label, maximum=4000):
    require(isinstance(value, str) and 0 < len(value.strip()) <= maximum,
            label + "内容无效", web.HTTPBadRequest)
    return value.strip()


def aware_time(value):
    result = datetime.fromisoformat(text(value, "时间", 80))
    require(result.tzinfo is not None, "时间需要包含时区", web.HTTPBadRequest)
    return result


def role_required(role, expected):
    require(role in {"BOSS", "MAINTAINER"}, "需要认证身份", web.HTTPUnauthorized)
    require(role == expected, "当前身份无权访问", web.HTTPForbidden)


def read_receipt(store, role, expected_role, prefix, domain, request_id):
    role_required(role, expected_role)
    text(request_id, "原请求编号", 128)
    with store.connect() as db:
        store.active(db, NAMESPACE)
        operation_prefix = prefix + domain + "."
        receipt_namespace = "dataset-catalog" if operation_prefix == "boss.technical.datasets." else NAMESPACE
        found = db.execute(
            "SELECT operation,result FROM idempotency WHERE namespace=? AND key=? AND substr(operation,1,?)=?",
            (receipt_namespace, request_id, len(operation_prefix), operation_prefix),
        ).fetchall()
        require(len(found) <= 1, "原请求编号存在多个操作记录")
        require(bool(found), "原请求尚无已提交回执", web.HTTPNotFound)
        receipt = json.loads(found[0][1])
        if operation_prefix == "boss.technical.datasets.":
            from boss_execution_transition import transition_status
            transition = transition_status(db, request_id)
            if transition is not None:
                receipt["transition"] = transition
        return receipt


def execute_transaction(api, role, expected_role, command, payload, mutate):
    role_required(role, expected_role)
    with api.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        api.store.active(db, NAMESPACE)
        if expected_role == "MAINTAINER":
            from boss_v7_configuration import check_technical_access
            check_technical_access(db, command.removeprefix("boss.technical.").split(".")[0], "WRITE")
        receipt_namespace = "dataset-catalog" if command.startswith("boss.technical.datasets.") else NAMESPACE
        key, digest, previous = api._check_existing(db, command, payload, namespace=receipt_namespace)
        if previous is not None:
            return previous
        prefix = command.rsplit(".", 1)[0] + "."
        other = db.execute("SELECT operation FROM idempotency WHERE namespace=? AND key=? AND substr(operation,1,?)=?",
                           (receipt_namespace, key, len(prefix), prefix)).fetchone()
        require(other is None, "原请求编号已经用于当前页面的其他操作")
        snapshot = api.store.get(db, NAMESPACE, "initial", "snapshot")
        result = mutate(db, snapshot)
        receipt = {"request_id": key, "action": command.rsplit(".", 1)[-1], "state": "RECORDED", "result": result}
        db.execute("INSERT INTO idempotency VALUES(?,?,?,?,?)", (receipt_namespace, command, key, digest, encode(receipt)))
        audit_input = {"client_request_id": key, "action": command, "role": role}
        audit_output = {field: result[field] for field in (
            "object_id", "memory_id", "authorization_id", "run_id", "task_id", "message_id", "source_id", "version", "state", "status",
        ) if field in result}
        db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)",
                   (NAMESPACE, command, encode(audit_input), encode(audit_output), now()))
        return receipt
