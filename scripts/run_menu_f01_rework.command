#!/bin/bash
set -euo pipefail
MENU_F01_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BOSS_VALIDATION_ROOT="$MENU_F01_ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION
export BOSS_DEMO_ACCOUNT_INJECTION=1
export BOSS_INITIAL_PAGE=F01
export BOSS_PRODUCT_FRONTEND_DIR="$MENU_F01_ROOT/menu-f01-rework-n3-dist"
export BOSS_APPLICATION_WORK_DIR="${BOSS_MENU_F01_REWORK_WORK_DIRECTORY:-$MENU_F01_ROOT/validation/.work/menu-f01-rework-release-experience}"
export BOSS_APPLICATION_PORTS='{"business":10621,"webui":10622,"gateway":20621}'
if [[ -n "${BOSS_MENU_F01_REWORK_PORTS:-}" ]]; then
  export BOSS_APPLICATION_PORTS="$BOSS_MENU_F01_REWORK_PORTS"
fi
export TMPDIR="$MENU_F01_ROOT/validation/.work/menu-f01-rework-launch-tmp"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR"
"$MENU_F01_ROOT/validation/.venv/bin/python" "$MENU_F01_ROOT/scripts/prepare_menu_f01_rework.py" --directory "$BOSS_APPLICATION_WORK_DIR" --frontend "$BOSS_PRODUCT_FRONTEND_DIR" --ports "$BOSS_APPLICATION_PORTS"
echo "今日工作：独立模拟资料，既有账号仅填入表单，登录由本人提交。"
cd "$MENU_F01_ROOT/validation/desktop"
exec ./node_modules/.bin/electron . "$@"
