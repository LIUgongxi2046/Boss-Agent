import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result

ROOT=Path(__file__).resolve().parents[2]
PIN="2161bb41c3fb31a384e8d3fd993b874ff6c33aa6"
BACKEND=ROOT/".work/w2-checks/remaining-read-backend"
FORMAL=yaml.safe_load(subprocess.check_output(["git","show",PIN+":specs/openapi.yaml"],cwd=ROOT))
sys.path.insert(0,str(BACKEND/"validation"))
sys.path.insert(1,str(ROOT/"validation"))

from boss_page_api import BossPageAPI
from controls import ControlStore
from boss_command_api import BossCommandAPI
from boss_meetings import MeetingAPI
from runtime_sop_read_tools import (BossTasksReadTool, BossCalendarConflictReadTool,
                                    BossCalendarSharePreviewTool, BossWorkspaceReadTool, SOP_WORKSPACE_PROJECTIONS)


def w2_module(name,path):
    definition=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


BossSkillCatalog=w2_module("w2_remaining_native_skills","validation/boss_native_skills.py").BossSkillCatalog
BossResearchSourcesTool=w2_module("w2_research_reader","validation/boss_agent_read_tools.py").BossResearchSourcesTool

NAMES={"bossTasksRead","bossCalendarConflictRead","bossCalendarSharePreview","bossWorkspaceRead"}
CLASSES=(BossTasksReadTool,BossCalendarConflictReadTool,BossCalendarSharePreviewTool,BossWorkspaceReadTool)
CONNECTIONS=[]
OBSERVATIONS=[]
TIME={"starts_at":"2026-10-23T10:00:00+08:00","ends_at":"2026-10-23T11:00:00+08:00","timezone":"Asia/Shanghai"}


def no_network(event,args):
    if event=="socket.connect":
        CONNECTIONS.append(str(args[1]))
        raise PermissionError("本项检查禁止网络连接")


sys.addaudithook(no_network)


@pytest.fixture(scope="session",autouse=True)
def immutable_backend():
    def hashes():
        paths=list((BACKEND/"validation").rglob("*.py"))+[path for path in (BACKEND/"specs").rglob("*") if path.is_file()]
        result={}
        for path in sorted(paths):
            relative=path.relative_to(BACKEND).as_posix()
            committed=subprocess.check_output(["git","show",PIN+":"+relative],cwd=ROOT)
            assert path.read_bytes()==committed,relative
            result[relative]=hashlib.sha256(committed).hexdigest()
        return result
    before=hashes()
    yield
    assert hashes()==before and CONNECTIONS==[]
    imported={name:{"path":str(Path(module.__file__).relative_to(BACKEND)),
                    "sha256":hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
              for name,module in tuple(sys.modules.items()) if getattr(module,"__file__",None)
              and Path(module.__file__).is_relative_to(BACKEND)}
    (ROOT/".work/w2-checks/remaining-read-observations.json").write_text(json.dumps({
        "source_files":before,"actual_imports":imported,"socket_connect_attempts":CONNECTIONS,
        "observations":OBSERVATIONS},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


@pytest.fixture
def api(tmp_path):
    store=ControlStore(tmp_path/"remaining-reads.sqlite")
    store.initialize("ui-check")
    return BossPageAPI(store)


@pytest.fixture
def registry(api):
    result=ToolRegistry()
    for tool_class in CLASSES:
        result.register(make(tool_class,api))
    return result


def make(tool_class,api,role="BOSS",**kwargs):
    if tool_class is BossWorkspaceReadTool and "allowed_projections" not in kwargs:
        kwargs["allowed_projections"]=SOP_WORKSPACE_PROJECTIONS
    return tool_class(api,role,**kwargs)


def database(api):
    with api.store.connect() as db:
        return tuple(db.iterdump())


def read(api,registry,name,params):
    before=database(api)
    raw=asyncio.run(registry.execute(name,params))
    assert not is_tool_error_result(raw),raw
    value=json.loads(raw)
    assert database(api)==before
    schema=FORMAL
    operation=next(methods["get"] for methods in schema["paths"].values() if methods.get("get",{}).get("operationId")==name)
    output=operation["responses"]["200"]["content"]["application/json"]["schema"]
    Draft202012Validator({**schema,"$ref":"#/checked","checked":output},format_checker=FormatChecker()).validate(value)
    return value


def denied(api,tool,params,status):
    before=database(api)
    with pytest.raises(web.HTTPException) as error:
        asyncio.run(tool.execute(**params))
    assert error.value.status==status and database(api)==before


def command(api,action,payload,role="BOSS"):
    status,value=BossCommandAPI(api.store).execute(role,action,payload)
    assert status==200,value
    return value


def initial(api):
    with api.store.connect() as db:
        return api.store.get(db,"ui-check","initial","snapshot")


def change_source(api,change):
    with api.store.connect() as db:
        document=api.store.get(db,"ui-check","document","finance-note")
        api.store.put(db,"ui-check","document","finance-note",{**document,**change})


def test_remaining_read_capabilities_exist(registry):
    assert NAMES<=set(registry.tool_names)
    assert all(registry.get(name).read_only for name in NAMES)


@pytest.mark.parametrize("projection",sorted(SOP_WORKSPACE_PROJECTIONS))
def test_each_workspace_projection_uses_exact_actual_projection_and_reopens(api,registry,projection):
    first=read(api,registry,"bossWorkspaceRead",{"projection":projection})
    status,actual=api.serve("BOSS","/api/boss/ui/workspace/"+projection)
    assert status==200
    assert {k:v for k,v in first.items() if k!="read_at"}=={k:v for k,v in actual.items() if k!="read_at"}
    reopened=BossPageAPI(ControlStore(api.store.path))
    other=ToolRegistry()
    other.register(make(BossWorkspaceReadTool,reopened))
    second=read(reopened,other,"bossWorkspaceRead",{"projection":projection})
    assert {k:v for k,v in first.items() if k!="read_at"}=={k:v for k,v in second.items() if k!="read_at"}
    OBSERVATIONS.append({"projection":projection,"initial_keys":sorted(first)})


@pytest.mark.parametrize("tool_class",CLASSES)
@pytest.mark.parametrize("role,status",[(None,401),("MAINTAINER",403),("CONTACT",403)])
def test_roles_are_bound_by_server(api,tool_class,role,status):
    before=database(api)
    with pytest.raises(web.HTTPException) as error:
        make(tool_class,api,role)
    assert error.value.status==status and database(api)==before


@pytest.mark.parametrize("name",sorted(NAMES))
@pytest.mark.parametrize("field",["namespace","owner_id","role","authorization_id","envelope","idempotency_key"])
def test_caller_cannot_expand_scope_or_authority(api,registry,name,field):
    params={"bossTasksRead":{},"bossCalendarConflictRead":TIME,
            "bossCalendarSharePreview":{"share_id":"busy-share-unknown"},
            "bossWorkspaceRead":{"projection":"research"}}[name]
    before=database(api)
    _,_,error=registry.prepare_call(name,{**params,field:"caller-value"})
    assert error and database(api)==before


@pytest.mark.parametrize("name,params",[
    ("bossCalendarConflictRead",{}),("bossCalendarConflictRead",{**TIME,"starts_at":"2026-10-23"}),
    ("bossCalendarConflictRead",{**TIME,"ends_at":True}),("bossCalendarConflictRead",{**TIME,"timezone":[]}),
    ("bossCalendarSharePreview",{}),("bossCalendarSharePreview",{"share_id":[]}),
    ("bossCalendarSharePreview",{"share_id":"private-1"}),("bossCalendarSharePreview",{"share_id":"busy-share-"+"a"*100}),
    ("bossWorkspaceRead",{}),("bossWorkspaceRead",{"projection":[]}),
    ("bossWorkspaceRead",{"projection":"dataset"}),("bossWorkspaceRead",{"projection":"../calendar"}),
])
def test_exact_input_schema_in_actual_registry(api,registry,name,params):
    before=database(api)
    _,_,error=registry.prepare_call(name,params)
    assert error and database(api)==before


@pytest.mark.parametrize("tool_class,params",[
    (BossTasksReadTool,{}),(BossCalendarConflictReadTool,TIME),
    (BossCalendarSharePreviewTool,{"share_id":"busy-share-unknown"}),
    (BossWorkspaceReadTool,{"projection":"research"}),
])
def test_owner_namespace_and_reset_are_checked(api,tool_class,params):
    denied(api,make(tool_class,api,owner_id="another-owner"),params,403)
    other=BossPageAPI(api.store,namespace="another-space")
    api.store.initialize("another-space")
    denied(api,make(tool_class,other),params,409)
    api.store.control("ui-check","reset",{"namespace":"next-space"})
    denied(api,make(tool_class,api),params,409)


def test_workspace_requires_explicit_server_projection_scope(api):
    for projections,status in (([],400),(["dataset"],403),(["research","research"],403),(["voice"],403)):
        with pytest.raises(web.HTTPException) as error:
            BossWorkspaceReadTool(api,"BOSS",allowed_projections=projections)
        assert error.value.status==status
    tool=BossWorkspaceReadTool(api,"BOSS",allowed_projections=["research"])
    denied(api,tool,{"projection":"calendar"},400)
    registry=ToolRegistry()
    registry.register(tool)
    assert registry.prepare_call("bossWorkspaceRead",{"projection":"calendar"})[2]
    assert tool.allowed_projections==frozenset({"research"})


def test_empty_results_remain_empty_and_historical_task_is_separate(api,registry):
    tasks=read(api,registry,"bossTasksRead",{})
    assert tasks["tasks"]==[] and tasks["feedback"]==[] and tasks["self_commitments"]==[]
    assert tasks["historical_commitment"]["task_id"]=="historical-1"
    for projection,key in (("notifications","notifications"),("minutes","linked_assignments"),
                           ("approvals","applications"),("outbox","sent_messages"),
                           ("people","briefs"),("decisions","history")):
        assert read(api,registry,"bossWorkspaceRead",{"projection":projection})[key]==[]
    assert read(api,registry,"bossWorkspaceRead",{"projection":"minutes"})["minute"] is None
    assert read(api,registry,"bossWorkspaceRead",{"projection":"research"})["report"] is None
    denied(api,registry.get("bossCalendarSharePreview"),{"share_id":"busy-share-unknown"},404)


def test_conflict_uses_current_meeting_and_inactive_status(api,registry):
    first=read(api,registry,"bossCalendarConflictRead",TIME)
    assert first["meeting_end_known"] is False and first["conflict_proven_absent"] is False
    meeting=initial(api)["meeting"]
    service=MeetingAPI(api.store)
    draft=service.execute("BOSS","draft.save",{
        "client_request_id":"remaining-conflict-save","meeting_id":"meeting-1","meeting_version":"1","expected_version":"0",
        "purpose":"提交当前会议关联的毛利变化解释、措施和证据","starts_at":meeting["starts_at"],
        "ends_at":"2026-10-23T11:00:00+08:00","timezone":"Asia/Shanghai","preparation_due_at":None,
        "participant_ids":meeting["participant_ids"],"source_refs":[{"source_id":"finance-note","version":"1"}]})
    service.execute("BOSS","confirm",{
        "client_request_id":"remaining-conflict-confirm","meeting_id":"meeting-1","meeting_version":"1",
        "draft_version":draft["version"],"review_sha256":draft["review_sha256"],"acknowledge_conflict":True})
    current=read(api,registry,"bossCalendarConflictRead",TIME)
    assert current["meeting_version"]=="2" and current["status"]=="KNOWN_MEETING_INTERVAL_OVERLAP"
    separated=read(api,registry,"bossCalendarConflictRead",{
        **TIME,"starts_at":"2026-10-23T12:00:00+08:00","ends_at":"2026-10-23T13:00:00+08:00"})
    assert separated["status"]=="NO_OVERLAP_WITH_CURRENT_MEETING" and separated["conflict_proven_absent"] is True
    service.execute("BOSS","cancel",{
        "client_request_id":"remaining-conflict-cancel","meeting_id":"meeting-1","expected_version":"2","reason":"取消本次模拟会议核查"})
    inactive=read(api,registry,"bossCalendarConflictRead",TIME)
    assert inactive["meeting_version"]=="3" and inactive["status"]=="MEETING_INACTIVE"
    assert inactive["conflict_proven_absent"] is True
    reopened=BossPageAPI(ControlStore(api.store.path))
    value=json.loads(asyncio.run(BossCalendarConflictReadTool(reopened,"BOSS").execute(**TIME)))
    assert value["status"]=="MEETING_INACTIVE" and value["meeting_version"]=="3"


@pytest.mark.parametrize("change",[
    {"ends_at":"2026-10-23T09:00:00+08:00"},{"timezone":"Invalid/Zone"},
    {"starts_at":"2026-10-23T10:00:00"},{"ends_at":"2026-12-25T10:00:00+08:00"},
])
def test_conflict_rejects_invalid_window_or_timezone(api,registry,change):
    denied(api,registry.get("bossCalendarConflictRead"),{**TIME,**change},400)


def create_share(api):
    return command(api,"boss.calendar.share",{
        "client_request_id":"remaining-share-create","expected_version":"1","recipient_id":"coordinator-1",
        "purpose":"检查已有占用时间的授权预览","expires_at":"2026-10-25T20:00:00+08:00",
        "fields":["busy","starts_at","ends_at","timezone"]})


@pytest.mark.parametrize("ending",["revoke","expire","delete","authorization","revision"])
def test_busy_preview_is_read_only_and_stops_after_revocation_expiry_or_delete(api,registry,ending):
    share=create_share(api)
    params={"share_id":share["share_id"]}
    first=read(api,registry,"bossCalendarSharePreview",params)
    assert first["external_delivery_created"] is False and first["preview_only_not_external_access"] is True
    assert first["fields"]==["busy","starts_at","ends_at","timezone"]
    assert not {"private_body","title","location","attachment_refs","authorization_id"}.intersection(first)
    reopened_active=BossPageAPI(ControlStore(api.store.path))
    other=ToolRegistry()
    other.register(BossCalendarSharePreviewTool(reopened_active,"BOSS"))
    assert read(reopened_active,other,"bossCalendarSharePreview",params)["share_status"]=="ACTIVE_SIMULATED"
    if ending=="revoke":
        command(api,"boss.calendar.share.revoke",{
            "client_request_id":"remaining-share-revoke",**params,"expected_version":"1"})
    elif ending=="expire":
        api.store.control("ui-check","clock",{"at":"2026-10-26T09:00:00+08:00"})
    elif ending=="delete":
        command(api,"boss.calendar.delete",{"client_request_id":"remaining-calendar-delete","expected_version":"1"})
        view=read(api,registry,"bossWorkspaceRead",{"projection":"calendar"})
        assert view["calendar"]["status"]=="DELETED" and view["calendar"]["private_body"]==""
    elif ending=="revision":
        calendar=initial(api)["private_calendar"]
        command(api,"boss.calendar.save",{
            "client_request_id":"remaining-calendar-revise","expected_version":"1",
            "starts_at":calendar["starts_at"],"ends_at":calendar["ends_at"],"timezone":calendar["timezone"],
            "title":"","private_body":calendar["private_body"],"location":"","attachment_refs":[],"acknowledge_conflict":True})
        assert read(api,registry,"bossWorkspaceRead",{"projection":"calendar"})["calendar"]["version"]=="2"
    else:
        command(api,"boss.authorization.revoke",{
            "client_request_id":"remaining-share-auth-revoke","authorization_id":share["authorization_id"],"expected_version":"1","reason":"结束本次模拟分享授权核查"})
    denied(api,registry.get("bossCalendarSharePreview"),params,410)
    reopened=BossPageAPI(ControlStore(api.store.path))
    denied(reopened,BossCalendarSharePreviewTool(reopened,"BOSS"),params,410)


def test_memory_confirmation_and_deletion_read_current_state(api,registry):
    text=initial(api)["memory"]["text"]
    before=read(api,registry,"bossWorkspaceRead",{"projection":"memory"})
    assert before["effective"] is True and before["memory"]["version"]=="1"
    command(api,"boss.memory.confirm",{"client_request_id":"remaining-memory-confirm","expected_version":"1","text":text})
    current=read(api,registry,"bossWorkspaceRead",{"projection":"memory"})
    assert current["effective"] is True and current["memory"]["version"]=="2"
    command(api,"boss.memory.delete",{"client_request_id":"remaining-memory-delete","expected_version":"2"})
    deleted=read(api,registry,"bossWorkspaceRead",{"projection":"memory"})
    assert deleted["memory"]["version"]=="3" and deleted["memory"]["text"]=="" and deleted["effective"] is False
    knowledge=read(api,registry,"bossWorkspaceRead",{"projection":"knowledge"})
    assert text not in json.dumps(knowledge,ensure_ascii=False)


def full_read_registry(api,registry):
    from business import OPERATIONS
    from model_probe import BusinessTool
    envelope={"request_id":"remaining-native-read","owner_id":"boss-1","execution_namespace":"ui-check",
              "dataset_id":"selection","dataset_version":"1","session_id":"remaining-native-read"}
    for operation in OPERATIONS:
        registry.register(BusinessTool(operation,api.store,envelope,{},[]))
    for filename,names in (
        ("runtime_page_read_tools",("BossDashboardReadTool","BossMeetingsReadTool","BossEvidenceReadTool")),
        ("runtime_owner_read_tools",("BossTodayReadTool","BossOwnerPlansReadTool")),
        ("runtime_meeting_tool",("BossCurrentMeetingTool",)),
        ("runtime_assignment_source_tool",("BossAssignmentSourcesReadTool",)),
    ):
        module=w2_module("w2_"+filename,"validation/"+filename+".py")
        for name in names:
            first=api if filename=="runtime_page_read_tools" else api.store
            registry.register(getattr(module,name)(first,"BOSS"))
    return registry


def test_native_catalog_checks_real_projection_capabilities_and_remaining_commands(api,registry,tmp_path):
    registry=full_read_registry(api,registry)
    catalog=BossSkillCatalog(SkillsLoader(tmp_path,builtin_skills_dir=ROOT/"agent/skills"),registry)
    status=catalog.technical_status("MAINTAINER")
    assets=json.loads((ROOT/"specs/agent-assets.json").read_text(encoding="utf-8"))
    bindings={item["sop_id"]:item for item in assets["sop_backend_bindings"]}
    union={projection for item in bindings.values() for projection in item.get("workspace_projections",[])}
    assert union==set(SOP_WORKSPACE_PROJECTIONS)
    for item in status["items"]:
        assert item["missing_projections"]==[]
        assert not set(item["missing_tools"]).intersection(bindings[item["sop_id"]]["read_operations"])
        if item["sop_id"]!="SOP03":
            assert item["missing_tools"] and not item["context_eligible"]
            with pytest.raises(web.HTTPConflict):
                catalog.context("BOSS",[item["sop_id"]])
    OBSERVATIONS.append({"native_sop_coverage":status["items"]})
    registry.register(BossResearchSourcesTool(api.store,"BOSS"))
    restricted=catalog.technical_status("MAINTAINER")
    for item in restricted["items"]:
        expected=set(bindings[item["sop_id"]].get("workspace_projections",[]))-{"research"}
        assert set(item["missing_projections"])==expected
        if expected:
            assert item["context_eligible"] is False and item["tool_references_resolved"] is False
    OBSERVATIONS.append({"research_only_coverage":restricted["items"]})


def create_task(api):
    return command(api,"boss.assignment.create",{
        "client_request_id":"remaining-task-create","purpose":"提交当前会议关联的毛利变化解释、措施和证据",
        "coordinator_id":"coordinator-1","due_at":"2026-10-25T17:00:00+08:00","timezone":"Asia/Shanghai",
        "evidence_requirements":["经营原始明细"],"related_meeting_id":"meeting-1","related_event_ids":["event-1"],
        "source_refs":["finance-note"],"content_version":"1"})


def test_tasks_keep_actual_result_source_and_cancellation_separate(api,registry):
    created=create_task(api)
    task=read(api,registry,"bossTasksRead",{})["tasks"][0]
    assert task["task_id"]==created["task_id"] and task["status"]=="OPEN"
    sent=command(api,"boss.assignment.send",{
        "client_request_id":"remaining-task-send","task_id":task["task_id"],"task_version":task["version"],
        "recipient_id":"coordinator-1","body":task["purpose"],"content_version":"1"})
    current=read(api,registry,"bossTasksRead",{})
    assert current["tasks"][0]["status"]=="WAITING_FEEDBACK" and current["linked_messages"]
    feedback=command(api,"boss.simulation.feedback",{
        "client_request_id":"remaining-task-feedback","task_id":task["task_id"],"task_version":sent["task_version"],
        "author_contact_id":"coordinator-1","kind":"RESULT_SUBMITTED",
        "content":initial(api)["documents"][0]["content"],"evidence_refs":["finance-note"]},"MAINTAINER")
    result=read(api,registry,"bossTasksRead",{})
    assert result["tasks"][0]["status"]=="RESULT_SUBMITTED" and result["feedback"]
    change_source(api,{"version":"2"})
    stale=read(api,registry,"bossTasksRead",{})["tasks"][0]
    assert stale["status"]=="RESULT_SUBMITTED" and stale["source_reference_state"]=="NEEDS_REVIEW"
    assert stale["result_evidence_requires_resubmission"] is True
    canceled=command(api,"boss.assignment.cancel",{
        "client_request_id":"remaining-task-cancel","task_id":task["task_id"],"task_version":stale["version"],
        "reason":"结束本次模拟任务读取核查"})
    reopened=BossPageAPI(ControlStore(api.store.path))
    final=json.loads(asyncio.run(BossTasksReadTool(reopened,"BOSS").execute()))
    assert final["tasks"][0]["status"]=="CANCELED" and final["tasks"][0]["version"]==canceled["version"]
    decisions=read(api,registry,"bossWorkspaceRead",{"projection":"decisions"})
    assert any(item["action"]=="boss.assignment.cancel" and item["task_id"]==task["task_id"] for item in decisions["history"])
    outbox=read(api,registry,"bossWorkspaceRead",{"projection":"outbox"})
    assert outbox["messages"] and outbox["external_channel_invoked"] is False


@pytest.mark.parametrize("change,version,current",[
    ({"version":"2"},"2",True),({"withdrawn":True},None,False),
    ({"validity_state":"CONFLICTED"},None,False),({"validity_state":"EXPIRED"},None,False),
    ({"access_scope":"another-owner"},None,False),
])
def test_workspace_knowledge_research_minutes_and_people_recheck_current_sources(api,registry,change,version,current):
    original=next(item for item in initial(api)["documents"] if item["source_id"]=="finance-note")
    command(api,"boss.minutes.save",{
        "client_request_id":"remaining-minutes-save","meeting_id":"meeting-1","meeting_version":"1",
        "source_id":"finance-note","source_version":"1","expected_version":"0",
        "entries":[{"kind":"OPINION","text":original["content"],"source_anchor":"毛利=收入减成本"}]})
    command(api,"boss.people.prepare",{
        "client_request_id":"remaining-people-prepare","brief_id":None,"expected_version":"0",
        "contact_id":"coordinator-1","purpose":"核查现有获准会议材料","meeting_id":"meeting-1",
        "source_refs":[{"source_id":"finance-note","version":"1"}]})
    command(api,"boss.research.prepare",{
        "client_request_id":"remaining-research-prepare","expected_version":"0","question":"毛利",
        "period":"","country":"","business_relation":"","cutoff_date":"2026-10-22"})
    assert read(api,registry,"bossWorkspaceRead",{"projection":"minutes"})["minute"]["source_reference_state"]=="CURRENT"
    assert read(api,registry,"bossWorkspaceRead",{"projection":"people"})["briefs"][0]["live_evidence_current"] is True
    change_source(api,change)
    knowledge=read(api,registry,"bossWorkspaceRead",{"projection":"knowledge"})
    matches=[item for item in knowledge["results"] if item["source_id"]=="finance-note"]
    assert bool(matches)==current
    if current:
        assert matches[0]["version"]==version
    research=read(api,registry,"bossWorkspaceRead",{"projection":"research"})
    quotes=[item for item in research["report"]["matched_sources"] if item["source_id"]=="finance-note"]
    assert bool(quotes)==current and research["current_reference_state"]=="NEEDS_REVIEW"
    minute=read(api,registry,"bossWorkspaceRead",{"projection":"minutes"})["minute"]
    assert minute["source_reference_state"]=="NEEDS_REVIEW" and minute["entries"][0]["text"]==""
    people=read(api,registry,"bossWorkspaceRead",{"projection":"people"})["briefs"][0]
    assert people["live_evidence_current"] is False and people["compiled"]["sources"][0]["excerpt"] is None
    reopened=BossPageAPI(ControlStore(api.store.path))
    reopened_tool=BossWorkspaceReadTool(reopened,"BOSS",allowed_projections=["minutes"])
    value=json.loads(asyncio.run(reopened_tool.execute(projection="minutes")))
    assert value["minute"]["source_reference_state"]=="NEEDS_REVIEW"


def test_travel_pending_confirmed_canceled_are_current_and_not_external_bookings(api,registry):
    reviewed=command(api,"boss.travel.review",{
        "client_request_id":"remaining-travel-review","travel_id":None,"expected_version":"0",
        "origin":"合成区域","destination":"合成财务","starts_at":"2026-10-24T09:00:00+08:00",
        "ends_at":"2026-10-24T10:00:00+08:00","timezone":"Asia/Shanghai",
        "host_contact_id":"coordinator-1","buffer_minutes":0,"transport_refs":[]})
    draft=read(api,registry,"bossWorkspaceRead",{"projection":"travel"})
    assert draft["plans"][0]["status"]=="DRAFT_REVIEWED" and draft["plans"][0]["current"] is None
    confirmed=command(api,"boss.travel.confirm",{
        "client_request_id":"remaining-travel-confirm","travel_id":reviewed["travel_id"],"expected_version":reviewed["version"],
        "review_sha256":reviewed["review_sha256"],"acknowledge_conflicts":True,"acknowledge_missing_transport":True})
    view=read(api,registry,"bossWorkspaceRead",{"projection":"travel"})
    assert view["plans"][0]["status"]=="CONFIRMED" and view["real_transport_bookings"] is False
    command(api,"boss.travel.cancel",{
        "client_request_id":"remaining-travel-cancel","travel_id":reviewed["travel_id"],"expected_version":confirmed["version"],"reason":"结束本次模拟行程读取核查"})
    canceled=read(api,registry,"bossWorkspaceRead",{"projection":"travel"})
    assert canceled["plans"][0]["status"]=="CANCELED" and canceled["plans"][0]["pending"] is None


def test_calendar_list_reports_revoked_share_authorization(api,registry):
    share=create_share(api)
    command(api,"boss.authorization.revoke",{
        "client_request_id":"remaining-calendar-list-revoke","authorization_id":share["authorization_id"],
        "expected_version":"1","reason":"结束本次模拟日历分享读取核查"})
    value=read(api,registry,"bossWorkspaceRead",{"projection":"calendar"})
    assert value["shares"][0]["effective_state"]=="REVOKED"
    assert value["calendar"]["status"]=="ACTIVE"


@pytest.mark.parametrize("change,state",[
    ({"validity_state":"CONFLICTED"},"CONFLICTED"),
    ({"validity_state":"EXPIRED"},"EXPIRED"),
    ({"access_scope":"another-owner"},"NOT_AUTHORIZED"),
])
def test_approval_attachment_status_uses_current_source_qualification(api,registry,change,state):
    data=initial(api)
    content=next(item["content"] for item in data["documents"] if item["source_id"]=="finance-note")
    seeded=command(api,"boss.simulation.application.seed",{
        "client_request_id":"remaining-approval-seed","application_id":"application-1",
        "applicant_contact_id":"coordinator-1","amount_cny":data["details"][0]["revenue_cny"],
        "title":"获准模拟原文资料核查","description":content,"attachment_text":content},"MAINTAINER")
    assert seeded["owner_authorization_created"] is False
    first=read(api,registry,"bossWorkspaceRead",{"projection":"approvals"})
    assert first["applications"][0]["attachment_status"]=="CURRENT"
    with api.store.connect() as db:
        source=api.store.get(db,"ui-check","document",seeded["source_id"])
        api.store.put(db,"ui-check","document",seeded["source_id"],{**source,**change})
    view=read(api,registry,"bossWorkspaceRead",{"projection":"approvals"})
    application=view["applications"][0]
    assert application["attachment_status"]==state and application["state"]=="PENDING_DECISION"
    assert application["funds_transferred"] is False and application["professional_release_issued"] is False
