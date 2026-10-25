import hashlib
import json
import subprocess
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[2]
W1_COMMIT="1db14662c82b91e33f7a5dc3d6cc97d93d3a7fbb"
W3_COMMIT="7aab4405b77887b3a2f242dde8c256247c0926f1"


def source(commit,path):
    return subprocess.check_output(["git","show",commit+":"+path],cwd=ROOT)


backend=yaml.safe_load(source(W3_COMMIT,"specs/openapi.yaml"))
operations={}
for path,value in backend["paths"].items():
    for method,item in value.items():
        if isinstance(item,dict) and item.get("operationId") in {"bossDashboardRead","bossMeetingsRead","bossEvidenceRead"}:
            operations[item["operationId"]]={"path":path,"method":method,"definition":item}
files={}
for name in ("boss_page_api","boss_meetings","business","controls","boss_source_access","boss_memory"):
    path="validation/"+name+".py"
    files[path]={"W1_sha256":hashlib.sha256(source(W1_COMMIT,path)).hexdigest(),
                 "W3_sha256":hashlib.sha256(source(W3_COMMIT,path)).hexdigest(),
                 "W2_sha256":hashlib.sha256((ROOT/path).read_bytes()).hexdigest() if (ROOT/path).exists() else None}
print(json.dumps({"W1_commit":W1_COMMIT,"W3_commit":W3_COMMIT,"formal_version":backend["info"]["version"],
                  "operations":operations,"source_files":files},ensure_ascii=False,indent=2))
