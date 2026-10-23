import json

from aiohttp import web

from business import require
from boss_bi_scenarios import BIScenarioAPI
from boss_simulation_api import _context
from boss_source_policy import source_validity


def source_option(store, db, context, identifier):
    document = store.get(db,context["namespace"],"document",identifier)
    require(document["source_type"] == "SIMULATED" and document["access_scope"] == context["owner_id"],
            "场景来源不属于当前本人范围",web.HTTPForbidden)
    return {"source_id":identifier,"version":document["version"],"business_basis":document.get("business_basis"),
        "author_kind":document.get("author_kind"),"author_display_name":document.get("author_display_name"),
        "allowed_use":document.get("allowed_use"),"validity_state":source_validity(document,context["clock"])}


def loaded_scenarios(store, role):
    require(role in ("BOSS","MAINTAINER"),"身份尚未认证",web.HTTPUnauthorized)
    with store.connect() as db:
        db.execute("BEGIN")
        context = _context(db)
        rows = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='bi_scenario' ORDER BY id",(context["namespace"],))]
        result = []
        for row in rows:
            if not all(row[field] == context[field] for field in ("owner_id","dataset_id","dataset_version")) or row["execution_namespace"] != context["namespace"]:
                continue
            result.append({key:row[key] for key in ("scenario_id","version","source_ids","generator_version","seed","manifest_sha256","allowed_use")}
                | {"record_count":len(row["records"]),"sources":[source_option(store,db,context,identifier) for identifier in row["source_ids"]]})
        return {"source_type":"SIMULATED","scenarios":result}


def maintainer_catalog(store, role):
    catalog = BIScenarioAPI(store).catalog(role)
    return {**catalog,"loaded_scenarios":loaded_scenarios(store,role)["scenarios"]}


def dimension_options(store, role, result):
    require(role == "BOSS","当前身份不能读取经营维度",web.HTTPForbidden)
    with store.connect() as db:
        db.execute("BEGIN")
        context = _context(db)
        return {**result,"source_options":[source_option(store,db,context,identifier) for identifier in result.get("source_ids",[result["source_id"]])]}
