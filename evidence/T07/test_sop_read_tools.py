import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.skills import SkillsLoader

ROOT=Path(__file__).resolve().parents[2]
PIN="7aab4405b77887b3a2f242dde8c256247c0926f1"
BACKEND=ROOT/".work/w2-checks/sop-read-backend"
sys.path.insert(0,str(BACKEND/"validation"))
sys.path.insert(1,str(ROOT/"validation"))

from business import OPERATIONS
from boss_page_api import BossPageAPI
from boss_command_api import BossCommandAPI
from boss_meetings import MeetingAPI
from controls import ControlStore
from model_probe import BusinessTool
from runtime_page_read_tools import BossDashboardReadTool, BossMeetingsReadTool, BossEvidenceReadTool
from boss_native_skills import BossSkillCatalog

CLASSES=(BossDashboardReadTool,BossMeetingsReadTool,BossEvidenceReadTool)

READ_NAMES={"bossDashboardRead","bossMeetingsRead","bossEvidenceRead"}
CONNECTIONS=[]


def deny_network(event,args):
    if event=="socket.connect":
        CONNECTIONS.append(str(args[1]))
        raise PermissionError("本项检查禁止网络连接")


sys.addaudithook(deny_network)


@pytest.fixture(scope="session",autouse=True)
def verify_actual_imports_and_no_network():
    def hashes():
        result={}
        paths=list((BACKEND/"validation").rglob("*.py"))+[path for path in (BACKEND/"specs").rglob("*") if path.is_file()]
        for path in sorted(paths):
            relative=path.relative_to(BACKEND).as_posix()
            committed=subprocess.check_output(["git","show",PIN+":"+relative],cwd=ROOT)
            assert path.read_bytes()==committed,relative
            result[relative]=hashlib.sha256(committed).hexdigest()
        return result
    before=hashes()
    yield
    assert hashes()==before
    assert CONNECTIONS==[]
    imported={}
    for name,module in tuple(sys.modules.items()):
        source=getattr(module,"__file__",None)
        if source and Path(source).is_relative_to(BACKEND):
            path=Path(source)
            imported[name]={"path":path.relative_to(BACKEND).as_posix(),
                            "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    assert imported["boss_page_api"]["path"]=="validation/boss_page_api.py"
    (ROOT/".work/w2-checks/sop-read-imports.json").write_text(json.dumps({
        "source_files":before,"actual_imports":imported,"socket_connect_attempts":CONNECTIONS},
        ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


@pytest.fixture
def api(tmp_path):
    store=ControlStore(tmp_path/"read-tools.sqlite")
    store.initialize("ui-check")
    return BossPageAPI(store)


@pytest.fixture
def registry(api):
    result=ToolRegistry()
    envelope={"request_id":"w2-formal-read","owner_id":"boss-1","execution_namespace":"ui-check",
              "dataset_id":"selection","dataset_version":"1","session_id":"w2-formal-read"}
    for operation in OPERATIONS:
        result.register(BusinessTool(operation,api.store,envelope,{},[]))
    for tool_class in CLASSES:
        result.register(tool_class(api,"BOSS"))
    return result


def test_three_read_operations_are_present_in_actual_registry(registry):
    assert READ_NAMES<=set(registry.tool_names)
    assert all(registry.get(name).read_only for name in READ_NAMES)


def test_native_sop_catalog_resolves_only_registered_read_operations(api,registry,tmp_path):
    catalog=BossSkillCatalog(SkillsLoader(tmp_path,builtin_skills_dir=ROOT/"agent/skills"),registry)
    before=database(api.store)
    status=catalog.technical_status("MAINTAINER")
    assert database(api.store)==before
    assert len(status["items"])==13 and status["business_authorization_granted"] is False
    items={item["sop_id"]:item for item in status["items"]}
    assert all(not READ_NAMES.intersection(item["missing_tools"]) for item in items.values())
    assert items["SOP03"]["context_eligible"] is True
    for sop_id in ("SOP01","SOP04","SOP05","SOP07","SOP10"):
        assert items[sop_id]["missing_tools"] and items[sop_id]["context_eligible"] is False
        with pytest.raises(web.HTTPConflict):
            catalog.context("BOSS",[sop_id])
    (ROOT/".work/w2-checks/sop-read-catalog.json").write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def database(store):
    with store.connect() as db:
        return tuple(db.iterdump())


def read(registry,api,name,parameters):
    before=database(api.store)
    value=json.loads(asyncio.run(registry.execute(name,parameters)))
    assert database(api.store)==before
    return value


def validate_response(name,value):
    schema=yaml.safe_load(subprocess.check_output(["git","show",PIN+":specs/openapi.yaml"],cwd=ROOT))
    operation=next(item["get"] for item in schema["paths"].values() if item.get("get",{}).get("operationId")==name)
    Draft202012Validator(operation["responses"]["200"]["content"]["application/json"]["schema"]).validate(value)


@pytest.mark.parametrize("name,parameters",[("bossDashboardRead",{}),("bossMeetingsRead",{}),("bossEvidenceRead",{"source":"finance-note"})])
def test_actual_registry_reads_formal_projection_without_writes(api,registry,name,parameters):
    value=read(registry,api,name,parameters)
    validate_response(name,value)
    assert value["source_type"]=="SIMULATED"
    if name=="bossDashboardRead":
        assert value["namespace"]=="ui-check" and value["tasks"]==[] and value["notifications"]==[]
        assert value["profile"]["owner_confirmation"]=="NOT_CONFIRMED" and value["profile"]["goals"]==[]
    elif name=="bossMeetingsRead":
        assert value["meeting"]["meeting_id"]=="meeting-1" and value["meeting"]["version"]=="1"
        assert "draft" not in value and {item["source_id"] for item in value["documents"]}=={"finance-note","meeting-minutes"}
    else:
        assert value["source_id"]=="finance-note" and value["version"]=="1" and "毛利=收入减成本" in value["content"]
    reopened=BossPageAPI(ControlStore(api.store.path))
    registry2=ToolRegistry()
    for tool_class in CLASSES:
        registry2.register(tool_class(reopened,"BOSS"))
    second=read(registry2,reopened,name,parameters)
    assert {key:content for key,content in second.items() if key not in {"read_at","refreshed_at"}}=={
        key:content for key,content in value.items() if key not in {"read_at","refreshed_at"}}


@pytest.mark.parametrize("tool_class",CLASSES)
@pytest.mark.parametrize("role,status",[(None,401),("MAINTAINER",403),("CONTACT",403)])
def test_read_construction_rejects_other_roles(api,tool_class,role,status):
    before=database(api.store)
    with pytest.raises(web.HTTPException) as denied:
        tool_class(api,role)
    assert denied.value.status==status and database(api.store)==before


@pytest.mark.parametrize("name",sorted(READ_NAMES))
@pytest.mark.parametrize("field",["namespace","owner_id","role","envelope","authorization_id","idempotency_key"])
def test_model_cannot_supply_scope_or_authority(registry,name,field):
    arguments={"source":"finance-note"} if name=="bossEvidenceRead" else {}
    _,_,error=registry.prepare_call(name,{**arguments,field:"caller-supplied"})
    assert error


@pytest.mark.parametrize("arguments",[{}, {"source":""},{"source":"a"*101},{"source":None},{"source":[]},{"source":1},{"source":True},{"source":{}},{"source_id":"finance-note"}])
def test_evidence_accepts_only_formal_source_field(registry,arguments):
    _,_,error=registry.prepare_call("bossEvidenceRead",arguments)
    assert error


@pytest.mark.parametrize("tool_class",CLASSES)
def test_server_owner_and_execution_space_remain_bound(api,tool_class):
    params={"source":"finance-note"} if tool_class is BossEvidenceReadTool else {}
    wrong_owner=tool_class(api,"BOSS",owner_id="another-owner")
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(wrong_owner.execute(**params))
    other=BossPageAPI(api.store,namespace="another-space")
    api.store.initialize("another-space")
    before=database(api.store)
    with pytest.raises(web.HTTPConflict):
        asyncio.run(tool_class(other,"BOSS").execute(**params))
    assert database(api.store)==before


@pytest.mark.parametrize("tool_class",CLASSES)
def test_inactive_space_rejected_without_write(api,tool_class):
    api.store.control("ui-check","reset",{"namespace":"w2-next-space"})
    before=database(api.store)
    params={"source":"finance-note"} if tool_class is BossEvidenceReadTool else {}
    with pytest.raises(web.HTTPConflict):
        asyncio.run(tool_class(api,"BOSS").execute(**params))
    assert database(api.store)==before


@pytest.mark.parametrize("source",["missing-source","../../boss agent.md","https://example.invalid/finance-note","finance-note&role=MAINTAINER"])
def test_unknown_or_locator_source_is_not_read_or_fetched(api,source):
    before=database(api.store)
    with pytest.raises(web.HTTPNotFound):
        asyncio.run(BossEvidenceReadTool(api,"BOSS").execute(source=source))
    assert database(api.store)==before


def command(api,role,action,payload):
    status,value=BossCommandAPI(api.store).execute(role,action,payload)
    assert status==200,value
    return value


def initial(api):
    with api.store.connect() as db:
        return api.store.get(db,"ui-check","initial","snapshot")


def test_dashboard_uses_confirmed_current_goals_and_ignores_draft(api,registry):
    profile=initial(api)["boss_profile"]
    saved=command(api,"BOSS","boss.owner.goals.save",{
        "client_request_id":"w2-read-goals-save","expected_version":"0",
        "goals":profile["goals"],"topics":[],"reading_requirement":profile["confirmed_reading_requirement"],
        "scope":"OWNER_WORKSPACE","valid_until":None})
    assert saved["authorization_created"] is False
    assert read(registry,api,"bossDashboardRead",{})["profile"]["goals"]==[]
    confirmed=command(api,"BOSS","boss.owner.goals.confirm",{
        "client_request_id":"w2-read-goals-confirm","expected_draft_version":saved["version"],
        "expected_active_version":"0","content_sha256":saved["content_sha256"]})
    assert confirmed["authorization_id"]
    current=read(registry,api,"bossDashboardRead",{})["profile"]
    assert current["goals"]==profile["goals"] and current["reading_requirement"]==profile["confirmed_reading_requirement"]
    reopened=BossPageAPI(ControlStore(api.store.path))
    assert json.loads(asyncio.run(BossDashboardReadTool(reopened,"BOSS").execute()))["profile"]==current


def test_current_meeting_changes_only_after_explicit_fixture_confirmation(api,registry):
    data=initial(api)
    current=data["meeting"]
    meetings=MeetingAPI(api.store)
    draft=meetings.execute("BOSS","draft.save",{
        "client_request_id":"w2-read-meeting-save","meeting_id":current["meeting_id"],
        "meeting_version":current["version"],"expected_version":"0",
        "purpose":"提交当前会议关联的毛利变化解释、措施和证据",
        "starts_at":current["starts_at"],"ends_at":"2026-10-23T10:00:00+08:00",
        "timezone":"Asia/Shanghai","preparation_due_at":None,
        "participant_ids":current["participant_ids"],
        "source_refs":[{"source_id":"finance-note","version":"1"}]})
    assert draft["meeting_changed"] is False and meetings.read("BOSS")["draft"]
    assert read(registry,api,"bossMeetingsRead",{})["meeting"]==current
    assert "draft" not in read(registry,api,"bossMeetingsRead",{})
    confirmed=meetings.execute("BOSS","confirm",{
        "client_request_id":"w2-read-meeting-confirm","meeting_id":current["meeting_id"],
        "meeting_version":current["version"],"draft_version":draft["version"],
        "review_sha256":draft["review_sha256"],"acknowledge_conflict":True})
    assert confirmed["version"]=="2" and confirmed["invitation_sent"] is False
    meeting=read(registry,api,"bossMeetingsRead",{})["meeting"]
    assert meeting["version"]=="2" and meeting["state"]=="SCHEDULED"
    assert read(registry,api,"bossDashboardRead",{})["meeting"]==meeting
    reopened=BossPageAPI(ControlStore(api.store.path))
    assert json.loads(asyncio.run(BossMeetingsReadTool(reopened,"BOSS").execute()))["meeting"]==meeting


def test_current_evidence_create_revise_withdraw_and_reopen(api,registry):
    data=initial(api)
    original=next(doc for doc in data["documents"] if doc["source_id"]=="finance-note")
    payload={"source_id":"sim-doc-w2-read","title":"获准模拟原文读取检查",
             "author_contact_id":original["author_contact_id"],"published_at":datetime.fromisoformat(original["published_at"]).date().isoformat(),
             "content":original["content"]}
    created=command(api,"MAINTAINER","boss.knowledge.source.create",{
        **payload,"client_request_id":"w2-read-source-create"})
    assert created["business_action_authorized"] is False
    first=read(registry,api,"bossEvidenceRead",{"source":payload["source_id"]})
    assert first["version"]=="1" and first["content"]==original["content"]
    command(api,"MAINTAINER","boss.knowledge.source.revise",{
        **payload,"client_request_id":"w2-read-source-revise","expected_version":"1"})
    second=read(registry,api,"bossEvidenceRead",{"source":payload["source_id"]})
    assert second["version"]=="2" and second["content"]==original["content"]
    reopened=BossPageAPI(ControlStore(api.store.path))
    assert json.loads(asyncio.run(BossEvidenceReadTool(reopened,"BOSS").execute(source=payload["source_id"])))["version"]=="2"
    withdrawn=command(api,"MAINTAINER","boss.knowledge.source.withdraw",{
        "client_request_id":"w2-read-source-withdraw","source_id":payload["source_id"],"expected_version":"2"})
    assert withdrawn["version"]=="3" and withdrawn["withdrawn"] is True
    before=database(api.store)
    for actual in (api,BossPageAPI(ControlStore(api.store.path))):
        with pytest.raises(web.HTTPGone):
            asyncio.run(BossEvidenceReadTool(actual,"BOSS").execute(source=payload["source_id"]))
    assert database(api.store)==before
    error=asyncio.run(registry.execute("bossEvidenceRead",{"source":payload["source_id"]}))
    assert error.is_error and original["content"] not in error
    assert database(api.store)==before


@pytest.mark.parametrize("change,status",[
    ({"source_type":"PRIVATE"},403),({"access_scope":"another-owner"},403),
    ({"validity_state":"RECEIVED"},409),({"validity_state":"INCOMPLETE"},409),
    ({"validity_state":"CONFLICTED"},409),({"validity_state":"SUPERSEDED"},409),
    ({"validity_state":"WITHDRAWN"},410),({"validity_state":"EXPIRED"},410),
    ({"valid_until":"2026-10-21T09:00:00+08:00"},410),
])
def test_actual_persisted_source_policy_rejects_unavailable_body(api,change,status):
    # 在独立SIMULATED资料中设置来源政策前置状态，读取仍执行正式模块。
    with api.store.connect() as db:
        document=api.store.get(db,"ui-check","document","finance-note")
        api.store.put(db,"ui-check","document","finance-note",{**document,**change})
    before=database(api.store)
    with pytest.raises(web.HTTPException) as denied:
        asyncio.run(BossEvidenceReadTool(api,"BOSS").execute(source="finance-note"))
    assert denied.value.status==status and database(api.store)==before
