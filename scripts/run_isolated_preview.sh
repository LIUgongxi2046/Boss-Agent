#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_ROOT="$PROJECT_ROOT/.work/upgrade2-u2-08-simulated/isolated-preview-001"
WORK_DIR="$DATA_ROOT/application"
VENV_ROOT="$PROJECT_ROOT/.work/upgrade2/u2-01/product-venv-007"
PYTHON="$VENV_ROOT/bin/python"
FRONTEND="$VENV_ROOT/lib/python3.12/site-packages/boss-preview-026"
TEMP_DIR="$DATA_ROOT/temp"

if [[ ! -x "$PYTHON" ]]; then
  echo "独立 Python 环境尚未准备完成。" >&2
  exit 1
fi
"$PYTHON" -I -c 'from pathlib import Path; from boss_agent_runtime.application_paths import _reject_symlink_components; import sys; _reject_symlink_components(Path(sys.argv[1]), allow_missing=True); _reject_symlink_components(Path(sys.argv[2]), allow_missing=True)' "$DATA_ROOT" "$WORK_DIR/accounts"
if [[ ! -f "$WORK_DIR/accounts/accounts.sqlite" || -L "$WORK_DIR/accounts/accounts.sqlite" || -L "$WORK_DIR/accounts" || -L "$WORK_DIR" || -L "$DATA_ROOT" ]]; then
  echo "独立账号尚未准备完成；账号必须位于独立应用目录且不能使用符号链接。" >&2
  exit 1
fi
if [[ ! -d "$TEMP_DIR" || -L "$TEMP_DIR" ]]; then
  echo "独立临时目录尚未准备完成，且不能使用符号链接。" >&2
  exit 1
fi
if [[ ! -f "$FRONTEND/index.html" ]]; then
  echo "独立前端制品尚未准备完成。" >&2
  exit 1
fi
ACCOUNT_DIR="$WORK_DIR/accounts"
ACCOUNT_FILE="$ACCOUNT_DIR/accounts.sqlite"
CURRENT_UID="$(id -u)"
if [[ "$(stat -f '%u:%Lp' "$DATA_ROOT")" != "$CURRENT_UID:700" || \
      "$(stat -f '%u:%Lp' "$WORK_DIR")" != "$CURRENT_UID:700" || \
      "$(stat -f '%u:%Lp' "$TEMP_DIR")" != "$CURRENT_UID:700" || \
      "$(stat -f '%u:%Lp' "$ACCOUNT_DIR")" != "$CURRENT_UID:700" || \
      "$(stat -f '%u:%Lp:%l' "$ACCOUNT_FILE")" != "$CURRENT_UID:600:1" ]]; then
  echo "独立账号目录或数据库的所有者、权限或链接数量不符合要求。" >&2
  exit 1
fi
if [[ -L "$WORK_DIR/config.json" || -L "$WORK_DIR/runtime-scope.json" ]] || \
   { [[ -e "$WORK_DIR/config.json" ]] && [[ ! -e "$WORK_DIR/runtime-scope.json" ]]; } || \
   { [[ ! -e "$WORK_DIR/config.json" ]] && [[ -e "$WORK_DIR/runtime-scope.json" ]]; }; then
  echo "独立应用配置和实例目录声明必须同时存在或同时缺失。" >&2
  exit 1
fi
for port in 18871 18872 18873 18874; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "独立预览需要的本机端口 $port 已被占用。" >&2
    exit 1
  fi
done
if ! git -C "$PROJECT_ROOT" apply --reverse --check --directory=.work/upgrade2/u2-01/product-venv-007/lib/python3.12/site-packages patches/nanobot-session-isolation.patch; then
  echo "独立 Python 环境缺少已核查的会话隔离补丁。" >&2
  exit 1
fi

cd "$WORK_DIR"
exec env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin \
  TMPDIR="$TEMP_DIR" PYTHONDONTWRITEBYTECODE=1 \
  BOSS_PRODUCT_UI=1 BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION \
  BOSS_ISOLATED_SESSIONS=1 BOSS_DEMO_ACCOUNT_INJECTION=0 \
  BOSS_AGENT_RUN_PORT=18874 \
  BOSS_APPLICATION_DATA_ROOT="$DATA_ROOT" BOSS_APPLICATION_WORK_DIR="$WORK_DIR" BOSS_PRODUCT_FRONTEND_DIR="$FRONTEND" \
  BOSS_APPLICATION_PORTS='{"business":18871,"webui":18872,"gateway":18873}' \
  sandbox-exec -D VENV_ROOT="$VENV_ROOT" -D FRONTEND_ROOT="$FRONTEND" -D WORK_ROOT="$DATA_ROOT" -D TEMP_ROOT="$TEMP_DIR" -f "$PROJECT_ROOT/scripts/isolated-preview.sb" \
  "$PYTHON" -I -c 'from boss_agent_runtime.boss_agent_runtime_bootstrap import main; main()'
