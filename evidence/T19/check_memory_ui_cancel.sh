set -euo pipefail
task_pid="$1"
task_command="$(ps -p "$task_pid" -o command=)"
case "$task_command" in
  *"Python evidence/T19/check_memory_ui_server.py --database .work/w2-checks/memory-ui/"*) ;;
  *) exit 1 ;;
esac
trap 'kill -CONT "$task_pid"' EXIT
kill -STOP "$task_pid"
bash evidence/T19/memory_ui_cli.sh run-code --filename ../../../evidence/T19/check_memory_ui_cancel.js
