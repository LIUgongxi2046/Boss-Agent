import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from nanobot.agent.tools.context import RequestContext
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_execution_scope import NAMESPACE
from boss_memory_runtime import OwnerMemoryContext
from boss_page_api import BossPageAPI
from boss_simulation_api import KINDS, SimulationAPI
from controls import ControlStore
from connection import settings
from product_bi import BI_TOOLS, FeatureBusinessTool, FeatureProvider, FeatureRecorder, FeatureToolRegistry, ProductBI
from product_fc01 import ProductFc01
from product_runtime import ProductRuntime
from sop_write_tools.fc01 import Fc01Tool, TOOLS


async def run_native_query(store, initial):
    settings()
    native_root = store.path.parent / "native" / NAMESPACE
    native_root.mkdir(parents=True)
    configuration = Config.model_validate({"agents": {"defaults": {
        "workspace": str(native_root / "workspace"), "provider": "deepseek", "model": "deepseek-flash",
        "maxToolIterations": 12, "maxTokens": 700, "maxToolResultChars": 200000,
        "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
        "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com"}}})
    path = native_root / "config.json"
    save_config(configuration, path)
    config = load_config(path)
    fc01, bi = ProductFc01(store), ProductBI(store)
    provider, registry = FeatureProvider(fc01, bi), FeatureToolRegistry()
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi)
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    tools = [FeatureBusinessTool(store, fc01, bi, name) if name in BI_TOOLS else Fc01Tool(store, fc01.context_provider, name)
             for name in sorted(TOOLS)]
    runtime = ProductRuntime(store, path, loop, registry, tools, provider)
    fc01.runtime = bi.runtime = runtime
    assert loop.sessions.sessions_dir.is_relative_to(native_root / "sessions")
    session = loop.sessions.get_or_create("sdk:namespace-owner")
    session.add_message("user", "请保存这次经营核查的会话。")
    loop.sessions.save(session, fsync=True)
    commands, pages = BossCommandAPI(store, runtime), BossPageAPI(store, runtime_control=runtime)
    inspection_request = {"client_request_id": str(uuid4()), "expected_namespace": NAMESPACE}
    status, inspection = commands.execute("MAINTAINER", "boss.technical.datasets.inspect-reset", inspection_request)
    assert status == 200, inspection
    impact = inspection["result"]
    assert impact["sessions"] == 1 and impact["memories"] == 1 and impact["tasks"] == 0
    assert impact["plans"] == 0 and impact["outbox"] == 0 and impact["active_runs"] == 0
    assert "请保存" not in json.dumps(inspection, ensure_ascii=False)
    assert commands.execute("MAINTAINER", "boss.technical.datasets.inspect-reset", inspection_request) == (status, inspection)
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/datasets")[1]["reset_impact"]["state"] == "CURRENT"
    session.add_message("user", "继续检查当前期间的经营资料。")
    loop.sessions.save(session, fsync=True)
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/datasets")[1]["reset_impact"]["state"] == "STALE"
    request_id = str(uuid4())
    async with Nanobot(loop, config=config) as bot:
        bi.bot = bot
        for context in (runtime.context, bi.scope_context, OwnerMemoryContext(store), recorder.context):
            bot.runtime.add_context_provider(context)
        receipt = await bi.execute("BOSS", {"client_request_id": request_id, "question": "读取当前执行空间经营指标与来源",
            "scope": {"metric_ids": ["sales_quantity", "revenue", "gross_profit"], "region_id": "region-1",
                "product_ids": ["product-1", "product-2"], "legal_entity_id": "entity-1",
                "period_start": initial["periods"]["CURRENT"][0], "period_end": initial["periods"]["CURRENT"][1],
                "comparison_start": initial["periods"]["BASE"][0], "comparison_end": initial["periods"]["BASE"][1],
                "currency": "CNY", "quantity_unit": "tonne", "trade_scope": "EXTERNAL_SALES", "definition_version": "1",
                "business_basis": "SELECTION_REPORTED", "settlement_state": "SETTLED"}}, False, lambda: True)
    await runtime.close()
    assert receipt["request_state"] == "SUCCEEDED", receipt
    assert ProductBI(ControlStore(store.path)).receipt("BOSS", request_id) == receipt
    with store.connect() as db:
        run = store.get(db, NAMESPACE, "runtime_run", receipt["run_id"])
        assert run["status"] == "SUCCEEDED" and run["usage"] is None and run["cost_total"] is None
        assert [item["tool_id"] for item in run["tool_results"]] == ["query_metrics", "read_evidence"]
        query = receipt["receipt"]["query"]["result"]
        assert query["envelope"]["execution_namespace"] == NAMESPACE
        assert query["envelope"]["dataset_id"] == initial["dataset_id"]
    return receipt["run_id"]


def main():
    store = ControlStore(Path(sys.argv[1]))
    assert NAMESPACE == sys.argv[2]
    pages, api = BossPageAPI(store), BossCommandAPI(store)
    dataset = pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/datasets")
    assert dataset[0] == 200, dataset
    assert dataset[1]["current"]["namespace"] == NAMESPACE
    assert dataset[1]["current"]["dataset_id"] == sys.argv[3]
    status, original = pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/datasets/requests/" + sys.argv[4])
    assert status == 200 and original["request_id"] == sys.argv[4], original
    assert original["action"] == "generate" and original["result"]["dataset_id"] == sys.argv[3]
    assert pages.serve("BOSS", "/api/boss/ui/admin/technical/datasets/requests/" + sys.argv[4])[0] == 403
    for role in ("BOSS", "MAINTAINER"):
        for interface in KINDS:
            service = SimulationAPI(store)
            read = service.query if role == "BOSS" else service.inspect
            result = read(role, {"interface_id": interface, "object_ids": [], "filters": {}})
            assert result["execution_namespace"] == NAMESPACE
    paths = ["/api/boss/ui/owner/personal-memory", "/api/boss/ui/workspace/memory",
             "/api/boss/ui/workspace/calendar", "/api/boss/ui/today", "/api/boss/ui/metrics", "/api/boss/ui/meetings"]
    for path in paths:
        status, result = pages.serve("BOSS", path)
        assert status == 200, (path, status, result)
    memory = pages.serve("BOSS", paths[0])[1]
    assert memory["current"] is None and memory["adoption"] == []
    assert pages.serve("BOSS", "/api/boss/ui/workspace/calendar")[1]["calendar"] is None
    admin = pages.serve("MAINTAINER", "/api/boss/ui/admin/memory-status")
    assert admin[0] == 200 and admin[1]["memory"]["confirmation_state"] == "ABSENT", admin
    request = RequestContext(channel="cli", chat_id=str(uuid4()), session_key=str(uuid4()), sender_id="boss-1")
    context = asyncio.run(OwnerMemoryContext(store)(request))
    assert json.loads(context.content)["memory"] is None
    assert request.attributes["boss_memory_reference"] is None
    status, receipt = api.execute("BOSS", "boss.owner_workspace.personal-memory.confirm", {
        "client_request_id": str(uuid4()), "expected_version": "0", "expected_candidate_version": "0", "confirmation": True,
        "values": {"text": "请采用当前执行空间的获准经营资料。", "source_note": "本人在独立模拟空间输入", "visibility": "BOSS_ONLY", "valid_until": None},
    })
    assert status == 200, receipt
    assert receipt["result"]["version"] == "1"
    context = asyncio.run(OwnerMemoryContext(store)(request))
    assert json.loads(context.content)["memory"]["version"] == "1"
    assert request.attributes["boss_memory_reference"]["eligible"] is True
    with store.connect() as db:
        initial = store.get(db, NAMESPACE, "initial", "snapshot")
        clock = store.get(db, NAMESPACE, "clock", "current")["at"]
    status, calendar = api.execute("BOSS", "boss.calendar.save", {
        "client_request_id": str(uuid4()), "expected_version": "0", "starts_at": clock[:10] + "T18:00:00+08:00",
        "ends_at": clock[:10] + "T19:00:00+08:00", "timezone": "Asia/Shanghai", "title": "本人安排",
        "private_body": "本人在独立空间保存的私人安排", "location": "", "attachment_refs": [], "acknowledge_conflict": True,
    })
    assert status == 200 and calendar["version"] == "1", calendar
    assert pages.serve("BOSS", "/api/boss/ui/workspace/calendar")[1]["calendar"]["version"] == "1"
    result = store.invoke("query_metrics", {"envelope": {"request_id": str(uuid4()), "session_id": "scope-query",
        "execution_namespace": NAMESPACE, "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"]},
        "question": "读取当前数据集的同范围经营指标", "metric_ids": ["sales_quantity", "revenue", "cost", "gross_profit"],
        "region_id": "region-1", "product_ids": ["product-1", "product-2"], "period_start": initial["periods"]["CURRENT"][0],
        "period_end": initial["periods"]["CURRENT"][1], "comparison_start": initial["periods"]["BASE"][0],
        "comparison_end": initial["periods"]["BASE"][1], "currency": "CNY", "trade_scope": "EXTERNAL_SALES", "definition_version": "1"})
    assert result["query_id"]
    run_id = asyncio.run(run_native_query(store, initial))
    print(json.dumps({"namespace": NAMESPACE, "interfaces": len(KINDS), "empty_owner_state": "VERIFIED",
                      "owner_memory_and_calendar": "RECORDED", "query_id": result["query_id"], "native_run_id": run_id}))


if __name__ == "__main__":
    main()
