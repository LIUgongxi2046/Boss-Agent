import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from markdown_it import MarkdownIt

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))

from boss_sector_api import SECTORS
from controls import ControlStore


def read_result(path):
    tokens=MarkdownIt().parse(path.read_text())
    headings=[index for index,token in enumerate(tokens) if token.type=="inline" and token.content=="Result" and index>0 and tokens[index-1].type=="heading_open"]
    assert len(headings)==1
    return json.loads(next(token.content for token in tokens[headings[0]+1:] if token.type=="inline"))


def main():
    directory=ROOT/"evidence/T21"
    checks=[]
    observations={}
    for name,check_id in (("scope","SECTOR-PAGE-FILTER-BOUNDARY"),("pending","SECTOR-ACTUAL-PENDING-PAGE-CHANGE"),
                          ("resumed","SECTOR-RESUMED-READ-CURRENT-PAGE"),("identity","SECTOR-PROVIDER-IDENTITY-BOUNDARY")):
        path=directory/("w2-20261023-sector-"+name+"-ui.txt")
        result=read_result(path)
        assert result["status"].startswith("PASS") and result["check_id"]==check_id and result["model_requests"]==0
        checks.append({"check_id":check_id,"status":result["status"],"source":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        observations[name]=result
    pages=observations["scope"]["all_page_observations"]
    assert {item["page_id"] for item in pages}==set(SECTORS)
    assert all(item["unknown_metrics_preserved"] for item in pages)
    work=ROOT/".work/w2-checks/sector-ui"
    baseline=ControlStore(work/"baseline.sqlite")
    with baseline.connect() as db:
        exists=db.execute("SELECT 1 FROM spaces WHERE namespace='ui-check'").fetchone()
    if exists is None:
        baseline.initialize("ui-check")
    with sqlite3.connect((work/"sector.sqlite").as_uri()+"?mode=ro",uri=True) as original,baseline.connect() as reference:
        assert tuple(original.iterdump())==tuple(reference.iterdump())
        counts={kind:original.execute("SELECT COUNT(*) FROM objects WHERE kind=?",(kind,)).fetchone()[0] for kind in ("task","outbox","message_outbox","runtime_run")}
        assert all(count==0 for count in counts.values())
        assert original.execute("SELECT COUNT(*) FROM audit").fetchone()[0]==0
        snapshot=json.loads(original.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='initial' AND id='snapshot'").fetchone()[0])
        assert snapshot["source_type"]=="SIMULATED"
    earlier=json.loads((ROOT/"evidence/T19/w2-20261023-prompt-identity-ui.json").read_text())
    upstream=Path("/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent/.work/product/nanobot")
    source_hashes={name:hashlib.sha256((upstream/name).read_bytes()).hexdigest() for name in earlier["actual_upstream_source_sha256"]}
    assert source_hashes==earlier["actual_upstream_source_sha256"]
    own_sources=["app/webui/BossSectorView.tsx","validation/boss_sector_api.py","validation/controls.py","validation/business.py"]
    own_sources.extend(str(path.relative_to(ROOT)) for path in sorted(directory.glob("check_sector*")) if path.is_file())
    own_sources.extend(str(path.relative_to(ROOT)) for path in sorted((directory/"sector-ui").iterdir()) if path.is_file())
    build={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((work/"dist/assets").iterdir())}
    report={"status":"PASS_SECTOR_SCOPE_AND_IDENTITY_COMPONENT","task_id":"T21","related_tasks":["T22","T23"],
            "source_commit":"a6625b9","working_changes_included":True,"source_type":"SIMULATED","external_api_mode":"SIMULATED_FIRST",
            "checks":checks,"all_page_observations":pages,"page_count":len(pages),"actual_database_matches_original_initialization":True,
            "audit_count":0,"object_counts":counts,"new_model_requests":0,"new_stt_requests":0,"new_external_api_requests":0,
            "actual_upstream_provider_used":True,"upstream_source_revision":earlier["upstream_source_revision"],"upstream_source_sha256":source_hashes,
            "source_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in own_sources},"build_sha256":build,
            "screenshots_taken":False,"public_rolechannel_acceptance":"NOT_RUN","visual_acceptance":"NOT_RUN",
            "model_conversation_integration":"NOT_RUN","sector_calculation_acceptance":"NOT_RUN",
            "full_A21_accepted":False,"full_A22_accepted":False,"full_A23_accepted":False}
    (directory/"w2-20261023-sector-identity.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"status":report["status"],"page_count":report["page_count"],"check_count":len(checks),
                      "database_unchanged":True,"new_external_api_requests":0},ensure_ascii=False))


main()
