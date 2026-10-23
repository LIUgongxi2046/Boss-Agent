import hashlib
import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import yaml

ROOT=Path(__file__).resolve().parents[2]
PIN="7aab4405b77887b3a2f242dde8c256247c0926f1"
WORK=ROOT/".work/w2-checks"
BACKEND=WORK/"sop-read-backend"
WORK.mkdir(parents=True,exist_ok=True)
BACKEND.mkdir(parents=True,exist_ok=True)
archive=WORK/"sop-read-backend.tar"
subprocess.run(["git","archive","--format=tar","--output="+str(archive),PIN,"validation","specs"],cwd=ROOT,check=True)
with tarfile.open(archive) as bundle:
    bundle.extractall(BACKEND,filter="data")
formal=subprocess.check_output(["git","show",PIN+":specs/openapi.yaml"],cwd=ROOT)
assert (BACKEND/"specs/openapi.yaml").read_bytes()==formal
schema=yaml.safe_load(formal)
operations={}
for path,methods in schema["paths"].items():
    operation=methods.get("get",{})
    name=operation.get("operationId")
    if name in {"bossDashboardRead","bossMeetingsRead","bossEvidenceRead"}:
        operations[name]={"path":path,"method":"GET","parameters":operation.get("parameters",[])}
assert len(operations)==3
environment=os.environ.copy()
environment.pop("PYTHONPATH",None)
environment["PYTHONDONTWRITEBYTECODE"]="1"
environment["TMPDIR"]=str(WORK)
xml=WORK/"sop-read-green.xml"
subprocess.run([sys.executable,"-m","pytest","evidence/T07/test_sop_read_tools.py","-q",
                "--basetemp="+str(WORK/"sop-read-green"),"--junitxml="+str(xml)],
               cwd=ROOT,env=environment,check=True)
suite=ElementTree.parse(xml).getroot().find("testsuite")
assert suite is not None and suite.get("errors")=="0" and suite.get("failures")=="0" and suite.get("skipped")=="0"
identity=json.loads((WORK/"sop-read-imports.json").read_text(encoding="utf-8"))
catalog=json.loads((WORK/"sop-read-catalog.json").read_text(encoding="utf-8"))
paths=["validation/runtime_page_read_tools.py","evidence/T07/test_sop_read_tools.py",
       "evidence/T07/check_sop_read_tools.py","specs/agent-assets.json"]
report={
    "work_item_id":"T07-SOP-READ-ADAPTERS","checked_at":datetime.now().astimezone().isoformat(),
    "code_base_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
    "source_commit":PIN,"source_distribution":"IMMUTABLE_COMMITTED_W3_BACKEND",
    "formal_read_contract_version":schema["info"]["version"],"operations":operations,
    "result":"PASS_LOCAL_READ_ADAPTERS","tests":int(suite.get("tests")),"seconds":float(suite.get("time")),
    "failures":0,"errors":0,"skipped":0,
    "cases":[{"name":case.get("name"),"seconds":float(case.get("time"))} for case in suite.findall("testcase")],
    "implementation_sha256":{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths},
    **identity,
    "data_source":"EXISTING_COMMITTED_SIMULATED_SELECTION_AND_FORMAL_LOCAL_ACTIONS",
    "read_mutation_check":"FULL_SQLITE_LOGICAL_DUMP_EQUAL_BEFORE_AFTER_EVERY_SUCCESS_AND_DENIAL",
    "fixture_actions":"独立资料库中的BOSS目标和会议确认，以及MAINTAINER来源新增、换版与撤销；各项读取前后单独比较完整资料库",
    "external_requests":0,"stt":"DEFERRED_BY_USER","public_runtime_registration":"NOT_RUN",
    "model_adoption":"NOT_RUN","parent_A07_accepted":False,"parent_A16_accepted":False,
    "registry":"ACTUAL_NANOBOT_TOOL_REGISTRY_WITH_FIVE_EXISTING_TOOLS_AND_THREE_NEW_READ_TOOLS",
    "native_sop_coverage":[{key:item[key] for key in ("sop_id","missing_tools","context_eligible")} for item in catalog["items"]],
    "remaining":"W3在正式配置许可范围注册工具，在同一集成版本验证完整SOP和页面业务采用",
}
output=ROOT/"evidence/T07/w2-20261023-sop-read-tools.json"
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"report":str(output),"tests":report["tests"],"result":report["result"]},ensure_ascii=False))
