"""A05 technical Prompt configuration; next-turn adoption only, no business rights."""
from __future__ import annotations
import json
import re
import uuid
from aiohttp import web
from business import now, checksum, require
from boss_source_policy import source_validity

from boss_execution_scope import NAMESPACE as NS
KINDS=("SECRETARY_ROLE","EXPRESSION","TASK_HINTS")
SECRET=re.compile(r"\bsk-[A-Za-z0-9_-]{25,}\b")


def obj(db,kind,key,namespace=NS):
    row=db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",(namespace,kind,key)).fetchone()
    return json.loads(row[0]) if row else None


def text_field(value, label, maximum, minimum=1):
    require(isinstance(value,str) and minimum<=len(value.strip())<=maximum,
            label+"格式或长度无效",web.HTTPBadRequest)
    require(not SECRET.search(value),"Prompt不能保存疑似密钥",web.HTTPBadRequest)
    return value.strip()


def refs(api,db,data,values):
    require(isinstance(values,list) and len(values)<=5
            and all(isinstance(x,str) for x in values)
            and len(set(values))==len(values),"Prompt资料引用不合法",web.HTTPBadRequest)
    items=[]
    for sid in values:
        source=_require_adoptable_source(api,db,data,sid)
        items.append({"source_id":sid,"version":source["version"]})
    return items


def _require_adoptable_source(api,db,data,source_id):
    source=api._require_current_source(db,data,source_id)
    clock=api.store.get(db,NS,"clock","current")["at"]
    state=source_validity(source,clock)
    require(state=="VALID","引用资料当前无法采用："+state)
    return source


def save(api,db,data,p):
    api._exact(p,{"client_request_id","prompt_id","expected_version",
                  "kind","title","instruction_text","change_note","source_ids"})
    require(p["kind"] in KINDS,"Prompt任务类型无效",web.HTTPBadRequest)
    body=text_field(p["instruction_text"],"提示词正文",5000,20)
    title=text_field(p["title"],"标题",120)
    note=text_field(p["change_note"],"变更说明",360)
    sources=refs(api,db,data,p["source_ids"])
    pid=p["prompt_id"]
    require(pid is None or isinstance(pid,str) and pid.startswith("prompt-") and len(pid)<96,
            "Prompt标识无效",web.HTTPBadRequest)
    existing=obj(db,"prompt_draft",pid) if pid else None
    version=existing["version"] if existing else "0"
    require(p["expected_version"]==version,"当前草稿版本变化")
    if existing:
        require(existing["kind"]==p["kind"],"不可更改已有Prompt类别")
        api.store.put(db,NS,"prompt_revision",pid+":v"+version,existing)
    else:
        pid="prompt-"+str(uuid.uuid4())
    current={
        "prompt_id":pid,"kind":p["kind"],"title":title,"instruction_text":body,
        "version":str(int(version)+1),"change_note":note,"source_refs":sources,
        "content_sha256":checksum(body),"validation_status":"DRAFT_UNVALIDATED",
        "validated_content_sha256":None,"validated_at":None,
        "updated_at":now(),"source_type":"TECHNICAL_CONFIG",
        "actual_model_evaluation_passed":False,
    }
    api.store.put(db,NS,"prompt_draft",pid,current)
    return {"prompt_id":pid,"version":current["version"],"kind":p["kind"],
            "validation_status":"DRAFT_UNVALIDATED",
            "content_sha256":current["content_sha256"],
            "runtime_adopted":False,"actual_model_evaluation_passed":False}


def validate(api,db,data,p):
    api._exact(p,{"client_request_id","prompt_id","expected_version","expected_content_sha256"})
    doc=api.store.get(db,NS,"prompt_draft",p["prompt_id"])
    require(doc["version"]==p["expected_version"] and
            doc["content_sha256"]==p["expected_content_sha256"],"版本或内容摘要冲突")
    require(doc["validation_status"]=="DRAFT_UNVALIDATED","当前版本已经校验")
    for ref in doc["source_refs"]:
        d=_require_adoptable_source(api,db,data,ref["source_id"])
        require(d["version"]==ref["version"],"引用资料版本变化")
    api.store.put(db,NS,"prompt_revision",doc["prompt_id"]+":v"+doc["version"],doc)
    doc["version"]=str(int(doc["version"])+1)
    doc["validation_status"]="VALIDATED_STATIC_ONLY"
    doc["validated_at"]=now()
    doc["validated_content_sha256"]=doc["content_sha256"]
    api.store.put(db,NS,"prompt_draft",doc["prompt_id"],doc)
    return {"prompt_id":doc["prompt_id"],"kind":doc["kind"],"version":doc["version"],
            "validation_status":"VALIDATED_STATIC_ONLY",
            "actual_model_evaluation_passed":False,"runtime_adopted":False}


def activate(api,db,data,p):
    api._exact(p,{"client_request_id","prompt_id","expected_version",
                  "expected_content_sha256","expected_active_version"})
    doc=api.store.get(db,NS,"prompt_draft",p["prompt_id"])
    require(doc["version"]==p["expected_version"] and
            doc["content_sha256"]==p["expected_content_sha256"],"启用内容已经变化")
    require(doc["validation_status"]=="VALIDATED_STATIC_ONLY" and
            doc["validated_content_sha256"]==doc["content_sha256"],"必须先校验当前内容")
    for ref in doc["source_refs"]:
        d=_require_adoptable_source(api,db,data,ref["source_id"])
        require(d["version"]==ref["version"],"知识来源已经失效")
    old=obj(db,"prompt_active",doc["kind"])
    ver=old["active_version"] if old else "0"
    require(p["expected_active_version"]==ver,"当前已启用版本变化")
    if old:
        api.store.put(db,NS,"prompt_active_revision",doc["kind"]+":v"+ver,old)
    current={"kind":doc["kind"],"active_version":str(int(ver)+1),
             "prompt_id":doc["prompt_id"],"prompt_version":doc["version"],
             "content_sha256":doc["content_sha256"],"enabled":True,
             "activated_at":now(),"adoption_policy":"NEXT_BOSS_TURN_ONLY",
             "actual_model_evaluation_passed":False}
    api.store.put(db,NS,"prompt_active",doc["kind"],current)
    return {"kind":doc["kind"],"prompt_id":doc["prompt_id"],
            "prompt_version":doc["version"],"active_version":current["active_version"],
            "enabled":True,"adoption_policy":"NEXT_BOSS_TURN_ONLY",
            "actual_model_evaluation_passed":False}


def deactivate(api,db,data,p):
    api._exact(p,{"client_request_id","kind","expected_active_version"})
    require(p["kind"] in KINDS,"Prompt类别不合法",web.HTTPBadRequest)
    old=obj(db,"prompt_active",p["kind"])
    require(old and old["enabled"] and old["active_version"]==p["expected_active_version"],
            "当前已启用版本变化或已经停用")
    api.store.put(db,NS,"prompt_active_revision",p["kind"]+":v"+old["active_version"],old)
    old["active_version"]=str(int(old["active_version"])+1)
    old["enabled"]=False
    old["deactivated_at"]=now()
    api.store.put(db,NS,"prompt_active",p["kind"],old)
    return {"kind":p["kind"],"active_version":old["active_version"],
            "enabled":False,"adoption_policy":"NEXT_BOSS_TURN_ONLY"}


def active_runtime_prompts(store,namespace=NS):
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db,namespace)
        return _select_runtime_prompts(store, db, namespace)


def _select_runtime_prompts(store, db, namespace):
    output = []
    data = store.get(db, namespace, "initial", "snapshot")
    clock = store.get(db, namespace, "clock", "current")["at"]
    for kind in KINDS:
        active = obj(db, "prompt_active", kind, namespace)
        if not active or not active["enabled"]:
            continue
        draft = obj(db, "prompt_draft", active["prompt_id"], namespace)
        if not draft or draft["version"] != active["prompt_version"] or (
            draft["content_sha256"] != active["content_sha256"]
        ) or draft["validation_status"] != "VALIDATED_STATIC_ONLY":
            continue
        healthy = True
        for ref in draft["source_refs"]:
            document = obj(db, "document", ref["source_id"], namespace)
            if not document or document.get("withdrawn") or (
                document.get("access_scope") != data["owner_id"]
            ) or document.get("source_type") != "SIMULATED" or document["version"] != ref["version"] or source_validity(document, clock) != "VALID":
                healthy = False
                break
        if healthy:
            output.append({"kind": kind, "prompt_id": draft["prompt_id"],
                           "prompt_version": draft["version"],
                           "active_version": active["active_version"],
                           "instruction_text": draft["instruction_text"],
                           "source_refs": draft["source_refs"]})
    return output


def load_runtime_prompts(store, namespace=NS):
    # 选择与记录使用同一事务，返回本次真正有效的配置。
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.active(db, namespace)
        selected = _select_runtime_prompts(store, db, namespace)
        _record_runtime_context_load(store, db, selected, namespace)
        return selected


def _record_runtime_context_load(store, db, selected, namespace):
    for entry in selected:
        active = obj(db, "prompt_active", entry["kind"], namespace)
        identifier = active["prompt_id"] + ":" + active["prompt_version"]
        previous = obj(db, "prompt_context_use", identifier, namespace)
        store.put(db, namespace, "prompt_context_use", identifier, {
            "kind": entry["kind"], "prompt_id": active["prompt_id"],
            "prompt_version": active["prompt_version"],
            "active_version": active["active_version"],
            "content_sha256": active["content_sha256"], "at": now(),
            "context_load_count": previous["context_load_count"] + 1 if previous else 1,
            "observation": "RUNTIME_CONTEXT_PROVIDER_INVOKED",
            "model_completion_verified": False,
            "technical_configuration_grants_business_authority": False,
        })


def record_runtime_context_load(store, runtime_prompts, namespace=NS):
    """Record metadata after a *real RuntimeContextBlock provider* selects a version.

    This does not claim the DeepSeek API accepted a prompt, produced a reply,
    or passed safety/quality evaluation. Re-check the pointer under SQLite
    BEGIN IMMEDIATE: an activation may have changed between read and use.
    No prompt body, owner memory, model text, or API credential is logged.
    """
    if not runtime_prompts:
        return
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.active(db, namespace)
        current = _select_runtime_prompts(store, db, namespace)
        selected = [entry for entry in current if entry in runtime_prompts]
        _record_runtime_context_load(store, db, selected, namespace)
