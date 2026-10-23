import hashlib
import importlib.metadata
import json
import sqlite3
import sys
from pathlib import Path

from lxml import etree
from markdown_it import MarkdownIt
from nanobot.agent.skills import SkillsLoader, parse_skill_metadata
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))

from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from controls import ControlStore
from model_probe import BusinessTool


def result(path):
    tokens=MarkdownIt().parse(path.read_text())
    headings=[index for index,token in enumerate(tokens) if token.type=="inline" and token.content=="Result"
              and index>0 and tokens[index-1].type=="heading_open"]
    assert len(headings)==1
    return json.loads(next(token.content for token in tokens[headings[0]+1:] if token.type=="inline"))


def main():
    evidence=ROOT/"evidence/T19"
    checks=[]
    observed={}
    for suffix,check_id in (("ui","A06-DRAFT-HISTORY-NATIVE-LIFECYCLE"),("prepare-restart","A06-PREPARED-ACTIVATION"),
                            ("recovery-ui","A06-ACTUAL-RESTART-RECOVERY-CANCEL"),("cancel-ui","A06-CANCEL-ACTUAL-PENDING-READ"),
                            ("errors-ui","A06-OFFLINE-ORIGINAL-RECEIPT-IDENTITY")):
        path=evidence/("w2-20261023-sop-drafts-"+suffix+".txt")
        item=result(path)
        assert item["status"].startswith("PASS") and item["check_id"]==check_id
        assert item.get("observed_external_request_count",item.get("external_request_count"))==0
        checks.append({"check_id":check_id,"status":item["status"],"source":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        observed[suffix]=item
    reports={}
    cases=set()
    for name in ("domain","receipts"):
        path=evidence/("w2-20261023-sop-drafts-"+name+".xml")
        tree=etree.parse(str(path))
        suite=tree.getroot().find("testsuite")
        assert suite.get("errors")=="0" and suite.get("failures")=="0" and suite.get("skipped")=="0"
        reports[name]={key:suite.get(key) for key in ("tests","errors","failures","skipped","time")}
        reports[name]["source"]=str(path.relative_to(ROOT))
        reports[name]["sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
        cases.update((item.get("classname"),item.get("name")) for item in suite.findall("testcase"))
    work=ROOT/".work/w2-checks/skill-ui"
    source=work/"business.sqlite"
    with sqlite3.connect(source.as_uri()+"?mode=ro",uri=True) as db:
        rows=[(kind,identifier,json.loads(body)) for kind,identifier,body in db.execute("SELECT kind,id,body FROM objects WHERE namespace='ui-check'")]
        objects={(kind,identifier):body for kind,identifier,body in rows}
        snapshot=objects[("initial","snapshot")]
        assert snapshot["source_type"]=="SIMULATED" and snapshot["dataset_id"]=="selection"
        counts={kind:sum(1 for observed_kind,_,_ in rows if observed_kind==kind) for kind in ("task","outbox","message_outbox","runtime_run","sop_draft","sop_history","sop_activation")}
        assert all(counts[kind]==0 for kind in ("task","outbox","message_outbox","runtime_run"))
        operations=[row[0] for row in db.execute("SELECT operation FROM audit WHERE namespace='ui-check' ORDER BY id")]
        assert operations and all(operation.startswith("boss.sop.") for operation in operations)
        pending=[body for kind,_,body in rows if kind=="sop_activation" and body["state"]=="PREPARED"]
        assert pending==[]
        draft=objects[("sop_draft","SOP03")]
        assert draft["draft_version"]=="6" and draft["method_version"]=="0.1.5" and draft["state"]=="DRAFT"
        recovery_id=observed["recovery-ui"]["recovered_request_id"]
        journal=objects[("sop_activation",recovery_id)]
        assert journal["state"]=="COMPLETED"
        receipt=json.loads(db.execute("SELECT result FROM idempotency WHERE namespace='ui-check' AND operation='boss.sop.activate' AND key=?",(recovery_id,)).fetchone()[0])
        assert receipt["state"]=="ACTIVE" and receipt["method_version"]=="0.1.3"
    config=load_config(work/"config.json")
    loader=SkillsLoader(work/"workspace",disabled_skills=set(config.agents.defaults.disabled_skills))
    document=loader.load_skill("boss-sop03")
    metadata=parse_skill_metadata(document)
    assert metadata["metadata"]["boss"]["version"]=="0.1.3"
    native_sha=hashlib.sha256(document.encode()).hexdigest()
    assert native_sha==observed["recovery-ui"]["final_native_sha256"]
    registry=ToolRegistry()
    store=ControlStore(source)
    assets=json.loads((ROOT/"specs/agent-assets.json").read_text())
    envelope={"request_id":"w2-sop-final-context","owner_id":"boss-1","execution_namespace":"ui-check","dataset_id":"selection","dataset_version":"1","session_id":"w2-sop-final-context"}
    for item in assets["tools"]:
        registry.register(BusinessTool(item["tool_id"],store,envelope,{},[]))
    catalog=BossSkillCatalog(loader,registry)
    methods=BossSkillDrafts(store,catalog,work/"config.json")
    with store.connect() as db:
        before=tuple(db.iterdump())
    block,references=catalog.context("BOSS",["SOP03"])
    assert references[0]["version"]=="0.1.3" and references[0]["content_sha256"]==native_sha
    assert block.source=="explicit_skills" and "原因贡献材料缺少时明确说明未知" in block.content
    assert methods.read("MAINTAINER","SOP03")["draft"]["method_version"]=="0.1.5"
    with store.connect() as db:
        assert tuple(db.iterdump())==before
    files=["validation/boss_skill_drafts.py","validation/boss_native_skills.py","validation/pyproject.toml","validation/uv.lock",
           "app/webui/MaintainerSkillVersions.tsx","app/tests/test_boss_skill_drafts.py","app/tests/test_boss_native_skills.py","specs/agent-assets.json"]
    files.extend(str(path.relative_to(ROOT)) for path in sorted(evidence.glob("check_skill_ui*")) if path.is_file())
    files.extend(str(path.relative_to(ROOT)) for path in sorted((evidence/"skill-ui").iterdir()) if path.is_file())
    files.extend(str(path.relative_to(ROOT)) for path in sorted((ROOT/"agent/skills").glob("*/SKILL.md")))
    build_files=[work/"lifecycle-index-ZmtbLt1k.js",*(work/"dist/assets").iterdir()]
    foreign=[str(Path(module.__file__).resolve()) for module in list(sys.modules.values()) if getattr(module,"__file__",None)
             and "/.codex/worktrees/" in str(Path(module.__file__).resolve()) and not Path(module.__file__).resolve().is_relative_to(ROOT)]
    assert foreign==[]
    report={"status":"PASS_LOCAL_DRAFT_DOMAIN_AND_COMPONENT_SCOPE","task_id":"T19","related_task_id":"T07",
        "source_commit":"2812813","working_changes_included":True,"external_api_mode":"SIMULATED_FIRST",
        "checks":checks,"test_reports":reports,"unique_test_case_count":len(cases),"receipt_checks_overlap_domain":True,
        "current_native_version":"0.1.3","current_native_sha256":native_sha,"current_draft_version":"6","current_draft_method_version":"0.1.5",
        "native_context_references":references,"native_context_read_verified":True,"model_adoption_verified":False,
        "object_counts":counts,"audit_operations":operations,"pending_activation_count":0,"actual_database_reopened":True,
        "final_context_and_read_do_not_write":True,"external_request_count":0,"stt_request_count":0,"cost_total":None,
        "packages":{name:importlib.metadata.version(name) for name in ("nanobot-ai","PyYAML","markdown-it-py","packaging")},
        "source_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files},
        "build_sha256":{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in build_files},
        "foreign_worktree_modules_loaded":foreign,"screenshots_taken":False,"public_rolechannel_acceptance":"NOT_RUN",
        "visual_acceptance":"NOT_RUN","real_external_service_validation":"NOT_RUN","full_A07_accepted":False,"full_A19_accepted":False}
    (evidence/"w2-20261023-sop-drafts.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"status":report["status"],"dom_check_count":len(checks),"unique_test_case_count":len(cases),
                      "native_version":report["current_native_version"],"draft_version":report["current_draft_version"],"external_request_count":0},ensure_ascii=False))


main()
