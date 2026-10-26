import json
from urllib.parse import parse_qs

from aiohttp import web

from business import now, require
from boss_v7_store import NAMESPACE, optional, role_required, rows

ACTIVE = {"QUEUED", "RUNNING", "WAITING_INPUT"}


def read_runs(store, db, snapshot):
    result = []
    for run in rows(db, "runtime_run"):
        require(run["namespace"] == NAMESPACE and run["dataset_id"] == snapshot["dataset_id"], "运行所属资料不符", web.HTTPForbidden)
        links = run.get("owner_task_links", []) + run["tool_results"]
        task_ids = list(dict.fromkeys(row["task_id"] for row in links if row.get("task_id")))
        tasks = [optional(db, "task", identifier) for identifier in task_ids]
        tasks = [row for row in tasks if row is not None]
        task = tasks[0] if len(tasks) == 1 else None
        steps = []
        sources = set()
        artifacts = []
        for item in run["tool_results"]:
            safe = {key: item[key] for key in ("query_id", "task_id", "message_id", "list_id", "draft_id", "version", "task_version", "status", "authorization_id", "result_sha256") if key in item}
            steps.append({"id": item["tool_call_id"], "title": item["tool_id"], "state": item.get("status", "RESULT_RECORDED"),
                          "tool_name": item["tool_id"], "input": json.dumps({"parameters_sha256": item["parameters_sha256"]}, ensure_ascii=False) if item.get("parameters_sha256") else None,
                          "output": json.dumps(safe, ensure_ascii=False, indent=2), "error": None,
                          "started_at": item.get("started_at"), "ended_at": item.get("ended_at")})
            for reference in item.get("source_refs", []):
                if isinstance(reference, dict) and reference.get("source_id"):
                    sources.add(reference["source_id"])
            if item.get("source_id"):
                sources.add(item["source_id"])
            for field, kind in (("query_id", "query"), ("task_id", "task"), ("list_id", "morning_list"), ("draft_id", "message_draft")):
                if item.get(field) and optional(db, kind, item[field]):
                    artifacts.append({"id": kind + ":" + item[field], "title": item[field], "source_id": None,
                                      "task_id": item[field] if kind == "task" else None, "state": "SAVED"})
        for item in run.get("tool_errors", []):
            steps.append({"id": item["tool_call_id"] + ":error", "title": item["tool_id"], "state": "FAILED",
                          "tool_name": item["tool_id"], "input": None, "output": None, "error": item["error_type"],
                          "started_at": item.get("started_at"), "ended_at": item.get("ended_at")})
        usage = []
        for item in run["model_requests"]:
            reported = item.get("usage")
            if reported is None:
                usage.append({"id": item["model_request_id"], "resource": "模型请求", "quantity": None, "unit": "Token",
                              "cache": None, "pricing_date": None, "cost": None, "currency": None, "state": "USAGE_NOT_PROVIDED"})
                continue
            for key, label in (("prompt_tokens", "输入"), ("completion_tokens", "输出")):
                usage.append({"id": item["model_request_id"] + ":" + key, "resource": label, "quantity": str(reported[key]) if reported.get(key) is not None else None,
                              "unit": "Token", "cache": str(reported["prompt_cache_hit_tokens"]) if key == "prompt_tokens" and reported.get("prompt_cache_hit_tokens") is not None else None,
                              "pricing_date": item.get("pricing_date"), "cost": item.get("costs", {}).get(key), "currency": item.get("currency"),
                              "state": "RECORDED" if item.get("costs", {}).get(key) is not None else "PRICE_NOT_PROVIDED"})
        context = run.get("conversation_context", {})
        missing = context.get("required_inputs", [])
        missing = [row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in missing]
        result.append({"id": run["run_id"], "task_id": task["task_id"] if task else None,
                       "task_version": task["version"] if task else None,
                       "goal": task.get("purpose", task["task_id"]) if task else run.get("goal", run["feature_id"] if "feature_id" in run else run["run_id"]),
                       "state": "CANCEL_REQUESTED" if run.get("cancel_request") and run["status"] in ACTIVE else run["status"],
                       "started_at": run["started_at"], "ended_at": run["finished_at"], "provider": run["runtime"]["provider"],
                       "model_id": run["runtime"]["model_id"], "waiting_inputs": missing, "termination_reason": run["stop_reason"],
                       "can_cancel": run["status"] in ACTIVE and not run.get("cancel_request"),
                       "request_id": run.get("cancel_request", {}).get("request_id"),
                       "action": "boss.owner_workspace.runs.cancel" if run.get("cancel_request") else None,
                       "steps": steps, "usage": usage,
                       "artifacts": list({row["id"]: row for row in artifacts}.values()), "source_ids": sorted(sources)})
    return sorted(result, key=lambda row: row["started_at"], reverse=True)


def cancel_run(api, db, snapshot, payload):
    api._exact(payload, {"client_request_id", "run_id", "expected_state", "confirmation"})
    require(payload["confirmation"] is True, "取消运行需要本人确认", web.HTTPForbidden)
    run = api.store.get(db, NAMESPACE, "runtime_run", payload["run_id"])
    require(run["dataset_id"] == snapshot["dataset_id"] and run["namespace"] == NAMESPACE, "运行所属资料不符", web.HTTPForbidden)
    require(run["status"] == payload["expected_state"] and run["status"] in ACTIVE, "当前运行状态已经变化")
    require(not run.get("cancel_request"), "已经存在取消请求，请查询原结果")
    authorization = api._authorize(db, "runtime.cancel", {"run_id": run["run_id"], "expected_state": run["status"]}, run["run_id"], run["configuration_version"])
    run["cancel_request"] = {"request_id": payload["client_request_id"], "authorization_id": authorization, "requested_at": now()}
    api.store.put(db, NAMESPACE, "runtime_run", run["run_id"], run)
    return {"run_id": run["run_id"], "state": "CANCEL_REQUESTED", "authorization_id": authorization}


def task_exceptions(store, role, query):
    role_required(role, "BOSS")
    parameters = parse_qs(query, keep_blank_values=True)
    require(set(parameters) <= {"task_id"} and all(len(values) == 1 and values[0] for values in parameters.values()), "异常查询参数无效", web.HTTPBadRequest)
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db, NAMESPACE)
        snapshot = store.get(db, NAMESPACE, "initial", "snapshot")
        records = read_runs(store, db, snapshot)
        issues = []
        for run in records:
            if run["state"] not in {"FAILED", "TIMED_OUT", "WAITING_INPUT", "CANCELED", "CANCEL_REQUESTED"}:
                continue
            if parameters and run["task_id"] != parameters["task_id"][0]:
                continue
            task = optional(db, "task", run["task_id"]) if run["task_id"] else None
            issues.append({"id": run["id"], "task_id": run["task_id"], "run_id": run["id"], "request_id": run["request_id"],
                           "action": run["action"], "state": run["state"], "title": run["goal"],
                           "reason": run["termination_reason"] or run["state"],
                           "executed": [{"id": row["id"], "state": row["state"], "description": row["title"]} for row in run["steps"]],
                           "remaining": [], "missing": run["waiting_inputs"], "source_ids": run["source_ids"],
                           "current_business_state": task["status"] if task else "NO_LINKED_TASK",
                           "can_cancel": run["can_cancel"], "created_at": run["started_at"]})
        return {"projection": "task-exceptions", "source_type": "RUNTIME_RECORD", "issues": issues, "read_at": now()}
