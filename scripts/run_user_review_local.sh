#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REVIEW_DIRECTORY="$ROOT/validation/.work/user-review-20261027-r2"
REVIEW_FRONTEND="$ROOT/.work/user-review-20261027/dist-testing-final"
if [[ ! -f "$REVIEW_DIRECTORY/business.sqlite" ]]; then
  echo "独立验收资料尚未准备。" >&2
  exit 2
fi
if [[ ! -f "$REVIEW_DIRECTORY/accounts/accounts.sqlite" ]]; then
  echo "独立验收账号尚未创建，需要取得初始化认证授权。" >&2
  exit 2
fi
if [[ ! -f "$REVIEW_FRONTEND/index.html" ]]; then
  echo "独立验收前端尚未构建。" >&2
  exit 2
fi
export BOSS_VALIDATION_ROOT="$ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_DEMO_ACCOUNT_INJECTION=1
export BOSS_REVIEW_RUNTIME_SETUP=1
export BOSS_APPLICATION_WORK_DIR="$REVIEW_DIRECTORY"
export BOSS_PRODUCT_FRONTEND_DIR="$REVIEW_FRONTEND"
export BOSS_APPLICATION_PORTS='{"business":9071,"webui":9072,"gateway":18891}'
unset BOSS_EXECUTION_SCOPE
cd "$ROOT/validation"
exec "$ROOT/validation/.venv/bin/python" application.py
