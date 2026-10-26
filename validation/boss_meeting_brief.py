"""FR-04 meeting preparation: source-pinned, versioned, read-only refresh.

Real deterministic aggregation of the fixed approved synthetic records. No
LLM narrative is invented. A preparation is an owner-authorized SQLite
transaction; viewing does not silently mutate or send message requests.
"""
from __future__ import annotations

import json
from datetime import datetime

from aiohttp import web
from business import checksum, now, require
from boss_travel import meeting_impacts
from boss_people import meeting_impacts as people_meeting_impacts
from boss_owner_preferences import owner_goal_reference
from boss_metrics import aggregate_metrics
from boss_v7_metrics import apply_configurations, record_adoption
from boss_meetings import meeting_materials
from boss_source_policy import source_validity
from boss_supply_quality import external_adoption

from boss_execution_scope import NAMESPACE as NS


def _get(db, kind, key):
    row=db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
                   (NS,kind,key)).fetchone()
    return json.loads(row[0]) if row else None


def _documents(db, data):
    results=[]
    for source_id in data["meeting"]["material_ids"]:
        if source_id == data["event"]["event_id"]:
            continue # a business event is not a documentary attachment
        document=_get(db,"document",source_id)
        if document is None:
            results.append({"source_id":source_id,"status":"MISSING","version":None,
                            "source_type":"SIMULATED","excerpt":None})
            continue
        authorized=document.get("access_scope")==data["owner_id"] and document.get("source_type")=="SIMULATED"
        clock=_get(db,"clock","current")["at"]
        validity=source_validity(document,clock) if authorized else "FORBIDDEN"
        adoption=external_adoption(db,NS,data,clock,document) if authorized else {"state":"NOT_APPLICABLE"}
        status="NEEDS_REVIEW" if validity=="VALID" and adoption["state"]=="NEEDS_REIMPORT" else "CURRENT" if validity=="VALID" else validity
        results.append({
            "source_id":source_id,"status":status,
            "version":document.get("version"),
            "source_type":"SIMULATED",
            "published_at":document.get("published_at"),
            "valid_from":document.get("valid_from"),"valid_until":document.get("valid_until"),
            "source_sha256":checksum(document) if status=="CURRENT" else None,
            "author_contact_id":document.get("author_contact_id"),
            "excerpt":document.get("content","")[:220] if status=="CURRENT" else None,
        })
    return results


def _metrics(db, data, approved):
    if not approved:
        return {"available":False,"reason":"finance-note CURRENT source not available",
                "values":[],"unexplained_causes":["缺少已核验的财务来源"]}
    details=data["details"]
    result=[]
    for period in ("BASE","CURRENT"):
        group=[r for r in details if r["period"]==period and
               r["region_id"]=="region-1" and r["trade_type"]=="EXTERNAL_SALES"]
        computed=aggregate_metrics(group)
        computed["metrics"], adopted = apply_configurations(db, NS, group, computed["metrics"])
        result.append({
            "period_scope":period,"date_range":data["periods"][period],
            "source_id":"finance-note","source_version":approved["version"],
            "definition_version":"1","source_type":"SIMULATED",
            "metrics":{metric:{"value":str(computed["metrics"][metric][0]) if computed["metrics"][metric][0] is not None else None,
                               "unit":computed["metrics"][metric][1]}
                       for metric in ("sales_quantity","revenue","gross_profit","gross_margin")},
            "detail_refs":[r["record_id"] for r in group],
            **({"metric_configurations": {identifier: {key: value for key, value in calculation.items() if key not in {"calculated_at", "next_refresh_at"}}
                                           for identifier, calculation in adopted.items()}} if adopted else {}),
        })
    return {"available":True,"values":result,
            "unexplained_causes":["贡献明细与经营变化原因未提供，不能推断"]}


def compile_brief(db,data):
    data=meeting_materials(db,data)
    meeting=data["meeting"]
    current_docs=_documents(db,data)
    missing=[d["source_id"] for d in current_docs if d["status"]!="CURRENT"]
    if meeting.get("state") == "CANCELED":
        missing.append("meeting:CANCELED")
    contacts=[]
    clock=_get(db,"clock","current")
    today=datetime.fromisoformat(clock["at"]).date().isoformat() if clock else ""
    for contact_id in meeting["participant_ids"]:
        candidates=[c for c in data["contacts"] if c["contact_id"]==contact_id]
        if len(candidates)!=1:
            missing.append("participant:"+contact_id)
            contacts.append({"contact_id":contact_id,"status":"UNKNOWN_ID"})
            continue
        contact=candidates[0]
        valid=contact["valid_from"]<=today<=contact["valid_until"]
        if not valid: missing.append("participant:"+contact_id)
        contacts.append({
            "contact_id":contact["contact_id"],"name":contact["name"],
            "organization":contact["organization"],"responsibility":contact["responsibility"],
            "status":"CURRENT" if valid else "EXPIRED",
        })
    existing_tasks=[
        json.loads(row[0]) for row in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='task'",
            (NS,)).fetchall()
    ]
    historical=data["historical_task"]
    commitments=[{
        "task_id":historical["task_id"],"status":historical["status"],
        "due_at":historical["due_at"],"evidence_requirements":historical["evidence_requirements"],
        "source_type":"SIMULATED","is_historical":True,
    }]
    for t in existing_tasks:
        if t.get("related_meeting_id")==meeting["meeting_id"]:
            commitments.append({
                "task_id":t["task_id"],"status":t["status"],
                "due_at":t["due_at"],"evidence_requirements":t["evidence_requirements"],
                "source_type":"SIMULATED","is_historical":False,
            })
    finance=next((d for d in current_docs if d["source_id"]=="finance-note" and
                  d["status"]=="CURRENT"),None)
    calculation=_metrics(db,data,finance)
    if not calculation["available"]:missing.append("metric:finance-note")
    meeting_event=_get(db,"event",data["event"]["event_id"])
    return {
        "meeting":{"meeting_id":meeting["meeting_id"],"version":meeting["version"],
                   "starts_at":meeting["starts_at"],"timezone":meeting["timezone"],
                   "ends_at":meeting.get("ends_at"),"state":meeting.get("state","DRAFT"),
                   "preparation_due_at":meeting.get("preparation_due_at")},
        "participants":contacts,
        "sources":current_docs,
        "commitments":commitments,
        "event":{
            "event_id":data["event"]["event_id"],
            "status":meeting_event["state"] if meeting_event else data["event"]["status"],
            "origin":"CURRENT_EVENT" if meeting_event else "FIXED_INITIAL_SNAPSHOT",
            "source_type":"SIMULATED",
        },
        "metrics":calculation,
        "travel_impacts":meeting_impacts(db,meeting),
        "people_meeting_impacts":people_meeting_impacts(db,meeting),
        "owner_goal_reference":owner_goal_reference(db,data),
        "missing_items":sorted(set(missing)),
        "needs_review":bool(missing),
        "prepared_for_owner":data["owner_id"],
        "source_type":"SIMULATED",
    }


def prepare(api,db,data,payload):
    data=meeting_materials(db,data)
    api._exact(payload,{"client_request_id","meeting_id","meeting_version",
                        "expected_version"})
    meeting=data["meeting"]
    require(payload["meeting_id"]==meeting["meeting_id"] and
            payload["meeting_version"]==meeting["version"],
            "会议 ID 或当前会议版本不符")
    previous=_get(db,"meeting_brief",meeting["meeting_id"])
    version=previous["version"] if previous else "0"
    require(payload["expected_version"]==version,
            "会前材料版本已变化，必须重新读取")
    compiled=compile_brief(db,data)
    new_version=str(int(version)+1)
    if previous:
        api.store.put(db,NS,"meeting_brief_revision",
                      meeting["meeting_id"]+":v"+version,previous)
    state="NEEDS_REVIEW" if compiled["needs_review"] else "READY_FOR_REVIEW"
    record={
        "brief_id":"brief:"+meeting["meeting_id"],
        "meeting_id":meeting["meeting_id"],
        "meeting_version":meeting["version"],
        "version":new_version,
        "state":state,
        "compiled":compiled,
        "prepared_at":now(),
        "reviewed_by_owner":False,
        "meeting_occurred":meeting.get("state")=="HELD",
        "message_sent":False,
        "source_type":"SIMULATED",
    }
    api.store.put(db,NS,"meeting_brief",meeting["meeting_id"],record)
    record_adoption(api.store, db, NS, record["brief_id"] + ":v" + new_version,
                    {item["period_scope"]: item.get("metric_configurations", {}) for item in compiled["metrics"]["values"]})
    return {
        "source_type":"SIMULATED","brief_id":record["brief_id"],
        "meeting_id":meeting["meeting_id"],"version":new_version,
        "state":state,"source_count":len(compiled["sources"]),
        "missing_count":len(compiled["missing_items"]),
        "historical_commitment_count":len(compiled["commitments"]),
        "message_sent":False,"meeting_occurred":record["meeting_occurred"],
    }


def briefing_projection(db,data):
    current=compile_brief(db,data)
    stored=_get(db,"meeting_brief",data["meeting"]["meeting_id"])
    if stored is None:
        return {
            "saved":False,"saved_brief":None,
            "current":current,"current_status":"NOT_PREPARED",
            "needs_review":True,
            "meeting_occurred":current["meeting"]["state"]=="HELD","material_request_sent":False,
            "revisions":[],
        }
    old=stored["compiled"]
    pinned={doc["source_id"]:(doc["version"],doc["status"],doc.get("source_sha256"))
            for doc in old["sources"]}
    available={doc["source_id"]:(doc["version"],doc["status"],doc.get("source_sha256"))
               for doc in current["sources"]}
    source_changed=pinned!=available
    participant_changed=old["participants"]!=current["participants"]
    meeting_changed=old["meeting"]!=current["meeting"]
    # Other changes (e.g. new task or simulated event state) also need review.
    business_changed=(old["commitments"]!=current["commitments"] or old["event"]!=current["event"]
                      or old.get("travel_impacts",[])!=current["travel_impacts"]
                      or old.get("people_meeting_impacts",[])!=current["people_meeting_impacts"]
                      or old.get("owner_goal_reference",{})!=current["owner_goal_reference"])
    changed=source_changed or participant_changed or meeting_changed or business_changed or old["metrics"]!=current["metrics"]
    status="NEEDS_REVIEW" if changed or current["needs_review"] else stored["state"]
    revisions=[
        {"version":row["version"],"state":row["state"],
         "prepared_at":row["prepared_at"]}
        for row in (
            json.loads(v[0]) for v in db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='meeting_brief_revision'",
                (NS,)).fetchall()
        ) if row["meeting_id"]==stored["meeting_id"]
    ]
    # Preserve the historical snapshot *in SQLite*, but never serve a
    # previously cached excerpt or numeric aggregate from a source that has
    # since been revoked or superseded. Historic references stay visible.
    display_snapshot=json.loads(json.dumps(stored))
    latest={doc["source_id"]:doc for doc in current["sources"]}
    for old_doc in display_snapshot["compiled"]["sources"]:
        live=latest.get(old_doc["source_id"])
        if not live or live["status"]!="CURRENT" or live["version"]!=old_doc["version"] or live.get("source_sha256")!=old_doc.get("source_sha256"):
            old_doc["excerpt"]=None
            old_doc["display_redacted_due_to_source_change"]=True
    old_finance=next((doc for doc in display_snapshot["compiled"]["sources"]
                      if doc["source_id"]=="finance-note"),None)
    if not old_finance or old_finance.get("display_redacted_due_to_source_change"):
        display_snapshot["compiled"]["metrics"]={
            "available":False,"values":[],
            "reason":"HISTORICAL_METRICS_SOURCE_NOT_CURRENT",
            "unexplained_causes":["来源版本撤销或已变化，旧指标不作为当前依据"],
        }
    return {
        "saved":True,"saved_brief":display_snapshot,
        "current":current,"current_status":status,
        "needs_review":status=="NEEDS_REVIEW",
        "source_changed":source_changed,
        "participant_changed":participant_changed,
        "meeting_changed":meeting_changed,
        "business_changed":business_changed,
        "meeting_occurred":current["meeting"]["state"]=="HELD","material_request_sent":False,
        "revisions":revisions,
    }
