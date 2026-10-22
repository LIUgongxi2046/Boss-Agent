import argparse
import subprocess
import sys
from pathlib import Path


root = Path.cwd()
parser = argparse.ArgumentParser(description="保存 T01 设计检查及前置引用复核的实际证据")
parser.add_argument("run_name")
args = parser.parse_args()
capture = Path("/Users/liuhaoxian/.agents/skills/haonan-s000-pmp/scripts/capture_check.py")
shared = [
    "docs/Boss-Agent需求输入.md", "docs/Boss-Agent项目计划.md",
    "docs/项目决策记录.md", "specs/value-validation.json", "docs/README.md",
    "docs/计划环境记录.md", "evidence/T01/run_design_checks.py",
]
checks = [
    ("K00", "prerequisite", "evidence/T00/check_strategy.py", ["evidence/T00/run_design_check.py"]),
    ("K01", "prd", "evidence/T01/check_prd.py", ["docs/PRD.md", "specs/selection-probe.json", "evidence/T01/check_mermaid.mjs", ".planning-checks/package.json", ".planning-checks/package-lock.json"]),
]
for check_id, directory, script, additional in checks:
    command = [
        sys.executable, str(capture),
        "--output-dir", str(root / "evidence/T01" / args.run_name / directory),
        "--check-id", check_id, "--kind", "STATIC",
        "--baseline-id", "boss-agent-t00-design-20261021",
        "--cwd", str(root), "--timeout", "60",
    ]
    for filename in shared + additional + [script]:
        command.extend(["--input", filename])
    command.extend(["--", sys.executable, script])
    subprocess.run(command, check=True)
    print((root / "evidence/T01" / args.run_name / directory / "output.log").read_text())
