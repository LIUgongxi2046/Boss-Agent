import json
import subprocess
import sys
from pathlib import Path

from business import ROOT


project = ROOT.parent
capture = "/Users/liuhaoxian/.agents/skills/haonan-s000-pmp/scripts/capture_check.py"
for name in ["models", "runtime", "faults", "reuse", "desktop"]:
    original_path = project / "evidence/T02" / (name + "-current-evidence") / "receipt.json"
    original = json.loads(original_path.read_text())
    inputs = [Path(item["path"]) for item in original["inputs"]]
    inputs += [original_path, ROOT / "verify_saved_check.py", Path(__file__), project / "docs/计划环境记录.md", project / "docs/选型环境.md", project / "evidence/T02/stage-decision.json"]
    command = [sys.executable, capture, "--output-dir", str(project / "evidence/T02" / ("feasibility-bound-" + name)), "--check-id", original["check_id"], "--kind", original["kind"], "--baseline-id", original["baseline_id"], "--cwd", str(project), "--timeout", "60"]
    for path in dict.fromkeys(inputs):
        command.extend(["--input", str(path)])
    for artifact in original["artifacts"]:
        command.extend(["--artifact", artifact["path"]])
    command.extend(["--artifact", str(original_path), "--", sys.executable, str(ROOT / "verify_saved_check.py"), str(original_path)])
    subprocess.run(command, check=True)
