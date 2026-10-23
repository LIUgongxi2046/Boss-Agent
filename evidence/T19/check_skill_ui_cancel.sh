set -euo pipefail
task_project="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$task_project"
task_pid="$(validation/.venv/bin/python -c 'import json; from pathlib import Path; print(json.loads(Path(".work/w2-checks/skill-ui/server.json").read_text())["pid"])')"
task_command="$(ps -p "$task_pid" -o command=)"
case "$task_command" in
  *evidence/T19/check_skill_ui_server.py*) ;;
  *) exit 1 ;;
esac
trap 'kill -CONT "$task_pid"' EXIT
kill -STOP "$task_pid"
bash evidence/T19/runtime_ui_cli.sh run-code --filename=../../../evidence/T19/check_skill_ui_cancel.js
