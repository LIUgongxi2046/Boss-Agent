#!/bin/bash
set -euo pipefail
FC07_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BOSS_VALIDATION_ROOT="$FC07_ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION
export BOSS_PRODUCT_FRONTEND_DIR="$FC07_ROOT/fc07-n3-dist"
export BOSS_APPLICATION_WORK_DIR="${BOSS_FC07_WORK_DIRECTORY:-$FC07_ROOT/validation/.work/mvp01-experience}"
export BOSS_APPLICATION_PORTS='{"business":9961,"webui":9962,"gateway":19961}'
if [[ -n "${BOSS_FC07_PORTS:-}" ]]; then
  export BOSS_APPLICATION_PORTS="$BOSS_FC07_PORTS"
fi
export TMPDIR="$FC07_ROOT/validation/.work/fc07-launch-tmp"
mkdir -p "$TMPDIR"
"$FC07_ROOT/validation/.venv/bin/python" "$FC07_ROOT/scripts/prepare_fc07.py" --directory "$BOSS_APPLICATION_WORK_DIR" --ports "$BOSS_APPLICATION_PORTS"
echo "本人账号信息位于：$BOSS_APPLICATION_WORK_DIR/accounts/credentials.json"
cd "$FC07_ROOT/validation/desktop"
exec ./node_modules/.bin/electron . "$@"
