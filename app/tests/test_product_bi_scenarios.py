import asyncio
from decimal import Decimal

import pytest
from aiohttp import web
from nanobot import Nanobot

from test_product_bi_runtime import product_bi, payload, validate_public_output
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from business import checksum


ACTION = "boss.simulation.bi_scenario.load"


def load_payload(identifier):
    return {"client_request_id":"public-load-"+identifier,"mode":"SIMULATED","scenario_id":identifier,
            "generator_version":"FC02-BI-1","seed":20261024,"expected_version":"0"}


def test_maintainer_public_scenario_catalog_load_receipt_and_permissions(product_bi):
    store, bi, runtime, recorder, config = product_bi
    pages, commands = BossPageAPI(store), BossCommandAPI(store)
    with store.connect() as db:
        initial = checksum(store.get(db,"ui-check","initial","snapshot"))
    status, catalog = pages.serve("MAINTAINER","/api/boss/ui/admin/bi-scenarios")
    assert status == 200
    validate_public_output("ScenarioCatalog",catalog)
    validate_public_output("Dimensions",bi.serve("BOSS","/api/boss/ui/bi/dimensions",""))
    unknown = pages.serve("MAINTAINER","/api/boss/ui/admin/bi-scenario-receipt","client_request_id=public-unknown-load")
    assert unknown[0] == 200 and unknown[1]["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    validate_public_output("ScenarioLoadReceipt",unknown[1])
    assert catalog["generator_version"] == "FC02-BI-1" and len(catalog["scenarios"]) == 6
    for role, expected in ((None,401),("BOSS",403)):
        assert pages.serve(role,"/api/boss/ui/admin/bi-scenarios")[0] == expected
        assert commands.execute(role,ACTION,load_payload("weighted-ratios"))[0] == expected
    for identifier in catalog["scenarios"]:
        request = load_payload(identifier)
        code, result = commands.execute("MAINTAINER",ACTION,request)
        assert code == 200 and result["scenario_id"] == identifier and result["external_service_invoked"] is False
        assert commands.execute("MAINTAINER",ACTION,request) == (code,result)
        status, receipt = pages.serve("MAINTAINER","/api/boss/ui/admin/bi-scenario-receipt","client_request_id="+request["client_request_id"])
        assert status == 200 and receipt["outcome"] == "RECORDED" and receipt["result"] == result
        validate_public_output("ScenarioLoadReceipt",receipt)
    loaded = bi.serve("BOSS","/api/boss/ui/bi/scenarios","")
    assert len(loaded["scenarios"]) == 6
    validate_public_output("ScenarioList",loaded)
    validate_public_output("ScenarioCatalog",pages.serve("MAINTAINER","/api/boss/ui/admin/bi-scenarios")[1])
    dimensions = bi.serve("BOSS","/api/boss/ui/bi/dimensions","scenario_id=weighted-ratios")
    assert dimensions["scenario_id"] == "weighted-ratios" and dimensions["source_options"][0]["business_basis"] == "SIMULATED_BOUNDARY"
    validate_public_output("Dimensions",dimensions)
    with store.connect() as db:
        assert checksum(store.get(db,"ui-check","initial","snapshot")) == initial
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('task','authorization','outbox')").fetchone()[0] == 0
    for invalid in ("scenario_id=weighted-ratios&owner_id=other","scenario_id=weighted-ratios&scenario_id=other"):
        with pytest.raises(web.HTTPBadRequest):
            bi.serve("BOSS","/api/boss/ui/bi/dimensions",invalid)


def test_formal_scenarios_execute_in_actual_public_runtime_and_keep_frozen_context(product_bi):
    store, bi, runtime, recorder, config = product_bi
    commands = BossCommandAPI(store)
    identifiers = ["weighted-ratios","zero-denominators","missing-numbers","delayed-records","unsynchronized-records","basis-conflict"]
    for identifier in identifiers:
        assert commands.execute("MAINTAINER",ACTION,load_payload(identifier))[0] == 200
    async def execute():
        results = {}
        async with Nanobot(runtime.loop,config=config) as bot:
            bi.bot = bot
            for provider in (runtime.context,bi.scope_context,recorder.context):
                bot.runtime.add_context_provider(provider)
            for identifier in identifiers:
                bases = ["FINANCIAL_REPORTED","BUSINESS_REPORTED"] if identifier == "basis-conflict" else ["SIMULATED_BOUNDARY"]
                for basis in bases:
                    request = payload("public-"+identifier+"-"+basis,scenario_id=identifier,source_ids=["sim-bi:"+identifier+":"+basis],business_basis=basis)
                    result = await bi.execute("BOSS",request,False,lambda:True)
                    assert result["request_state"] == "SUCCEEDED"
                    query = result["receipt"]["query"]["result"]
                    assert query["context_snapshot"]["scenario_id"] == identifier and query["sources"][0]["source_id"] == request["scope"]["source_ids"][0]
                    evidence = BossPageAPI(store).serve("BOSS","/api/boss/ui/metrics-evidence","query_id="+query["query_id"])
                    assert evidence[0] == 200 and any(row["record_id"] == query["sources"][0]["source_id"] for row in evidence[1]["result"]["original_records"])
                    results[identifier,basis] = query
            parent = results["basis-conflict","FINANCIAL_REPORTED"]
            follow = await bi.execute("BOSS",{"client_request_id":"public-basis-follow-up","parent_query_id":parent["query_id"],"question":"继续读取业务口径",
                "overrides":{"business_basis":"BUSINESS_REPORTED","source_ids":["sim-bi:basis-conflict:BUSINESS_REPORTED"]}},True,lambda:True)
            assert follow["receipt"]["query"]["result"]["parent_query_id"] == parent["query_id"]
            assert follow["receipt"]["query"]["result"]["overridden_fields"] == ["business_basis","source_ids"]
            return results
    results = asyncio.run(execute())
    current = lambda query, metric:next(row["value"] for row in query["values"] if row["metric_id"] == metric and row["period_scope"] == "CURRENT")
    assert Decimal(current(results["weighted-ratios","SIMULATED_BOUNDARY"],"gross_margin")) == Decimal("14")
    assert current(results["zero-denominators","SIMULATED_BOUNDARY"],"gross_margin") is None
    assert current(results["missing-numbers","SIMULATED_BOUNDARY"],"revenue") == "100"
    assert results["delayed-records","SIMULATED_BOUNDARY"]["coverage"]["delayed_regions"] == ["region-1"]
    assert results["unsynchronized-records","SIMULATED_BOUNDARY"]["coverage"]["unsynchronized_regions"] == ["region-1"]
    assert current(results["basis-conflict","FINANCIAL_REPORTED"],"revenue") == "100"
    assert current(results["basis-conflict","BUSINESS_REPORTED"],"revenue") == "120"
    store.control("ui-check","withdraw",{"source_id":"sim-bi:basis-conflict:FINANCIAL_REPORTED","version":"1"})
    dimensions = bi.serve("BOSS","/api/boss/ui/bi/dimensions","scenario_id=basis-conflict&source_ids=sim-bi%3Abasis-conflict%3ABUSINESS_REPORTED")
    assert dimensions["available_dimensions"]["business_basis"] == ["BUSINESS_REPORTED"]
