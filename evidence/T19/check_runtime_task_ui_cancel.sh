set -euo pipefail
task_pid="$1"
task_command="$(ps -p "$task_pid" -o command=)"
case "$task_command" in
  *"Python evidence/T19/check_runtime_ui_server.py --database validation/.work/w2-written-client-closed-"*"--copy-to .work/w2-checks/runtime-task-ui/business.sqlite"*) ;;
  *) exit 1 ;;
esac
trap 'kill -CONT "$task_pid"' EXIT
kill -STOP "$task_pid"
bash evidence/T19/runtime_ui_cli.sh run-code --filename ../../../evidence/T19/check_runtime_task_ui_cancel.js
