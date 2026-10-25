#!/bin/bash
set -euo pipefail
UI01_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BOSS_VALIDATION_ROOT="$UI01_ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION
export BOSS_DEMO_ACCOUNT_INJECTION=1
export BOSS_INITIAL_PAGE=F01
export BOSS_PRODUCT_FRONTEND_DIR="$UI01_ROOT/ui01-n3-dist"
export BOSS_APPLICATION_WORK_DIR="${BOSS_UI01_WORK_DIRECTORY:-$UI01_ROOT/validation/.work/mvp01-experience}"
export BOSS_APPLICATION_PORTS='{"business":9961,"webui":9962,"gateway":19961}'
if [[ -n "${BOSS_UI01_PORTS:-}" ]]; then
  export BOSS_APPLICATION_PORTS="$BOSS_UI01_PORTS"
fi
export TMPDIR="$UI01_ROOT/validation/.work/ui01-launch-tmp"
mkdir -p "$TMPDIR"
"$UI01_ROOT/validation/.venv/bin/python" "$UI01_ROOT/scripts/prepare_fc04.py" --directory "$BOSS_APPLICATION_WORK_DIR" --frontend "$BOSS_PRODUCT_FRONTEND_DIR" --ports "$BOSS_APPLICATION_PORTS" --feature-id UI01
echo "本机演示入口：测试账号仅填入表单，登录仍由服务端认证。"
cd "$UI01_ROOT/validation/desktop"
exec ./node_modules/.bin/electron . "$@"
