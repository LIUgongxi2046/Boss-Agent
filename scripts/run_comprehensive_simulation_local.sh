#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIMULATION_DIRECTORY="$ROOT/validation/.work/comprehensive-simulation-20261028"
SIMULATION_FRONTEND="$ROOT/.work/simulation-20261028/admin-dist"
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--desktop" ) ]]; then
  echo "用法：bash scripts/run_comprehensive_simulation_local.sh [--desktop]" >&2
  exit 2
fi
if [[ ! -f "$SIMULATION_DIRECTORY/business.sqlite" || ! -f "$SIMULATION_DIRECTORY/accounts/accounts.sqlite" || ! -f "$SIMULATION_FRONTEND/index.html" ]]; then
  echo "独立仿真资料、账号或前端制品尚未准备。" >&2
  exit 2
fi
export BOSS_VALIDATION_ROOT="$ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_DEMO_ACCOUNT_INJECTION=1
export BOSS_REVIEW_RUNTIME_SETUP=1
export BOSS_APPLICATION_WORK_DIR="$SIMULATION_DIRECTORY"
export BOSS_PRODUCT_FRONTEND_DIR="$SIMULATION_FRONTEND"
export BOSS_APPLICATION_PORTS='{"business":9081,"webui":9082,"gateway":18892}'
unset BOSS_EXECUTION_SCOPE
if [[ "${1:-}" == "--desktop" ]]; then
  export BOSS_INITIAL_PAGE=F01
  export TMPDIR="$ROOT/.work/simulation-20261028/desktop-temp"
  unset ELECTRON_RUN_AS_NODE BOSS_DESKTOP_TEST_WINDOW_HIDDEN
  mkdir -p "$TMPDIR"
  cd "$ROOT/validation/desktop"
  exec ./node_modules/.bin/electron .
fi
cd "$ROOT/validation"
exec "$ROOT/validation/.venv/bin/python" application.py
