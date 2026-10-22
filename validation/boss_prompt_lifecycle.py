"""AD05: actual versioned maintenance Prompt lifecycle and runtime adoption.

Scope is a fixed demo namespace. This is configurable *guidance* only:
maintainer cannot alter BOSS-only tools, identities, authorization policy,
model, provider, or private memory by saving a prompt. SQLite remains source
of truth and every mutation runs within BossCommandAPI's existing tx.
"""
from __future__ import annotations

import json
import re

from aiohttp import web
from business import checksum, now, require

NS = "ui-check"
TYPES = {
    "SECRETARY_ROLE": "秘书职责",
    "EXPRESSION": "表达要求",
    "TASK_GUIDANCE": "任务提示",
}
_ALLOWED_TASKS = {"ALL_BOSS_READS", "MEETING_PREPARATION", "RESEARCH_READING"}
_AUTHORITY_LIMITS = (
    "Maintainer prompt is advisory and has no authority to approve, send, "
    "complete tasks, read private data, change tools, or modify owner consent."
)


def _one(db,kind,ident):
    row=db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
        (NS,kind,ident),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _request(api,payload,required):
    api._exact(payload, required)


def _require_prompt_type(raw):
    require(isinstance(raw,str) and raw in TYPES,
            "Prompt 分类不在固定维护范围内",web.HTTPBadRequest)
    return raw


def draft_save(api,db,data,payload):
    _request(api,payload,{
        "client_request_id","prompt_type","expected_version",
        "content","task_scope","change_reason",
    })
    kind=_require_prompt_type(payload["prompt_type"])
    text=payload["content"]
    reason=payload["change_reason"]
    require(isinstance(text,str) and 8<=len(text.strip())<=4000,
            "Prompt 正文须为8—4000字",web.HTTPBadRequest)
    require(isinstance(reason,str) and 4<=len(reason.strip())<=300,
            "需要填写具体变更理由",web.HTTPBadRequest)
    require(payload["task_scope"] in _ALLOWED_TASKS,
            "不能增加未获准的新任务类型",web.HTTPBadRequest)
    last=_one(db,"prompt_head",kind)
    old_ver=last["version"] if last else "0"
    require(payload["expected_version"]==old_ver,"Prompt 编辑版本冲突")
    version=str(int(old_ver)+1)
    item={
        "prompt_id":f"prompt:{kind}:{version}",
        "type":kind,"type_label":TYPES[kind],"version":version,
        "content":text.strip(),"content_sha256":checksum(text.strip()),
        "task_scope":payload["task_scope"],
        "change_reason":reason.strip(),"state":"DRAFT",
        "validation_state":"NOT_VALIDATED","validation_at":None,
        "created_at":now(),"source_type":"SIMULATED",
        "authority":_AUTHORITY_LIMITS,
    }
    api.store.put(db,NS,"prompt_draft",item["prompt_id"],item)
    api.store.put(db,NS,"prompt_head",kind,{
        "type":kind,"version":version,"prompt_id":item["prompt_id"],
        "updated_at":now(),"source_type":"SIMULATED",
    })
    return {
        "prompt_id":item["prompt_id"],"prompt_type":kind,
        "version":version,"state":"DRAFT","validation_state":"NOT_VALIDATED",
        "adopted_in_actual_agent_turn":False,"source_type":"SIMULATED",
    }


def validate(api,db,data,payload):
    _request(api,payload,{
        "client_request_id","prompt_type","prompt_version","expected_sha256",
    })
    kind=_require_prompt_type(payload["prompt_type"])
    ident=f'prompt:{kind}:{payload["prompt_version"]}'
    item=api.store.get(db,NS,"prompt_draft",ident)
    current=_one(db,"prompt_head",kind)
    require(current and current["prompt_id"]==ident,
            "只能校验当前最新待发布版本")
    require(item["content_sha256"]==payload["expected_sha256"],
            "待校验正文版本或哈希已变化",web.HTTPForbidden)
    require(item["state"]=="DRAFT","当前版本不可重新校验")
    require(item["task_scope"] in _ALLOWED_TASKS and
            8<=len(item["content"])<=4000,
            "Prompt 内容或适用范围不符合结构约束",web.HTTPBadRequest)
    # This is deliberately a structural/permission-contract check, NOT
    # model quality, injection resistance, or independent evaluator PASS.
    checks={
        "category_allowed":True,
        "task_scope_allowed":True,
        "content_present":True,
        "length_bounded":True,
        "does_not_change_business_tool_policy":True,
    }
    item["state"]="VALIDATED_STRUCTURE"
    item["validation_state"]="PASS_STRUCTURE_ONLY"
    item["validation_at"]=now()
    item["validation_checks"]=checks
    api.store.put(db,NS,"prompt_draft",ident,item)
    return {
        "prompt_id":ident,"prompt_type":kind,"version":item["version"],
        "state":item["state"],"validation_state":item["validation_state"],
        "checks":checks,
        "evaluated_against_real_model":False,
        "adopted_in_actual_agent_turn":False,"source_type":"SIMULATED",
    }


def activate(api,db,data,payload):
    _request(api,payload,{
        "client_request_id","prompt_type","prompt_version",
        "expected_sha256","expected_active_version",
    })
    kind=_require_prompt_type(payload["prompt_type"])
    ident=f'prompt:{kind}:{payload["prompt_version"]}'
    candidate=api.store.get(db,NS,"prompt_draft",ident)
    head=_one(db,"prompt_head",kind)
    require(head and head["prompt_id"]==ident,
            "只有当前最新已校验版本可以启用")
    require(candidate["state"]=="VALIDATED_STRUCTURE" and
            candidate["validation_state"]=="PASS_STRUCTURE_ONLY" and
            candidate["content_sha256"]==payload["expected_sha256"],
            "候选 Prompt 未通过当前版本的结构检查",web.HTTPForbidden)
    previous=_one(db,"prompt_active",kind)
    prior_version=previous["version"] if previous else "0"
    require(payload["expected_active_version"]==prior_version,
            "当前启用版本变化，须先重新审阅")
    # Activating technical guidance is not a BOSS authorization.
    pointer={
        "type":kind,"prompt_id":ident,
        "version":candidate["version"],"content_sha256":candidate["content_sha256"],
        "task_scope":candidate["task_scope"],"activated_at":now(),
        "source_type":"SIMULATED",
        "next_turn_application":"PENDING_RUNTIME_CONTEXT",
    }
    api.store.put(db,NS,"prompt_active",kind,pointer)
    return {
        "prompt_id":ident,"prompt_type":kind,"version":candidate["version"],
        "state":"ACTIVE_FOR_NEXT_AGENT_TURN",
        "previous_active_version":prior_version,
        "adopted_in_actual_agent_turn":False,
        "runtime_reload_not_required":True,
        "source_type":"SIMULATED",
    }


def prompt_catalog(db, store, namespace=NS):
    heads=[
        json.loads(r[0]) for r in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='prompt_head'",
            (namespace,)
        ).fetchall()
    ]
    active=[
        json.loads(r[0]) for r in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='prompt_active'",
            (namespace,)
        ).fetchall()
    ]
    drafts=[
        json.loads(r[0]) for r in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='prompt_draft'",
            (namespace,)
        ).fetchall()
    ]
    latest={h["type"]:h for h in heads}
    selected={r["type"]:r for r in active}
    by_id={r["prompt_id"]:r for r in drafts}
    usage=[
        json.loads(r[0]) for r in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='prompt_context_use'",
            (namespace,)
        ).fetchall()
    ]
    rows=[]
    for kind,label in TYPES.items():
        head=latest.get(kind)
        current=by_id.get(head["prompt_id"]) if head else None
        pointer=selected.get(kind)
        seen=[
            x for x in usage
            if x["type"]==kind and pointer and
            x["prompt_id"]==pointer["prompt_id"]
        ]
        rows.append({
            "prompt_type":kind,"label":label,
            "draft_version":head["version"] if head else "0",
            "draft_id":head["prompt_id"] if head else None,
            "draft_content":current["content"] if current else "",
            "draft_task_scope":current["task_scope"] if current else "ALL_BOSS_READS",
            "draft_change_reason":current["change_reason"] if current else "",
            "draft_state":current["state"] if current else "NOT_CREATED",
            "draft_sha256":current["content_sha256"] if current else None,
            "validation_state":current["validation_state"] if current else "NOT_VALIDATED",
            "active_version":pointer["version"] if pointer else "0",
            "active_id":pointer["prompt_id"] if pointer else None,
            "active_task_scope":pointer["task_scope"] if pointer else None,
            "adoption_seen_in_runtime_context":bool(seen),
            "last_context_at":max((x["at"] for x in seen),default=None),
        })
    return {
        "prompts":rows,
        "scope":"TECHNICAL_GUIDANCE_ONLY",
        "runtime_adoption_status":"CONTEXT_LOADED_ONLY_NOT_MODEL_COMPLETION",
        "independent_quality_evaluation_completed":False,
        "model_runtime_call_proven_by_this_endpoint":False,
        "source_type":"SIMULATED",
    }


def runtime_active_context(store,namespace=NS):
    """Load fresh at each runtime context-provider invocation, no restart.

    It returns only currently validated candidates, strictly scoped. It
    never exposes this content through the BOSS HTTP API.
    """
    result=[]
    with store.connect() as db:
        store.active(db,namespace)
        for pointer in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='prompt_active'",
            (namespace,)
        ).fetchall():
            active=json.loads(pointer[0])
            if active["type"] not in TYPES:
                continue
            draft=_one(db,"prompt_draft",active["prompt_id"])
            if not draft or draft["content_sha256"]!=active["content_sha256"]:
                continue
            if draft["state"]!="VALIDATED_STRUCTURE" or draft["task_scope"] not in _ALLOWED_TASKS:
                continue
            result.append({
                "type":active["type"],"prompt_id":active["prompt_id"],
                "version":active["version"],"task_scope":active["task_scope"],
                "content":draft["content"],
            })
        return sorted(result,key=lambda x:x["type"])


def record_context_adoption(store, selected, namespace=NS):
    """Evidence of context injection only (not proof of provider API success).

    Store hash/version/selected scope, never raw prompts or owner data.
    """
    if not selected:
        return
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.active(db,namespace)
        for item in selected:
            key=f'{item["prompt_id"]}:current'
            store.put(db,namespace,"prompt_context_use",key,{
                "type":item["type"],"prompt_id":item["prompt_id"],
                "version":item["version"],"task_scope":item["task_scope"],
                "content_sha256":checksum(item["content"]),
                "at":now(),"evidence_level":"RUNTIME_CONTEXT_PROVIDER_ONLY",
            })
