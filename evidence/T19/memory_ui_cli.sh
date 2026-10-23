set -euo pipefail
task_project="$(cd "$(dirname "$0")/../.." && pwd)"
export PWTEST_SOCKETS_DIR="$task_project/.work/pw"
export TMPDIR="$task_project/.work/w2-checks"
export npm_config_cache="$task_project/.work/w2-checks/npm-cache"
mkdir -p "$PWTEST_SOCKETS_DIR"
cd "$task_project/.work/w2-checks/runtime-ui"
exec /Users/liuhaoxian/.codex/skills/playwright/scripts/playwright_cli.sh -s=w2-memory "$@"
