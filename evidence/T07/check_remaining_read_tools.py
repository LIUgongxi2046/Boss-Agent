import hashlib
import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from xml.etree import ElementTree

import yaml

ROOT=Path(__file__).resolve().parents[2]
PIN="2161bb41c3fb31a384e8d3fd993b874ff6c33aa6"
WORK=ROOT/".work/w2-checks"
BACKEND=WORK/"remaining-read-backend"
WORK.mkdir(parents=True,exist_ok=True)
BACKEND.mkdir(parents=True,exist_ok=True)
archive=WORK/"remaining-read-backend.tar"
subprocess.run(["git","archive","--format=tar","--output="+str(archive),PIN,"validation","specs"],cwd=ROOT,check=True)
with tarfile.open(archive) as bundle:
    bundle.extractall(BACKEND,filter="data")
formal=subprocess.check_output(["git","show",PIN+":specs/openapi.yaml"],cwd=ROOT)
assert (BACKEND/"specs/openapi.yaml").read_bytes()==formal
schema=yaml.safe_load(formal)
names={"bossTasksRead","bossCalendarConflictRead","bossCalendarSharePreview","bossWorkspaceRead"}
operations={methods["get"]["operationId"]:{"path":path,"definition":methods["get"]}
            for path,methods in schema["paths"].items() if methods.get("get",{}).get("operationId") in names}
assert set(operations)==names
environment=os.environ.copy()
environment.pop("PYTHONPATH",None)
environment["PYTHONDONTWRITEBYTECODE"]="1"
environment["TMPDIR"]=str(WORK)
xml=WORK/"remaining-read-green.xml"
subprocess.run([sys.executable,"-m","pytest","evidence/T07/test_remaining_read_tools.py","-q",
                "--basetemp="+str(WORK/"remaining-read-green"),"--junitxml="+str(xml)],
               cwd=ROOT,env=environment,check=True)
suite=ElementTree.parse(xml).getroot().find("testsuite")
assert suite is not None and all(suite.get(key)=="0" for key in ("errors","failures","skipped"))
observed=json.loads((WORK/"remaining-read-observations.json").read_text(encoding="utf-8"))
files=["validation/runtime_sop_read_tools.py","validation/runtime_page_read_tools.py",
       "validation/boss_agent_read_tools.py","validation/boss_native_skills.py",
       "evidence/T07/test_remaining_read_tools.py","evidence/T07/check_remaining_read_tools.py","specs/agent-assets.json"]
report={
    "work_item_id":"T07-REMAINING-READ-ADAPTERS","checked_at":datetime.now().astimezone().isoformat(),
    "code_base_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
    "source_commit":PIN,"formal_read_contract_version":schema["info"]["version"],"operations":operations,
    "result":"PASS_LOCAL_REMAINING_READ_ADAPTERS","tests":int(suite.get("tests")),"seconds":float(suite.get("time")),
    "failures":0,"errors":0,"skipped":0,"external_requests":0,"stt":"DEFERRED_BY_USER",
    "cases":[{"name":case.get("name"),"seconds":float(case.get("time"))} for case in suite.findall("testcase")],
    "implementation_sha256":{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in files},
    "native_skill_sha256":{path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sorted((ROOT/"agent/skills").glob("boss-sop*/SKILL.md"))},
    "runtime_versions":{"python":sys.version.split()[0],"nanobot-ai":version("nanobot-ai"),"jsonschema":version("jsonschema")},
    **observed,
    "data_source":"EXISTING_COMMITTED_SIMULATED_SELECTION_AND_FORMAL_LOCAL_ACTIONS",
    "read_mutation_check":"FULL_SQLITE_LOGICAL_DUMP_EQUAL_AT_READ_CHECKPOINTS",
    "fixture_actions":"使用正式本地操作准备任务、纪要、研究、人员材料、行程、分享、记忆及标明SIMULATED的申请；各项读取前后单独比较完整资料库",
    "public_runtime_registration":"NOT_RUN","model_adoption":"NOT_RUN","parent_A07_accepted":False,"parent_A16_accepted":False,
    "remaining":"公共配置准入、Runtime注册、各方法写操作及完整业务采用继续单独验证",
}
output=ROOT/"evidence/T07/w2-20261023-remaining-read-tools.json"
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"report":str(output),"tests":report["tests"],"result":report["result"]},ensure_ascii=False))
