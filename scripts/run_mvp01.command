#!/bin/bash
set -euo pipefail
MVP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BOSS_VALIDATION_ROOT="$MVP_ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-MVP-1
export BOSS_PRODUCT_FRONTEND_DIR="$MVP_ROOT/mvp01-n3-dist"
export BOSS_APPLICATION_WORK_DIR="$MVP_ROOT/validation/.work/mvp01-experience"
export BOSS_APPLICATION_PORTS='{"business":9961,"webui":9962,"gateway":19961}'
export TMPDIR="$MVP_ROOT/validation/.work/mvp01-launch-tmp"
mkdir -p "$TMPDIR"
"$MVP_ROOT/validation/.venv/bin/python" "$MVP_ROOT/scripts/prepare_mvp01.py"
echo "本人账号信息位于：$BOSS_APPLICATION_WORK_DIR/accounts/credentials.json"
echo "采购成本体验入口：http://127.0.0.1:9962"
cd "$MVP_ROOT/validation/desktop"
exec ./node_modules/.bin/electron . "$@"
