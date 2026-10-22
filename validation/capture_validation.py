import argparse
import subprocess
import sys

from business import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=["models", "runtime", "faults", "desktop"])
    parser.add_argument("run_name")
    args = parser.parse_args()
    commands = {"models": ([sys.executable, str(ROOT / "model_probe.py")], "K02-models", "EXTERNAL"), "runtime": ([sys.executable, str(ROOT / "check_runtime.py")], "K02-runtime", "INTEGRATION"), "faults": ([sys.executable, str(ROOT / "fault_probe.py")], "K02-runtime", "INTEGRATION"), "desktop": (["node", str(ROOT / "desktop/check-desktop.cjs")], "K02-desktop", "INTEGRATION")}
    command, check_id, kind = commands[args.scope]
    capture = "/Users/liuhaoxian/.agents/skills/haonan-s000-pmp/scripts/capture_check.py"
    files = {
        "models": ["business.py", "connection.py", "model_probe.py"],
        "runtime": ["business.py", "controls.py", "service.py", "check_runtime.py", "check_materials.py", "check_local.py", "check_scheduler.py", "check_controls.py"],
        "faults": ["business.py", "controls.py", "service.py", "connection.py", "model_probe.py", "fault_probe.py"],
        "desktop": ["business.py", "controls.py", "service.py", "connection.py", "model_probe.py", "application.py", "role_channel.py", "desktop/check-desktop.cjs", "desktop/main.cjs", "desktop/preload.cjs", "desktop/package.json", "desktop/package-lock.json"],
    }
    inputs = [ROOT / filename for filename in files[args.scope]] + [ROOT / "capture_validation.py", ROOT / "uv.lock", ROOT / "pyproject.toml", ROOT / "connection.json", ROOT.parent / "specs/selection-probe.json"]
    arguments = [sys.executable, capture, "--output-dir", str(ROOT.parent / "evidence/T02" / args.run_name), "--check-id", check_id, "--kind", kind, "--baseline-id", "boss-agent-t00-design-20261021", "--cwd", str(ROOT.parent), "--timeout", "600"]
    for path in inputs:
        arguments.extend(["--input", str(path)])
    subprocess.run([*arguments, "--", *command], check=True)


if __name__ == "__main__":
    main()
