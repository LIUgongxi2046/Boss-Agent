import argparse
import subprocess
import sys
from pathlib import Path


root = Path.cwd()
parser = argparse.ArgumentParser(description="执行 T03 文字设计检查并保存当前版本证据")
parser.add_argument("run_name")
args = parser.parse_args()
capture = Path("/Users/liuhaoxian/.agents/skills/haonan-s000-pmp/scripts/capture_check.py")
command = [
    sys.executable, str(capture),
    "--output-dir", str(root / "evidence/T03" / args.run_name),
    "--check-id", "K03", "--kind", "STATIC",
    "--baseline-id", "boss-agent-t00-design-20261021",
    "--cwd", str(root), "--timeout", "60",
]
for filename in [
    "docs/交互与页面规范.md", "docs/PRD.md", "docs/Boss-Agent需求输入.md",
    "docs/项目决策记录.md", "docs/Boss-Agent项目计划.md", "docs/README.md",
    "docs/计划环境记录.md", "evidence/T03/check_interaction.py",
    "evidence/T03/run_design_checks.py",
    "/Users/liuhaoxian/.agents/skills/haonan-s003-2-ui/scripts/audit_ui_delivery.py",
]:
    command.extend(["--input", filename])
for artifact in [".planning-checks/t03-ui-audit/ui-audit.md", ".planning-checks/t03-ui-audit/screen-design-map.csv"]:
    command.extend(["--artifact", artifact])
command.extend(["--", sys.executable, "evidence/T03/check_interaction.py"])
subprocess.run(command, check=True)
print((root / "evidence/T03" / args.run_name / "output.log").read_text())
