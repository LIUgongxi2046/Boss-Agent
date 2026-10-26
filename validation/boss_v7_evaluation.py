# A16/F31 评测：使用当前获准模拟数据执行断言，不调用外部模型。
# 每次尝试保留可读状态，断言结果与证据来自实际读取。
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from time import monotonic

from aiohttp import web

from business import now, require
from boss_metrics import aggregate_metrics
from boss_source_policy import source_validity
from boss_v7_store import NAMESPACE

SKILLS = Path(__file__).resolve().parents[1] / "agent/skills"


def _task_set(identifier, version, variant, title, summary, requirements, assertions, conditions, scoring):
    return {"id": identifier, "version": version, "variant": variant, "title": title,
            "input_summary": summary, "authorization_requirements": requirements,
            "assertion_definitions": assertions, "pairing_conditions": conditions,
            "scoring_access": scoring}


TASK_SETS = [
    _task_set("selection-core", "1", "CORE", "核心经营核对",
              "当前获准模拟数据集的经营明细、会议来源与本人记忆。",
              ["仅读取当前执行空间的获准模拟资料", "不修改任务、消息、审批或本人决定"],
              [{"id": "EVAL-METRIC-GROSS-MARGIN", "title": "毛利率计算与原始明细一致", "requirement_refs": ["FR-03", "AC-03-S"]},
               {"id": "EVAL-SOURCE-VALIDITY", "title": "会议材料在业务时钟下有效且属于本人", "requirement_refs": ["FR-04", "FR-05"]},
               {"id": "EVAL-MEMORY-CONFIRMATION", "title": "本人记忆保持已确认版本", "requirement_refs": ["FR-13"]},
               {"id": "EVAL-READ-ONLY", "title": "评测不写业务对象", "requirement_refs": ["AC-03-E"]}],
              ["人工核查独立初始资料", "人工核查运行顺序", "人工确认适合当前熟悉程度", "人工确认有效授权"],
              "评分与断言结果只由维护身份读取，不进入 Agent 上下文"),
    _task_set("selection-evidence", "1", "EVIDENCE", "来源与资料核对",
              "当前模拟资料的所有来源、版本与本人可见范围。",
              ["仅读取当前执行空间的获准模拟资料", "不重新导入、撤销或改写来源"],
              [{"id": "EVAL-DOCUMENT-VERSIONS", "title": "全部来源具有稳定版本与本人范围", "requirement_refs": ["FR-04", "FR-09"]},
               {"id": "EVAL-SNAPSHOT-SUMMARY", "title": "数据集摘要与当前明细一致", "requirement_refs": ["FR-25", "AC-03-S"]}],
              ["人工核查独立初始资料", "人工核查运行顺序", "人工确认适合当前熟悉程度", "人工确认有效授权"],
              "评分与断言结果只由维护身份读取，不进入 Agent 上下文"),
]
TASK_SETS_BY_ID = {item["id"]: item for item in TASK_SETS}


def _choice(identifier, title, version):
    return {"id": identifier, "title": title, "version": str(version)}


def _sop_choices():
    choices = []
    for path in sorted(SKILLS.glob("boss-sop*/SKILL.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        matched = re.search(r"sop_id:\s*(SOP\d+),\s*version:\s*([0-9.]+)", text)
        if matched:
            choices.append(_choice(matched.group(1), matched.group(1), matched.group(2)))
    return choices or [_choice("builtin-sop", "内置 SOP 方法", "builtin-1")]


def _prompt_choices(db):
    choices = []
    for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='prompt_active' ORDER BY id",
                          (NAMESPACE,)).fetchall():
        active = json.loads(row[0])
        if active.get("enabled"):
            choices.append(_choice(active["prompt_id"], "Prompt · " + str(active.get("kind", "")),
                                   active.get("prompt_version", "unknown")))
    return choices or [_choice("builtin-runtime", "内置运行时提示", "builtin-1")]


def catalogs(store, db, snapshot):
    configuration = store.get(db, NAMESPACE, "configuration", "current")
    return {
        "snapshots": [_choice(snapshot["dataset_id"], "获准模拟数据集", snapshot["dataset_version"])],
        "models": [_choice("model-current", configuration.get("model_id", "unknown"), configuration.get("version", "unknown"))],
        "prompts": _prompt_choices(db),
        "sops": _sop_choices(),
    }


def _summary(store, db, snapshot):
    clock = store.get(db, NAMESPACE, "clock", "current")["at"]
    meeting = snapshot["meeting"]
    documents = []
    for source_id in meeting["material_ids"]:
        if source_id == snapshot["event"]["event_id"]:
            continue
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?",
                         (NAMESPACE, source_id)).fetchone()
        documents.append((source_id, json.loads(row[0]) if row else None))
    return clock, documents


def _counts(db):
    kinds = ("task", "message", "outbox", "notification", "authorization", "application",
             "feedback", "minutes", "travel_plan", "owner_plan")
    marks = ",".join("?" for _ in kinds)
    return dict(db.execute("SELECT kind,COUNT(*) FROM objects WHERE namespace=? AND kind IN (%s) GROUP BY kind" % marks,
                           (NAMESPACE, *kinds)).fetchall())


def _assert_metric(store, db, snapshot):
    details = [row for row in snapshot["details"] if row["period"] == "CURRENT"]
    with localcontext() as context:
        context.prec = 80
        aggregated = aggregate_metrics(details)
        revenue = sum((Decimal(row["revenue_cny"]) for row in details), Decimal(0))
        cost = sum((Decimal(row["cost_cny"]) for row in details), Decimal(0))
        profit = revenue - cost
        margin = (profit / revenue * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        observed_margin = Decimal(aggregated["metrics"]["gross_margin"][0]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    observed = {"gross_profit": str(aggregated["metrics"]["gross_profit"][0]),
                "gross_margin": str(observed_margin),
                "revenue": str(aggregated["metrics"]["revenue"][0])}
    expected = {"gross_profit": str(profit), "gross_margin": str(margin), "revenue": str(revenue)}
    passed = observed == expected
    return passed, expected, observed


def _assert_sources(store, db, snapshot):
    clock, documents = _summary(store, db, snapshot)
    observed = []
    for source_id, document in documents:
        if document is None:
            observed.append({"source_id": source_id, "state": "MISSING"})
            continue
        state = source_validity(document, clock)
        observed.append({"source_id": source_id, "state": state,
                         "version": document.get("version"),
                         "owner_scope": document.get("access_scope") == snapshot["owner_id"],
                         "source_type": document.get("source_type")})
    passed = all(item["state"] == "VALID" and item["owner_scope"] and item["source_type"] == "SIMULATED"
                 for item in observed)
    return passed, {"all_valid": True, "clock": clock}, {"sources": observed, "clock": clock}


def _assert_memory(store, db, snapshot):
    memory = store.get(db, NAMESPACE, "memory", "current")
    initial = snapshot["memory"]
    observed = {"state": memory.get("confirmation_state"), "version": memory.get("version"),
                "text_matches_initial": memory.get("text") == initial.get("text")}
    passed = observed["state"] == "CONFIRMED" and observed["text_matches_initial"]
    return passed, {"state": "CONFIRMED", "text_matches_initial": True}, observed


def _assert_versions(snapshot):
    observed = [{"source_id": row["source_id"], "version": row.get("version")}
                for row in snapshot.get("documents", [])]
    passed = bool(observed) and all(item["version"] for item in observed)
    return passed, {"versioned_documents": True}, {"documents": observed}


def _assert_snapshot_summary(snapshot):
    details = snapshot["details"]
    expected_keys = {"record_id", "period", "quantity_tonnes", "revenue_cny", "cost_cny"}
    observed = {"count": len(details), "keys_complete": all(expected_keys <= set(row) for row in details),
                "periods": sorted({row["period"] for row in details})}
    passed = observed["periods"] == ["BASE", "CURRENT"] and observed["keys_complete"]
    return passed, {"periods": ["BASE", "CURRENT"], "keys_complete": True}, observed


def _run(store, db, snapshot, task):
    before = _counts(db)
    clock, _ = _summary(store, db, snapshot)
    assertions, evidence = [], []
    index = 0
    for definition in task["assertion_definitions"]:
        index += 1
        try:
            if definition["id"] == "EVAL-METRIC-GROSS-MARGIN":
                passed, expected, observed = _assert_metric(store, db, snapshot)
            elif definition["id"] == "EVAL-SOURCE-VALIDITY":
                passed, expected, observed = _assert_sources(store, db, snapshot)
            elif definition["id"] == "EVAL-MEMORY-CONFIRMATION":
                passed, expected, observed = _assert_memory(store, db, snapshot)
            elif definition["id"] == "EVAL-DOCUMENT-VERSIONS":
                passed, expected, observed = _assert_versions(snapshot)
            elif definition["id"] == "EVAL-SNAPSHOT-SUMMARY":
                passed, expected, observed = _assert_snapshot_summary(snapshot)
            elif definition["id"] == "EVAL-READ-ONLY":
                after = _counts(db)
                passed = after == before
                expected = before
                observed = after
            else:
                raise ValueError("未知断言定义")
        except Exception as error:  # 数据异常记为失败证据，不伪造通过
            passed, expected, observed = False, {"available": True}, {"error": type(error).__name__ + ": " + str(error)}
        evidence_id = "evidence-" + str(index) + "-" + str(uuid.uuid4())[:8]
        evidence.append({"id": evidence_id, "kind": "OBSERVATION",
                         "content": {"assertion_id": definition["id"], "expected": expected,
                                     "observed": observed, "clock": clock}})
        assertions.append({"id": definition["id"], "title": definition["title"],
                           "state": "PASSED" if passed else "FAILED",
                           "expected": expected, "observed": observed,
                           "evidence_ids": [evidence_id],
                           "requirement_refs": definition["requirement_refs"]})
    return assertions, evidence


def start(api, db, snapshot, payload, reset=False):
    required = {"client_request_id", "task_set_id", "dataset_snapshot_id", "model_version",
                "prompt_version", "sop_version", "expected_versions", "pairing_conditions_confirmed"}
    require(set(payload) == required, "评测启动字段不完整", web.HTTPBadRequest)
    require(payload["pairing_conditions_confirmed"] is True, "需要人工确认配对条件", web.HTTPBadRequest)
    task = TASK_SETS_BY_ID.get(payload["task_set_id"])
    require(task is not None, "评测任务集不存在", web.HTTPNotFound)
    categories = catalogs(api.store, db, snapshot)
    resolved = {
        "task_set_id": _choice(task["id"], task["title"], task["version"]),
        "dataset_snapshot_id": next((row for row in categories["snapshots"] if row["id"] == payload["dataset_snapshot_id"]), None),
        "model_version": next((row for row in categories["models"] if row["id"] == payload["model_version"]), None),
        "prompt_version": next((row for row in categories["prompts"] if row["id"] == payload["prompt_version"]), None),
        "sop_version": next((row for row in categories["sops"] if row["id"] == payload["sop_version"]), None),
    }
    require(all(resolved.values()), "所选版本不在当前目录", web.HTTPConflict)
    require(payload["expected_versions"] == {key: choice["version"] for key, choice in resolved.items()},
            "所选版本已经变化，请重新核查", web.HTTPConflict)
    attempt_id = "eval-" + str(uuid.uuid4())
    started_at = now()
    started = monotonic()
    assertions, evidence = _run(api.store, db, snapshot, task)
    finished = monotonic() - started
    failed = [item["id"] + " · " + item["title"] for item in assertions if item["state"] == "FAILED"]
    attempt = {
        "id": attempt_id, "task_set_id": task["id"], "task_set_version": task["version"],
        "variant": task["variant"], "dataset_snapshot_id": payload["dataset_snapshot_id"],
        "model_version": payload["model_version"], "prompt_version": payload["prompt_version"],
        "sop_version": payload["sop_version"], "namespace": NAMESPACE,
        "state": "FAILED" if failed else "PASSED", "started_at": started_at,
        "finished_at": now(), "assertions": assertions, "run_ids": [],
        "elapsed_seconds": round(finished, 3), "known_cost": None, "total_cost": None,
        "currency": None, "usage_coverage": "NO_MODEL_REQUESTS", "failures": failed,
        "selection_versions": payload["expected_versions"], "reset": reset,
        "source_type": "SIMULATED", "evidence": evidence,
    }
    for row in evidence:
        row["attempt_id"] = attempt_id
    api.store.put(db, NAMESPACE, "evaluation_attempt", attempt_id, attempt)
    return {"source_type": "SIMULATED", "attempt_id": attempt_id, "state": attempt["state"],
            "task_set_id": task["id"], "task_set_version": task["version"],
            "assertion_states": {item["id"]: item["state"] for item in assertions},
            "failures": failed, "reset": reset, "namespace": NAMESPACE}


def cancel(api, db, payload):
    require(set(payload) == {"client_request_id", "attempt_id", "expected_state", "expected_namespace"},
            "取消字段不完整", web.HTTPBadRequest)
    attempt = api.store.get(db, NAMESPACE, "evaluation_attempt", payload["attempt_id"])
    require(attempt["namespace"] == payload["expected_namespace"] == NAMESPACE, "执行空间不一致", web.HTTPConflict)
    require(attempt["state"] == payload["expected_state"], "尝试状态已经变化", web.HTTPConflict)
    require(attempt["state"] in ("QUEUED", "RUNNING", "WAITING_INPUT"), "已经结束的尝试不能取消", web.HTTPConflict)
    attempt["state"] = "CANCELED"
    attempt["finished_at"] = now()
    api.store.put(db, NAMESPACE, "evaluation_attempt", attempt["id"], attempt)
    return {"source_type": "SIMULATED", "attempt_id": attempt["id"], "state": "CANCELED"}


def read_evaluation(store, db, snapshot):
    categories = catalogs(store, db, snapshot)
    attempts = []
    evidence = []
    for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='evaluation_attempt' ORDER BY id",
                          (NAMESPACE,)).fetchall():
        attempt = json.loads(row[0])
        evidence.extend(attempt.pop("evidence", []))
        attempts.append(attempt)
    attempts.sort(key=lambda item: item["started_at"], reverse=True)
    return {"task_sets": TASK_SETS, **categories, "attempts": attempts, "evidence": evidence,
            "real_adoption_state": "EVALUATION_ONLY_NOT_RUNTIME_ADOPTION"}
