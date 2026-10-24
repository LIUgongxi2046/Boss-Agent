#!/bin/bash
set -euo pipefail
MENU_F01_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BOSS_VALIDATION_ROOT="$MENU_F01_ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION
export BOSS_DEMO_ACCOUNT_INJECTION=1
export BOSS_INITIAL_PAGE=F01
export BOSS_PRODUCT_FRONTEND_DIR="$MENU_F01_ROOT/menu-f01-n3-dist"
export BOSS_APPLICATION_WORK_DIR="${BOSS_MENU_F01_WORK_DIRECTORY:-$MENU_F01_ROOT/validation/.work/menu-f01-experience}"
export BOSS_APPLICATION_PORTS='{"business":10611,"webui":10612,"gateway":20611}'
if [[ -n "${BOSS_MENU_F01_PORTS:-}" ]]; then
  export BOSS_APPLICATION_PORTS="$BOSS_MENU_F01_PORTS"
fi
export TMPDIR="$MENU_F01_ROOT/validation/.work/menu-f01-launch-tmp"
mkdir -p "$TMPDIR"
"$MENU_F01_ROOT/validation/.venv/bin/python" "$MENU_F01_ROOT/scripts/prepare_menu_f01.py" --directory "$BOSS_APPLICATION_WORK_DIR" --frontend "$BOSS_PRODUCT_FRONTEND_DIR" --ports "$BOSS_APPLICATION_PORTS"
echo "今日工作：独立模拟资料、原生会话及当前事项。测试账号仅填入表单，登录由本人提交。"
cd "$MENU_F01_ROOT/validation/desktop"
exec ./node_modules/.bin/electron . "$@"
