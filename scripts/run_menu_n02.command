#!/bin/bash
set -euo pipefail
MENU_N02_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BOSS_VALIDATION_ROOT="$MENU_N02_ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION
export BOSS_DEMO_ACCOUNT_INJECTION=1
export BOSS_INITIAL_PAGE=N02
export BOSS_PRODUCT_FRONTEND_DIR="$MENU_N02_ROOT/menu-n02-n3-dist"
export BOSS_APPLICATION_WORK_DIR="${BOSS_MENU_N02_WORK_DIRECTORY:-$MENU_N02_ROOT/validation/.work/menu-n02-release-experience}"
export BOSS_APPLICATION_PORTS='{"business":10711,"webui":10712,"gateway":20711}'
if [[ -n "${BOSS_MENU_N02_PORTS:-}" ]]; then
  export BOSS_APPLICATION_PORTS="$BOSS_MENU_N02_PORTS"
fi
export TMPDIR="$MENU_N02_ROOT/validation/.work/menu-n02-launch-tmp"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR"
"$MENU_N02_ROOT/validation/.venv/bin/python" "$MENU_N02_ROOT/scripts/prepare_menu_n02.py" --directory "$BOSS_APPLICATION_WORK_DIR" --frontend "$BOSS_PRODUCT_FRONTEND_DIR" --ports "$BOSS_APPLICATION_PORTS"
echo "聊天交办：独立模拟资料、连续会话及原编号核查。既有账号仅填入表单，登录由本人提交。"
cd "$MENU_N02_ROOT/validation/desktop"
exec ./node_modules/.bin/electron . "$@"
