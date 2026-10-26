"""FR-09 source-grounded research with versioned scope, citations and invalidation.

This is a deterministic, owner-only local research step. The current dataset
does not have enough evidence to assert professional conclusions or causal
claims, and no model inference or public web retrieval is fabricated.
Source content is untrusted text, never a tool instruction.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from aiohttp import web
from business import now, require
from boss_source_policy import source_validity
from boss_supply_quality import external_adoption

from boss_execution_scope import NAMESPACE as NS
REPORT_ID="research-current"


def _find(db, kind, ident):
    row=db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
        (NS,kind,ident),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _scope(payload):
    required={"client_request_id","expected_version","question","period",
              "country","business_relation","cutoff_date"}
    allowed=required|{"source_refs","execution_namespace"}
    require(required<=set(payload)<=allowed,"研究范围字段无效",web.HTTPBadRequest)
    question=payload["question"]
    require(isinstance(question,str) and 2<=len(question.strip())<=160,
            "研究问题应为2—160字",web.HTTPBadRequest)
    for key,limit in (("period",60),("country",60),("business_relation",160)):
        val=payload[key]
        require(isinstance(val,str) and len(val.strip())<=limit,
                "研究条件超出长度范围",web.HTTPBadRequest)
    cutoff=payload["cutoff_date"]
    require(isinstance(cutoff,str) and re.fullmatch(r"\d{4}-\d\d-\d\d",cutoff),
            "须提供有效资料截止日期",web.HTTPBadRequest)
    try:
        date.fromisoformat(cutoff)
    except ValueError:
        raise web.HTTPBadRequest(text="资料截止日期非法") from None
    scope={
        "question":question.strip(),"period":payload["period"].strip(),
        "country":payload["country"].strip(),
        "business_relation":payload["business_relation"].strip(),
        "cutoff_date":cutoff,
    }
    if "execution_namespace" in payload:
        require(payload["execution_namespace"]==NS,"执行空间不一致",web.HTTPConflict)
        scope["execution_namespace"]=NS
    if "source_refs" in payload:
        refs=payload["source_refs"]
        require(isinstance(refs,list) and 1<=len(refs)<=8,"资料选择数量无效",web.HTTPBadRequest)
        seen=set()
        for ref in refs:
            require(isinstance(ref,dict) and set(ref)=={"source_id","version"},"资料选择字段无效",web.HTTPBadRequest)
            identifier,version=ref["source_id"],ref["version"]
            require(isinstance(identifier,str) and 0<len(identifier)<=128
                    and isinstance(version,str) and 0<len(version)<=40,
                    "资料标识或版本无效",web.HTTPBadRequest)
            require((identifier,version) not in seen,"资料选择重复",web.HTTPBadRequest)
            seen.add((identifier,version))
        scope["source_refs"]=[{"source_id":a,"version":b} for a,b in sorted(seen)]
    return scope


def _selected(scope):
    refs=scope.get("source_refs")
    return {(ref["source_id"],ref["version"]) for ref in refs} if refs else None


def _available_sources(db, data):
    clock=_find(db,"clock","current")["at"]
    result=[]
    for row in db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind='document' ORDER BY id",
        (NS,),
    ).fetchall():
        doc=json.loads(row[0])
        if doc.get("simulation_definition")=="SECTOR-PACK-1":
            continue
        current=(doc.get("source_type")=="SIMULATED"
                 and doc.get("access_scope")==data["owner_id"]
                 and not doc.get("withdrawn")
                 and source_validity(doc,clock)=="VALID"
                 and external_adoption(db,NS,data,clock,doc)["state"]!="NEEDS_REIMPORT")
        result.append({"source_id":doc["source_id"],"version":doc.get("version"),
                       "title":(doc.get("content") or doc["source_id"])[:40],
                       "reference_state":"CURRENT" if current else "UNAVAILABLE"})
    return result


def _source_quotes(db, data, scope, selected=None):
    records=db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind='document' ORDER BY id",
        (NS,),
    ).fetchall()
    matched=[]
    conflicted=[]
    source_issues=[]
    covered=0
    rejected={"withdrawn":0,"forbidden":0,"after_cutoff":0,"no_match":0,"not_current":0,"not_selected":0}
    clock=_find(db,"clock","current")["at"]
    token=scope["question"].casefold()
    for row in records:
        doc=json.loads(row[0])
        if doc.get("source_type")!="SIMULATED" or doc.get("access_scope")!=data["owner_id"]:
            rejected["forbidden"]+=1
            continue
        if doc.get("withdrawn") is True:
            rejected["withdrawn"]+=1
            continue
        if selected is not None and (doc.get("source_id"),doc.get("version")) not in selected:
            rejected["not_selected"]+=1
            continue
        stamp=doc.get("published_at")
        if not isinstance(stamp,str):
            rejected["after_cutoff"]+=1
            continue
        try:
            if datetime.fromisoformat(stamp).date()>date.fromisoformat(scope["cutoff_date"]):
                rejected["after_cutoff"]+=1
                continue
        except ValueError:
            rejected["after_cutoff"]+=1
            continue
        validity=source_validity(doc,clock)
        adoption=external_adoption(db,NS,data,clock,doc)
        if validity=="VALID" and adoption["state"]!="NEEDS_REIMPORT":
            covered+=1
        else:
            rejected["not_current"]+=1
        content=doc.get("content","")
        if not isinstance(content,str):
            rejected["no_match"]+=1
            continue
        begin=content.casefold().find(token)
        if begin<0:
            rejected["no_match"]+=1
            continue
        if adoption["state"]=="NEEDS_REIMPORT":
            source_issues.append({
                "source_id":doc["source_id"],"version":doc["version"],
                "validity_state":validity,"eligible_as_current_evidence":False,
                "adoption_state":adoption["state"],"adoption_dependencies":adoption["dependencies"],
                "valid_from":doc.get("valid_from"),"valid_until":doc.get("valid_until"),
            })
            continue
        if validity!="VALID":
            source_issues.append({
                "source_id":doc["source_id"],"version":doc["version"],
                "validity_state":validity,"eligible_as_current_evidence":False,
                "valid_from":doc.get("valid_from"),"valid_until":doc.get("valid_until"),
            })
            if validity!="CONFLICTED":
                continue
        end=min(len(content),begin+max(len(scope["question"]),90))
        start=max(0,begin-45)
        excerpt={
            "source_id":doc["source_id"],
            "source_type":"SIMULATED",
            "version":doc["version"],
            "published_at":doc["published_at"],
            "author_contact_id":doc.get("author_contact_id"),
            "original_locator":doc.get("original_locator"),
            "quote_start":start,"quote_end":end,
            "quote":content[start:end],
            "match_start":begin,
            "claim_kind":"UNVERIFIED_SOURCE_EXCERPT",
            "source_text_is_untrusted_instruction":True,
            "validity_state":validity,
            "eligible_as_current_evidence":validity=="VALID",
        }
        (matched if validity=="VALID" else conflicted).append(excerpt)
    missing=[]
    if not matched:missing.append("NO_APPROVED_SOURCE_MATCH")
    if source_issues:missing.append("CURRENT_SOURCE_VALIDITY_REQUIRES_REVIEW")
    if conflicted:missing.append("SOURCE_CONFLICT_REQUIRES_REVIEW")
    if scope["country"]:missing.append("COUNTRY_TO_BUSINESS_RELATION_NOT_VERIFIED")
    if scope["period"]:missing.append("REQUESTED_PERIOD_NOT_VERIFIED_AGAINST_SOURCE")
    if scope["business_relation"]:missing.append("BUSINESS_CAUSAL_LINK_NOT_VERIFIED")
    missing.append("CAUSE_ATTRIBUTION_AND_EXPERT_CONFIRMATION_MISSING")
    return {
        "matched_sources":matched[:20],
        "conflicted_sources":conflicted[:20],
        "source_issues":source_issues,
        "coverage":{
            "current_approved_sources":covered,
            "matched_source_count":len(matched),
            "rejected":rejected,
            "limit":20,
            "all_sources_exhausted":len(matched)<=20,
            "public_web_search_performed":False,
            "semantic_retrieval_performed":False,
        },
        "facts_confirmed":[],
        "author_opinions_confirmed":[],
        "model_inferences":[],
        "missing_items":missing,
    }


def prepare(api,db,data,payload):
    api._exact(payload,{
        "client_request_id","expected_version","question","period",
        "country","business_relation","cutoff_date",
    } | ({"source_refs"} if "source_refs" in payload else set())
      | ({"execution_namespace"} if "execution_namespace" in payload else set()))
    scope=_scope(payload)
    selected=_selected(scope)
    previous=_find(db,"research",REPORT_ID)
    prev_version=previous["version"] if previous else "0"
    require(payload["expected_version"]==prev_version,
            "研究范围版本已变化；请重读再提交")
    if selected is not None:
        current={(row["source_id"],row["version"]) for row in _available_sources(db,data) if row["reference_state"]=="CURRENT"}
        require(selected<=current,"所选资料不在当前有效范围",web.HTTPConflict)
    research=_source_quotes(db,data,scope,selected)
    version=str(int(prev_version)+1)
    if previous:
        api.store.put(db,NS,"research_revision",
                      f'{REPORT_ID}:v{prev_version}',previous)
    result={
        "research_id":REPORT_ID,
        "version":version,"state":"SOURCE_REVIEW_REQUIRED",
        "scope":scope,
        **research,
        "prepared_at":now(),"source_type":"SIMULATED",
        "owner_id":data["owner_id"],"published_conclusions":False,
        "external_message_sent":False,
    }
    api.store.put(db,NS,"research",REPORT_ID,result)
    # No owner authorization for *read-only* analysis required: the
    # mutation records an explicit owner request, not any external send.
    return {
        "research_id":REPORT_ID,"version":version,
        "state":"SOURCE_REVIEW_REQUIRED",
        "source_type":"SIMULATED",
        "matched_source_count":len(research["matched_sources"]),
        "missing_count":len(research["missing_items"]),
        "published_conclusions":False,
        "external_message_sent":False,
    }


def project(db,data):
    saved=_find(db,"research",REPORT_ID)
    if not saved:
        return {
            "saved":False,"report":None,
            "contacts":[{
                "contact_id":person["contact_id"],"name":person["name"],
                "organization":person["organization"],
                "responsibility":person["responsibility"],
                "valid_from":person["valid_from"],"valid_until":person["valid_until"],
            } for person in data["contacts"]],
            "preferred_timezone":data["boss_profile"]["timezone"],
            "current_reference_state":"NOT_PREPARED",
            "read_only":True,"source_type":"SIMULATED",
            "source_selection_available":True,"available_sources":_available_sources(db,data),
            "execution_namespace":NS,"data_version":data["dataset_version"],
            "revisions":[],
        }
    latest=_source_quotes(db,data,saved["scope"],_selected(saved["scope"]))
    # Even a bad upstream import that rewrites content without bumping its
    # declared version must force review; compare the *actual quote bytes*
    # as well as citation ID/version/offset.
    def signatures(rows):
        return {
            (item["source_id"],item["version"],item["quote_start"],
             item["quote_end"],item["quote"])
            for item in rows
        }
    current_versions=signatures(latest["matched_sources"])
    prior_versions=signatures(saved["matched_sources"])
    status=("CURRENT_SOURCE_EXCERPTS" if current_versions==prior_versions and not latest["source_issues"]
            else "NEEDS_REVIEW")
    # Always re-check source withdrawal and version before returning text.
    # Historic excerpts never survive a changed or withdrawn reference.
    safe=dict(saved)
    safe["matched_sources"]=latest["matched_sources"]
    safe["conflicted_sources"]=latest["conflicted_sources"]
    safe["source_issues"]=latest["source_issues"]
    safe["coverage"]=latest["coverage"]
    safe["missing_items"]=latest["missing_items"]
    safe["facts_confirmed"]=[]
    safe["author_opinions_confirmed"]=[]
    safe["model_inferences"]=[]
    safe["published_conclusions"]=False
    safe["historical_source_text_reused"]=False
    if status=="NEEDS_REVIEW":
        safe["state"]="NEEDS_REVIEW"
    revisions=[{
        "research_id":entry["research_id"],"version":entry["version"],
        "prepared_at":entry["prepared_at"],"state":entry["state"],
        "source_quote_text_released":False,
    } for entry in (
        json.loads(row[0]) for row in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='research_revision'",
            (NS,),
        ).fetchall()
    )]
    clock=data.get("boss_profile",{}).get("timezone","Asia/Shanghai")
    return {
        "saved":True,"report":safe,
        "contacts":[{
            "contact_id":person["contact_id"],"name":person["name"],
            "organization":person["organization"],
            "responsibility":person["responsibility"],
            "valid_from":person["valid_from"],"valid_until":person["valid_until"],
        } for person in data["contacts"]],
        "preferred_timezone":clock,
        "current_reference_state":status,
        "source_changed":status=="NEEDS_REVIEW",
        "current_source_count":len(latest["matched_sources"]),
        "source_selection_available":True,"available_sources":_available_sources(db,data),
        "execution_namespace":NS,"data_version":data["dataset_version"],
        "revisions":revisions,"read_only":True,
        "source_type":"SIMULATED",
    }
