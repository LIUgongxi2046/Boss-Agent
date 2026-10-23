import json
import subprocess
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[2]
PIN="2161bb41c3fb31a384e8d3fd993b874ff6c33aa6"
schema=yaml.safe_load(subprocess.check_output(["git","show",PIN+":specs/openapi.yaml"],cwd=ROOT))
names={"bossTasksRead","bossCalendarConflictRead","bossCalendarSharePreview","bossWorkspaceRead"}
operations={}
for path,methods in schema["paths"].items():
    for method,value in methods.items():
        if isinstance(value,dict) and value.get("operationId") in names:
            operations[value["operationId"]]={"path":path,"method":method,"definition":value}
assert set(operations)==names
print(json.dumps({"source_commit":PIN,"formal_version":schema["info"]["version"],"operations":operations},ensure_ascii=False,indent=2))
