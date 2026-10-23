import json
from datetime import datetime, timezone

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import now, require

QUERY = {
    "type": "object", "additionalProperties": False,
    "properties": {
        **{key: {"type": "string", "minLength": 1, "maxLength": 128}
           for key in ("provider", "run_id", "dataset_id", "stop_reason", "cursor_run_id")},
        "status": {"enum": ["QUEUED", "RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED", "CANCELED", "TIMED_OUT"]},
        **{key: {"type": "string", "format": "date-time"}
           for key in ("started_from", "started_until", "cursor_started_at")},
        "limit": {"type": "string", "pattern": "^(?:[1-9][0-9]?|100)$"},
    },
    "dependentRequired": {"cursor_run_id": ["cursor_started_at"], "cursor_started_at": ["cursor_run_id"]},
}


def read_runtime_records(store, role, namespace, run_id=None, query=None):
    require(role is not None, "需要认证身份", web.HTTPUnauthorized)
    require(role in {"BOSS", "MAINTAINER"}, "运行记录访问被拒绝", web.HTTPForbidden)
    parameters = {} if query is None else query
    errors = list(Draft202012Validator(QUERY, format_checker=FormatChecker()).iter_errors(parameters))
    require(not errors, "运行记录查询字段无效", web.HTTPBadRequest)
    require(run_id is None or isinstance(run_id, str) and 1 <= len(run_id) <= 128,
            "运行标识格式无效", web.HTTPBadRequest)
    require(run_id is None or not parameters, "单项读取与列表查询不能同时指定", web.HTTPBadRequest)
    timestamps = {key: datetime.fromisoformat(parameters[key].upper()).astimezone(timezone.utc).isoformat()
                  for key in ("started_from", "started_until", "cursor_started_at") if key in parameters}
    require(not {"started_from", "started_until"} <= set(timestamps)
            or timestamps["started_from"] <= timestamps["started_until"], "真实时间范围无效", web.HTTPBadRequest)
    limit = int(parameters.get("limit", "50"))
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db, namespace)
        if run_id is not None:
            rows = [store.get(db, namespace, "runtime_run", run_id)]
            total = 1
            cursor = None
        else:
            conditions = ["namespace=?", "kind='runtime_run'"]
            values = [namespace]
            for parameter, field in (("provider", "runtime.provider"), ("run_id", "run_id"),
                                     ("dataset_id", "dataset_id"), ("status", "status"), ("stop_reason", "stop_reason")):
                if parameter in parameters:
                    conditions.append("json_extract(body,'$." + field + "')=?")
                    values.append(parameters[parameter])
            for parameter, operator in (("started_from", ">="), ("started_until", "<=")):
                if parameter in timestamps:
                    conditions.append("json_extract(body,'$.started_at')" + operator + "?")
                    values.append(timestamps[parameter])
            total = db.execute("SELECT COUNT(*) FROM objects WHERE " + " AND ".join(conditions), values).fetchone()[0]
            if "cursor_started_at" in timestamps:
                conditions.append("(json_extract(body,'$.started_at')<? OR (json_extract(body,'$.started_at')=? AND id<?))")
                values.extend((timestamps["cursor_started_at"], timestamps["cursor_started_at"], parameters["cursor_run_id"]))
            found = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM objects WHERE " + " AND ".join(conditions)
                + " ORDER BY json_extract(body,'$.started_at') DESC,id DESC LIMIT ?", [*values, limit + 1],
            )]
            rows = found[:limit]
            cursor = ({"cursor_started_at": rows[-1]["started_at"], "cursor_run_id": rows[-1]["run_id"]}
                      if len(found) > limit else None)
        return {
            "projection": "runtime-records", "source_type": "RUNTIME_RECORD", "namespace": namespace,
            "read_at": now(), "runs": rows, "matched_count": total, "limit": limit, "next_cursor": cursor,
            "private_body_available_here": False, "business_mutation_performed": False,
        }
