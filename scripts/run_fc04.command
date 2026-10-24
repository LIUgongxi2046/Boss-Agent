#!/bin/bash
set -euo pipefail
FC04_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BOSS_VALIDATION_ROOT="$FC04_ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION
export BOSS_INITIAL_PAGE=F02
export BOSS_PRODUCT_FRONTEND_DIR="$FC04_ROOT/fc04-n3-dist"
export BOSS_APPLICATION_WORK_DIR="${BOSS_FC04_WORK_DIRECTORY:-$FC04_ROOT/validation/.work/mvp01-experience}"
export BOSS_APPLICATION_PORTS='{"business":9961,"webui":9962,"gateway":19961}'
if [[ -n "${BOSS_FC04_PORTS:-}" ]]; then
  export BOSS_APPLICATION_PORTS="$BOSS_FC04_PORTS"
fi
export TMPDIR="$FC04_ROOT/validation/.work/fc04-launch-tmp"
mkdir -p "$TMPDIR"
"$FC04_ROOT/validation/.venv/bin/python" "$FC04_ROOT/scripts/prepare_fc04.py" --directory "$BOSS_APPLICATION_WORK_DIR" --ports "$BOSS_APPLICATION_PORTS"
echo "账号文件位于：$BOSS_APPLICATION_WORK_DIR/accounts/credentials.json"
cd "$FC04_ROOT/validation/desktop"
exec ./node_modules/.bin/electron . "$@"
