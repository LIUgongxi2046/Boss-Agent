import argparse
import subprocess
import sys

from business import ROOT


parser = argparse.ArgumentParser()
parser.add_argument("run_name")
args = parser.parse_args()
command = [sys.executable, "/Users/liuhaoxian/.agents/skills/haonan-s000-pmp/scripts/capture_check.py", "--output-dir", str(ROOT.parent / "evidence/T02" / args.run_name), "--check-id", "K02-ui-reuse", "--kind", "INTEGRATION", "--baseline-id", "boss-agent-t00-design-20261021", "--cwd", str(ROOT.parent), "--timeout", "600"]
for name in ["business.py", "controls.py", "service.py", "connection.py", "model_probe.py", "application.py", "role_channel.py", "check_reuse.py", "check_ui_business.py", "check_admin.py", "capture_reuse.py", "uv.lock", "pyproject.toml", "connection.json"]:
    command.extend(["--input", str(ROOT / name)])
command.extend(["--input", str(ROOT.parent / "specs/selection-probe.json"), "--", sys.executable, str(ROOT / "check_reuse.py")])
subprocess.run(command, check=True)
