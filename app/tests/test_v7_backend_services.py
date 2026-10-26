import asyncio
import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from aiohttp import web
from docx import Document
from nanobot.cron.service import CronService

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_scheduler_runtime import BossSchedulerRuntime
from boss_v7_configuration import builtin_tool
from boss_v7_knowledge import VISIBILITY
from boss_v7_models import ModelConnections
from boss_v7_metrics import METRICS, builtin_metric
from boss_bi_queries import BIQueryAPI
from boss_meeting_brief import compile_brief
from boss_business_overview import BusinessOverviewAPI
from boss_alert_policy import MANIFEST as ALERT_MANIFEST
from business import encode
from controls import ControlStore
from model_probe import BusinessTool


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "v7.sqlite")
    store.initialize("ui-check")
    return store, BossCommandAPI(store), BossPageAPI(store)


def write(api, domain, action, values, role="MAINTAINER", request_id=None):
    return api.execute(role, "boss.technical." + domain + "." + action,
                       {"client_request_id": request_id or str(uuid4()), **values})


def read(pages, domain, role="MAINTAINER"):
    status, result = pages.serve(role, "/api/boss/ui/admin/technical/" + domain)
    assert status == 200, result
    return result


def model_values(store):
    with store.connect() as db:
        current = store.get(db, "ui-check", "configuration", "current")
    return {"provider": current["provider"], "api_type": current["api_type"], "model_id": current["model_id"],
            "credential_reference": "DEEPSEEK_API_KEY", "timeout_seconds": current["timeout"],
            "max_tool_rounds": current["max_tool_rounds"], "pricing_version": "UNVERIFIED",
            "capabilities": ["TEXT", "TOOL_CALLING", "STREAMING"], "change_note": "采用当前运行配置建立待验证连接"}


def test_model_draft_history_receipt_and_configuration_are_separate(services):
    store, api, pages = services
    initial = read(pages, "models")
    assert initial["runtime_mode"] == "SIMULATED_FIRST"
    assert initial["connections"] == [] and initial["adoption"] == []
    values = model_values(store)
    request_id = str(uuid4())
    payload = {"object_id": None, "expected_version": "0", "values": values}
    code, receipt = write(api, "models", "save", payload, request_id=request_id)
    assert code == 200, receipt
    assert write(api, "models", "save", payload, request_id=request_id) == (200, receipt)
    identifier = receipt["result"]["object_id"]
    after = read(pages, "models")
    assert after["configuration_version"] == initial["configuration_version"]
    assert after["active_connection_id"] is None and after["active_run_count"] == 0
    draft = after["connections"][0]["draft"]
    assert draft["version"] == "1" and draft["validation"] is None
    assert sorted(draft["values"]["capabilities"]) == sorted(values["capabilities"])
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/models/requests/" + request_id) == (200, receipt)
    updated = {**values, "change_note": "记录新的连接说明"}
    code, result = write(api, "models", "save", {"object_id": identifier, "expected_version": "1", "values": updated})
    assert code == 200, result
    assert result["result"]["version"] == "2"
    assert write(api, "models", "save", {"object_id": identifier, "expected_version": "1", "values": values})[0] == 409
    item = read(pages, "models")["connections"][0]
    assert item["draft"]["values"]["change_note"] == updated["change_note"]
    assert item["history"][0]["values"]["change_note"] == values["change_note"]
    ModelConnections(store).recover()
    assert read(pages, "models")["connections"][0] == item
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='model_connection_validation'").fetchone()[0] == 0


def test_model_role_credential_reference_and_runtime_guards(services):
    store, api, pages = services
    values = model_values(store)
    payload = {"object_id": None, "expected_version": "0", "values": values}
    assert pages.serve("BOSS", "/api/boss/ui/admin/technical/models")[0] == 403
    assert write(api, "models", "save", payload, role="BOSS")[0] == 403
    invalid = {**payload, "values": {**values, "credential_reference": "OPENAI_API_KEY"}}
    assert write(api, "models", "save", invalid)[0] == 400
    assert read(pages, "models")["connections"] == []
    assert write(api, "models", "save", payload)[0] == 200
    item = read(pages, "models")["connections"][0]
    version = {"object_id": item["id"], "expected_version": item["draft"]["version"],
               "expected_content_sha256": item["draft"]["content_sha256"]}
    assert write(api, "models", "validate", {**version, "external_request_confirmed": True})[0] == 503
    assert write(api, "models", "cancel", version)[0] == 409
    assert read(pages, "models")["connections"][0]["draft"]["validation"] is None
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='model_connection_active'").fetchone()[0] == 0


def metric_query(store, scoped=True):
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
    fields = {"envelope": {"request_id": str(uuid4()), "session_id": str(uuid4()), "owner_id": data["owner_id"],
                          "execution_namespace": "ui-check", "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"]},
              "question": "读取当前获准经营资料的计算结果", "region_id": "region-1", "product_ids": ["product-1", "product-2"],
              "period_start": data["periods"]["CURRENT"][0], "period_end": data["periods"]["CURRENT"][1],
              "comparison_start": data["periods"]["BASE"][0], "comparison_end": data["periods"]["BASE"][1],
              "currency": "CNY", "trade_scope": "EXTERNAL_SALES", "definition_version": "1", "metric_ids": list(METRICS)}
    if scoped:
        fields.update(query_mode="SCOPED", legal_entity_id=data["details"][0]["legal_entity_id"], quantity_unit="tonne",
                      business_basis="SELECTION_REPORTED", settlement_state="SETTLED")
    return fields


def metric_values(identifier, precision=3):
    return {**builtin_metric(identifier)["values"], "precision": precision, "refresh_seconds": 120,
            "effective_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            "dimensions": ["product_id"], "scope": "EXTERNAL_SALES_SETTLED", "change_note": "采用当前明细独立复算并核查查询版本"}


@pytest.mark.parametrize("scoped", [True, False])
def test_metric_configurations_recompute_query_cache_and_preserve_raw_values(services, scoped):
    store, api, pages = services
    before = store.invoke("query_metrics", metric_query(store, scoped))
    for identifier in METRICS:
        activate_configuration(api, pages, "metrics", metric_values(identifier), identifier)
    query = store.invoke("query_metrics", metric_query(store, scoped))
    assert {(row["metric_id"], row["period_scope"]): Decimal(row["value"]) if row["value"] is not None else None for row in query["values"]} == {
        (row["metric_id"], row["period_scope"]): Decimal(row["value"]) if row["value"] is not None else None for row in before["values"]}
    assert all("ROUND_HALF_UP(3)" in row["display_rounding"] for row in query["values"] if row["period_scope"] != "CHANGE")
    with store.connect() as db:
        binding = store.get(db, "ui-check", "query_source_binding", query["query_id"])
        first = binding["metric_calculations"]["CURRENT"]["gross_margin"]
        assert first["configuration_version"] == "1"
        assert first["scope"] == "EXTERNAL_SALES_SETTLED"
        assert {tuple(row["dimensions"]) for row in first["breakdown"]} == {("product_id",)}
        count = db.execute("SELECT count(*) FROM objects WHERE kind='metric_calculation'").fetchone()[0]
    repeated = store.invoke("query_metrics", metric_query(store, scoped))
    with store.connect() as db:
        next_binding = store.get(db, "ui-check", "query_source_binding", repeated["query_id"])
        assert next_binding["metric_calculations"] == binding["metric_calculations"]
        assert db.execute("SELECT count(*) FROM objects WHERE kind='metric_calculation'").fetchone()[0] == count
        data = store.get(db, "ui-check", "initial", "snapshot")
        brief = compile_brief(db, data)
        assert compile_brief(db, data) == brief
        assert brief["metrics"]["values"][0]["metric_configurations"]["gross_margin"]["configuration_version"] == "1"
    uses = read(pages, "metrics")["uses"]
    assert any(row["run_id"] == query["query_id"] + ":CURRENT" and row["details"] == first for row in uses)
    with pytest.raises(web.HTTPConflict):
        store.invoke("read_evidence", {"envelope": metric_query(store, scoped)["envelope"], "query_id": before["query_id"],
                                      "detail_refs": before["detail_refs"], "source_ids": [row["source_id"] for row in before["sources"]]})
    if scoped:
        assert BIQueryAPI(store).read("BOSS", before["query_id"], historical=True)["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"


def test_metric_future_effective_version_and_formula_validation(services):
    store, api, pages = services
    identifier = "gross_margin"
    values = metric_values(identifier)
    assert write(api, "metrics", "save", {"object_id": identifier, "expected_version": "0", "values": {**values, "formula": METRICS["revenue"][1]}})[0] == 400
    future = {**values, "effective_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}
    activate_configuration(api, pages, "metrics", future, identifier)
    result = store.invoke("query_metrics", metric_query(store))
    assert all("ROUND_HALF_UP" not in row["display_rounding"] for row in result["values"])
    assert read(pages, "metrics")["uses"] == []
    activate_configuration(api, pages, "metrics", values, identifier)
    fresh = store.invoke("query_metrics", metric_query(store))
    assert all("配置v2" in row["display_rounding"] for row in fresh["values"] if row["metric_id"] == identifier and row["period_scope"] != "CHANGE")


def test_metric_overview_and_alert_observation_use_current_configuration(services):
    store, api, pages = services
    values = metric_values("gross_margin")
    activate_configuration(api, pages, "metrics", values, "gross_margin")
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
    scope = {"legal_entity_id": data["details"][0]["legal_entity_id"], "region_id": None,
             "period_start": data["periods"]["CURRENT"][0], "period_end": data["periods"]["CURRENT"][1],
             "timezone": data["boss_profile"]["timezone"], "attention": "ALL"}
    overview = BusinessOverviewAPI(store)
    first = overview.read("BOSS", scope)
    assert overview.read("BOSS", scope)["snapshot_sha256"] == first["snapshot_sha256"]
    metric = next(row for row in first["metrics"] if row["metric_id"] == "gross_margin")
    assert metric["metric_configuration"]["configuration_version"] == "1"
    code, loaded = api.execute("MAINTAINER", "boss.simulation.alert.load", {
        "client_request_id": str(uuid4()), "expected_version": "0", "mode": "SIMULATED",
        "definition_version": ALERT_MANIFEST["definition_version"], "seed": ALERT_MANIFEST["seed"], "frame": "RESOURCE_SHORTAGE"})
    assert code == 200, loaded
    code, alerts = pages.serve("BOSS", "/api/boss/ui/business-alerts")
    assert code == 200 and alerts["items"][0]["adoption_state"] == "CURRENT"
    activate_configuration(api, pages, "metrics", metric_values("gross_margin", precision=2), "gross_margin")
    code, stale = pages.serve("BOSS", "/api/boss/ui/business-alerts")
    assert code == 200 and stale["items"][0]["adoption_state"] == "NEEDS_REVIEW"
    assert stale["items"][0]["facts"] is None
    assert any(row["status"] == "NEEDS_REIMPORT" for row in stale["items"][0]["sources"])


def activate_configuration(api, pages, domain, values, identifier):
    before = next(item for item in read(pages, domain)["items"] if item["id"] == identifier)
    status, saved = write(api, domain, "save", {"object_id": identifier, "expected_version": before["draft"]["version"] if before["draft"] else "0", "values": values})
    assert status == 200, saved
    item = next(item for item in read(pages, domain)["items"] if item["id"] == identifier)
    version = {"object_id": identifier, "expected_version": item["draft"]["version"],
               "expected_content_sha256": item["draft"]["content_sha256"], "expected_active_version": item["current"]["version"] if item["current"] else "0"}
    assert write(api, domain, "validate", version)[0] == 200
    status, result = write(api, domain, "activate", version)
    assert status == 200, result
    return result


@pytest.mark.parametrize("extension", [".txt", ".md", ".docx"])
def test_uploaded_repository_text_is_indexed_versioned_and_withdrawn(services, extension):
    store, api, pages = services
    content = (ROOT / "docs/development/V7-BACKEND.md").read_text()
    if extension == ".docx":
        document = Document()
        document.add_paragraph(content)
        stream = BytesIO()
        document.save(stream)
        raw = stream.getvalue()
    else:
        raw = content.encode()
    identifier = "sim-doc-" + uuid4().hex
    fields = {"source_id": identifier, "expected_version": "0", "confirmation": True, "text": "",
              "upload": {"name": "development" + extension, "mime_type": "application/octet-stream", "size": len(raw), "content_base64": base64.b64encode(raw).decode()},
              "values": {"source_id": identifier, "title": "获准项目开发资料", "author_id": "coordinator-1", "observed_at": "2026-10-20",
                         "published_at": "2026-10-20", "valid_until": "2027-01-01", "visibility": VISIBILITY, "change_note": "摄取当前仓库文档用于知识索引核查"}}
    request_id = str(uuid4())
    status, receipt = write(api, "knowledge", "ingest", fields, request_id=request_id)
    assert status == 200, receipt
    assert write(api, "knowledge", "ingest", fields, request_id=request_id) == (status, receipt)
    assert write(api, "knowledge", "ingest", fields, role="BOSS")[0] == 403
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/knowledge/requests/" + request_id) == (status, receipt)
    source = next(row for row in read(pages, "knowledge")["sources"] if row["id"] == identifier)
    assert source["version"] == "1" and source["original_available"]
    query = urlencode({"query": "CronService"})
    status, result = pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/knowledge/search", query)
    assert status == 200
    hit = next(row for row in result["hits"] if row["source_id"] == identifier)
    with store.connect() as db:
        stored = store.get(db, "ui-check", "document", identifier)
        assert hit["excerpt"] == stored["content"][hit["start"]:hit["end"]]
        upload = store.get(db, "ui-check", "knowledge_upload", identifier + ":v1")
        assert base64.b64decode(upload["content_base64"]) == raw
    matches = store.control("ui-check", "search", {"query": '"V7"'})
    assert identifier in {row["source_id"] for row in matches["results"]}
    changed = {**fields, "expected_version": "1", "upload": None, "text": content + "\n当前来源版本更新。"}
    assert write(api, "knowledge", "revise", changed)[0] == 200
    assert write(api, "knowledge", "revise", changed)[0] == 409
    assert write(api, "knowledge", "withdraw", {**changed, "expected_version": "2"})[0] == 200
    assert identifier not in {row["source_id"] for row in pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/knowledge/search", query)[1]["hits"]}
    with store.connect() as db:
        assert store.get(db, "ui-check", "document_revision", identifier + ":v1")["version"] == "1"
        assert all("content_base64" not in row[0] for row in db.execute("SELECT input FROM audit"))


def test_access_configuration_controls_current_and_existing_knowledge_routes(services):
    store, api, pages = services
    at = datetime.now(timezone.utc)
    values = {"name": "知识只读访问", "subject_id": "MAINTAINER", "object_scopes": ["knowledge"], "permissions": ["READ"],
              "valid_from": (at - timedelta(minutes=1)).isoformat(), "valid_until": (at + timedelta(days=1)).isoformat(), "change_note": "检查当前技术访问限制"}
    activate_configuration(api, pages, "access", values, "maintainer-access")
    assert read(pages, "knowledge")["projection"] == "knowledge"
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/relationships")[0] == 403
    assert api.execute("MAINTAINER", "boss.knowledge.source.create", {"client_request_id": str(uuid4())})[0] == 403
    assert read(pages, "access")["uses"]
    assert pages.serve("MAINTAINER", "/api/boss/ui/owner/personal-memory")[0] == 403
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_tool_definition_is_consumed_by_native_tool_and_business_validation(services):
    store, api, pages = services
    values = builtin_tool("query_metrics")["values"]
    values.update(description="按当前获准明细计算指标并保留查询依据。", change_note="核查原生工具采用")
    activate_configuration(api, pages, "tools", values, "query_metrics")
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
    envelope = {"request_id": str(uuid4()), "owner_id": data["owner_id"], "execution_namespace": "ui-check", "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"], "session_id": str(uuid4())}
    tool = BusinessTool("query_metrics", store, envelope, {}, [])
    assert tool.description == values["description"]
    fields = {"question": "查询当前获准经营指标及其比较期间", "region_id": "region-1", "product_ids": ["product-1", "product-2"], "period_start": data["periods"]["CURRENT"][0], "period_end": data["periods"]["CURRENT"][1],
              "comparison_start": data["periods"]["BASE"][0], "comparison_end": data["periods"]["BASE"][1], "currency": "CNY", "trade_scope": "EXTERNAL_SALES", "definition_version": "1",
              "metric_ids": [row["metric_id"] for row in data["metric_definitions"]]}
    result = json.loads(asyncio.run(tool.execute(**fields)))
    assert result["query_id"]
    adoption = read(pages, "tools")["uses"]
    assert any(row["object_id"] == "query_metrics" and row["run_id"] == envelope["request_id"] and row["version"] == "1" for row in adoption)


def test_owner_memory_confirmation_expiry_and_deletion_use_current_state(services):
    store, api, pages = services
    path = "/api/boss/ui/owner/personal-memory"
    current = pages.serve("BOSS", path)[1]["current"]
    fields = {"client_request_id": str(uuid4()), "expected_version": current["version"], "expected_candidate_version": "0", "confirmation": True,
              "values": {"text": current["text"], "source_note": "采用当前本人已确认要求", "visibility": "BOSS_ONLY", "valid_until": "2026-10-23T00:00:00+08:00"}}
    status, result = api.execute("BOSS", "boss.owner_workspace.personal-memory.confirm", fields)
    assert status == 200, result
    assert pages.serve("BOSS", path)[1]["current"]["state"] == "CONFIRMED"
    store.control("ui-check", "clock", {"at": "2026-10-23T09:00:00+08:00"})
    assert pages.serve("BOSS", path)[1]["current"]["state"] == "NOT_EFFECTIVE"
    record = next(row for row in pages.serve("BOSS", "/api/boss/ui/owner/authorizations")[1]["records"] if row["authorization_id"] == result["result"]["authorization_id"])
    assert record["effective_state"] == "NOT_EFFECTIVE"
    status, deleted = api.execute("BOSS", "boss.owner_workspace.personal-memory.delete", {"client_request_id": str(uuid4()), "expected_version": "2", "expected_candidate_version": "0", "confirmation": True})
    assert status == 200, deleted
    after = pages.serve("BOSS", path)[1]
    assert after["current"]["text"] == "" and all(not row["text"] for row in after["history"])


def test_native_cron_service_consumes_scope_and_restart_policy(services, tmp_path):
    store, api, pages = services
    def command(action, **payload):
        status, result = api.execute("MAINTAINER", "boss.scheduler." + action, {"client_request_id": str(uuid4()), **payload})
        assert status == 200, result
        return result
    command("draft.save", expected_version="0", trigger="EVENT", timezone="Asia/Shanghai", quiet_start=22, quiet_end=7,
            cooldown_seconds=1800, important_escalation=False, name="获准事件检查", executor_component="CronService", expression="",
            authorized_scope=["SIMULATED_EVENTS"], restart_policy="PAUSE_ON_RESTART")
    command("draft.validate", expected_version="1")
    command("activate", expected_draft_version="2", expected_schedule_version="1", expected_rules_version="0")
    with store.connect() as db:
        event = store.get(db, "ui-check", "initial", "snapshot")["event"]
    store.control("ui-check", "event", {"event_id": event["event_id"], "version": "1", "state": "OPEN", "impact": "NORMAL", "due_at": event["due_at"]})
    store.control("ui-check", "clock", {"at": event["due_at"]})
    async def observe():
        cron = CronService(tmp_path / "cron/jobs.json", max_sleep_ms=100)
        runtime = BossSchedulerRuntime(store, cron)
        store.scheduler_runtime = runtime
        cron.on_job = runtime.on_job
        await cron.start()
        try:
            runtime.start()
            projection = pages.serve("MAINTAINER", "/api/boss/ui/workspace/scheduler")[1]
            assert projection["schedule"]["enabled"] is False
            assert projection["runtime"]["state"] == "RUNNING"
            command("resume", expected_version=projection["schedule"]["version"])
            deadline = asyncio.get_running_loop().time() + 5
            observed = []
            while not observed and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.1)
                with store.connect() as db:
                    observed = db.execute("SELECT body FROM objects WHERE kind='notification'").fetchall()
            assert observed
            assert json.loads(observed[0][0])["event_id"] == event["event_id"]
            assert runtime.checked_at is not None
        finally:
            cron.stop()
    asyncio.run(observe())


def test_local_system_reports_available_observations_without_installation_claims(services):
    _, _, pages = services
    local = read(pages, "local-system")
    assert local["upstream_version"] == "0.3.5"
    assert local["service"]["state"] == "SERVICE_CONTEXT_NOT_ATTACHED"
    assert local["service"]["scheduler_state"] == "NOT_ATTACHED"
    assert local["desktop"]["auto_start"] is None
    assert local["installations"] == [] and local["backups"] == []
    assert pages.serve("BOSS", "/api/boss/ui/admin/technical/local-system")[0] == 403
