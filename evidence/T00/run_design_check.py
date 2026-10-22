import subprocess
import sys
from pathlib import Path


root = Path.cwd()
capture = Path("/Users/liuhaoxian/.agents/skills/haonan-s000-pmp/scripts/capture_check.py")
inputs = [
    "docs/Boss-Agent需求输入.md",
    "docs/Boss-Agent项目计划.md",
    "docs/项目决策记录.md",
    "specs/value-validation.json",
    "docs/README.md",
    "docs/计划环境记录.md",
    "evidence/T00/check_strategy.py",
    "evidence/T00/run_design_check.py",
]
command = [
    sys.executable, str(capture),
    "--output-dir", str(root / "evidence/T00/merged-design-check"),
    "--check-id", "K00", "--kind", "STATIC",
    "--baseline-id", "boss-agent-t00-design-20261021",
    "--cwd", str(root), "--timeout", "60",
]
for name in inputs:
    command.extend(["--input", name])
command.extend(["--", sys.executable, "evidence/T00/check_strategy.py"])
subprocess.run(command, check=True)
print((root / "evidence/T00/merged-design-check/output.log").read_text())
