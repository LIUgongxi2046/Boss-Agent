"""FR-06 owner commitments: explicit BOSS-only personal promise lifecycle.

Separated from assignments to other contacts; never invents an employee or
sends messages. Mutations share BossCommandAPI's BEGIN IMMEDIATE SQLite
transaction, authorization, redacted audit and idempotent receipts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from aiohttp import web

from business import now, require, checksum

NS="ui-check"
FINAL={"COMPLETED_CONFIRMED","CANCELED"}


def _ensure(api, payload, keys):
    api._exact(payload, keys)


def _source_refs(api, db, data, refs, *, allow_empty=True):
    require(isinstance(refs,list) and len(refs)<=8 and
            (allow_empty or len(refs)>0),
            "需要明确获准的来源清单", web.HTTPBadRequest)
    ids=set()
    result=[]
    for ref in refs:
        require(isinstance(ref,dict) and set(ref)=={"source_id","version"} and
                all(isinstance(v,str) for v in ref.values()),
                "证据引用须包含唯一来源及版本",web.HTTPBadRequest)
        require(ref["source_id"] not in ids,
                "重复来源不能代表两份不同证据",web.HTTPBadRequest)
        ids.add(ref["source_id"])
        doc=api._require_current_source(db,data,ref["source_id"])
        require(doc["version"]==ref["version"],
                "当前证据来源版本已变更")
        result.append({"source_id":doc["source_id"],"version":doc["version"]})
    return result


def _current_clock(api,db):
    return datetime.fromisoformat(api.store.get(db,NS,"clock","current")["at"])


def _due(api, db, value, tzname):
    from boss_command_api import _aware_due
    dt=_aware_due(value,tzname)
    current=_current_clock(api,db)
    require(dt>current,"本人承诺期限必须在当前业务时钟之后",web.HTTPBadRequest)
    require((dt-current).total_seconds() <= 366*86400,
            "个人承诺期限最长366天",web.HTTPBadRequest)
    return dt


def _event(api,db,row,reason):
    event_id="owner-due:"+row["commitment_id"]
    old=db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind='event' AND id=?",
        (NS,event_id),
    ).fetchone()
    import json
    previous=json.loads(old[0]) if old else None
    version=str(int(previous["version"])+1) if previous else "1"
    state="CANCELED" if row["status"] in FINAL else "OPEN"
    record={
        "event_id":event_id,"commitment_id":row["commitment_id"],
        "version":version,"state":state,"impact":row["importance"],
        "due_at":row["due_at"],"source_type":"SIMULATED",
        "generated_by":"BOSS_OWN_COMMITMENT","updated_at":now(),
        "commitment_version":row["version"],"transition_reason":reason,
        "external_delivery_created":False,
    }
    api.store.put(db,NS,"event",event_id,record)
    return {"event_id":event_id,"event_version":version,
            "state":state,"due_at":row["due_at"],
            "automatic_external_delivery":False}


def create(api,db,data,p):
    _ensure(api,p,{
        "client_request_id","purpose","due_at","timezone",
        "evidence_requirements","source_refs","importance",
    })
    require(isinstance(p["purpose"],str) and 1<=len(p["purpose"].strip())<=1600,
            "本人承诺须包含目的与产物",web.HTTPBadRequest)
    require(p["importance"] in {"NORMAL","IMPORTANT"},
            "重要程度无效",web.HTTPBadRequest)
    require(isinstance(p["evidence_requirements"],list) and
            1<=len(p["evidence_requirements"])<=8 and
            all(isinstance(x,str) and 1<=len(x.strip())<=160
                for x in p["evidence_requirements"]),
            "必须明确后续核查证据要求",web.HTTPBadRequest)
    _due(api,db,p["due_at"],p["timezone"])
    refs=_source_refs(api,db,data,p["source_refs"])
    ident="owner-task-"+str(uuid.uuid4())
    authorization=api._authorize(db,"commitment.create",{
        "commitment_id":ident,
        "purpose_sha256":checksum(p["purpose"].strip()),
        "due_at":p["due_at"],"timezone":p["timezone"],
        "requirements_sha256":checksum(p["evidence_requirements"]),
        "sources":refs,"importance":p["importance"],
    },ident,"1")
    row={
        "commitment_id":ident,"owner_id":data["owner_id"],
        "purpose":p["purpose"].strip(),"version":"1",
        "status":"ACTIVE","due_at":p["due_at"],
        "timezone":p["timezone"],"importance":p["importance"],
        "evidence_requirements":[x.strip() for x in p["evidence_requirements"]],
        "source_refs":refs,"completion_evidence":[],
        "created_at":now(),"updated_at":now(),
        "authorization_id":authorization,
        "completion_authorization_id":None,
        "source_type":"SIMULATED",
        "external_message_sent":False,
    }
    api.store.put(db,NS,"self_commitment",ident,row)
    due=_event(api,db,row,"BOSS_CREATED")
    return {"source_type":"SIMULATED","commitment_id":ident,
            "status":"ACTIVE","version":"1",
            "authorization_id":authorization,
            "due_event":due,
            "external_message_sent":False}


def _current(api,db,data,p):
    ident=p["commitment_id"]
    require(isinstance(ident,str) and ident.startswith("owner-task-")
            and len(ident)<=100,"本人承诺标识不合法",web.HTTPBadRequest)
    row=api.store.get(db,NS,"self_commitment",ident)
    require(row["owner_id"]==data["owner_id"] and
            row["source_type"]=="SIMULATED",
            "本人承诺不属于当前身份",web.HTTPForbidden)
    require(row["version"]==p["expected_version"],
            "个人承诺版本已变化，需要重新核查")
    require(row["status"]=="ACTIVE","已终止承诺不能再次操作")
    return row


def extend(api,db,data,p):
    _ensure(api,p,{"client_request_id","commitment_id",
                   "expected_version","due_at","reason"})
    row=_current(api,db,data,p)
    require(isinstance(p["reason"],str) and
            1<=len(p["reason"].strip())<=500,
            "调整期限须由本人填写原因",web.HTTPBadRequest)
    _due(api,db,p["due_at"],row["timezone"])
    require(datetime.fromisoformat(p["due_at"])>datetime.fromisoformat(row["due_at"]),
            "延期必须晚于原定期限",web.HTTPBadRequest)
    authorization=api._authorize(db,"commitment.extend",{
        "commitment_id":row["commitment_id"],
        "old_version":row["version"],"old_due_at":row["due_at"],
        "new_due_at":p["due_at"],
        "reason_sha256":checksum(p["reason"].strip()),
    },row["commitment_id"],row["version"])
    api.store.put(db,NS,"self_commitment_revision",
                  row["commitment_id"]+":v"+row["version"],row)
    row["version"]=str(int(row["version"])+1)
    row["due_at"]=p["due_at"]
    row["updated_at"]=now()
    row["last_extension_authorization_id"]=authorization
    api.store.put(db,NS,"self_commitment",row["commitment_id"],row)
    due=_event(api,db,row,"OWNER_EXTENDED")
    return {"source_type":"SIMULATED","commitment_id":row["commitment_id"],
            "version":row["version"],"status":row["status"],
            "due_at":row["due_at"],"due_event":due,
            "authorization_id":authorization,
            "external_message_sent":False}


def complete(api,db,data,p):
    _ensure(api,p,{"client_request_id","commitment_id",
                   "expected_version","evidence_refs"})
    row=_current(api,db,data,p)
    refs=_source_refs(api,db,data,p["evidence_refs"],allow_empty=False)
    authorization=api._authorize(db,"commitment.complete",{
        "commitment_id":row["commitment_id"],
        "version":row["version"],"evidence_refs":refs,
    },row["commitment_id"],row["version"])
    api.store.put(db,NS,"self_commitment_revision",
                  row["commitment_id"]+":v"+row["version"],row)
    row["version"]=str(int(row["version"])+1)
    row["status"]="COMPLETED_CONFIRMED"
    row["completion_evidence"]=refs
    row["completion_authorization_id"]=authorization
    row["completed_at"]=now()
    row["updated_at"]=row["completed_at"]
    api.store.put(db,NS,"self_commitment",row["commitment_id"],row)
    due=_event(api,db,row,"OWNER_COMPLETED")
    return {"source_type":"SIMULATED","commitment_id":row["commitment_id"],
            "version":row["version"],"status":row["status"],
            "authorization_id":authorization,"due_event":due,
            "external_message_sent":False}


def cancel(api,db,data,p):
    _ensure(api,p,{"client_request_id","commitment_id",
                   "expected_version","reason"})
    row=_current(api,db,data,p)
    require(isinstance(p["reason"],str) and
            1<=len(p["reason"].strip())<=500,
            "取消本人承诺需要原因",web.HTTPBadRequest)
    authorization=api._authorize(db,"commitment.cancel",{
        "commitment_id":row["commitment_id"],"version":row["version"],
        "reason_sha256":checksum(p["reason"].strip()),
    },row["commitment_id"],row["version"])
    api.store.put(db,NS,"self_commitment_revision",
                  row["commitment_id"]+":v"+row["version"],row)
    row["version"]=str(int(row["version"])+1)
    row["status"]="CANCELED"
    row["cancellation_reason_sha256"]=checksum(p["reason"].strip())
    row["cancellation_authorization_id"]=authorization
    row["canceled_at"]=now()
    row["updated_at"]=row["canceled_at"]
    api.store.put(db,NS,"self_commitment",row["commitment_id"],row)
    due=_event(api,db,row,"OWNER_CANCELED")
    return {"source_type":"SIMULATED","commitment_id":row["commitment_id"],
            "version":row["version"],"status":row["status"],
            "authorization_id":authorization,"due_event":due,
            "external_message_sent":False}
