#!/bin/bash
set -euo pipefail
UI02_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BOSS_VALIDATION_ROOT="$UI02_ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION
export BOSS_DEMO_ACCOUNT_INJECTION=1
export BOSS_INITIAL_PAGE=F01
export BOSS_PRODUCT_FRONTEND_DIR="$UI02_ROOT/ui02-n3-dist"
export BOSS_APPLICATION_WORK_DIR="${BOSS_UI02_WORK_DIRECTORY:-$UI02_ROOT/validation/.work/ui02-experience}"
export BOSS_APPLICATION_PORTS='{"business":10411,"webui":10412,"gateway":20411}'
if [[ -n "${BOSS_UI02_PORTS:-}" ]]; then
  export BOSS_APPLICATION_PORTS="$BOSS_UI02_PORTS"
fi
export TMPDIR="$UI02_ROOT/validation/.work/ui02-launch-tmp"
mkdir -p "$TMPDIR"
"$UI02_ROOT/validation/.venv/bin/python" "$UI02_ROOT/scripts/prepare_fc04.py" --directory "$BOSS_APPLICATION_WORK_DIR" --frontend "$BOSS_PRODUCT_FRONTEND_DIR" --ports "$BOSS_APPLICATION_PORTS" --feature-id UI02
echo "UI02：本人会话与维护设置使用同一产品导航。本机账号仅填入表单，登录仍由服务端认证。"
cd "$UI02_ROOT/validation/desktop"
exec ./node_modules/.bin/electron . "$@"
