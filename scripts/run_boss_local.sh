#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/.work/product/nanobot/nanobot/web/dist/index.html"
PYTHON="$ROOT/validation/.venv/bin/python"
if [[ ! -f "$DIST" ]]; then
  echo "缺少产品构建。请先运行：python3 scripts/prepare_boss_webui.py --build" >&2
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "缺少 Python 环境。请先在 validation/ 目录运行 uv sync --locked。" >&2
  exit 2
fi
if [[ ! -d "$ROOT/validation/desktop/node_modules" ]]; then
  echo "缺少 Electron 依赖。请先执行 npm --prefix validation/desktop ci。" >&2
  exit 2
fi
export BOSS_VALIDATION_ROOT="$ROOT/validation"
export BOSS_PRODUCT_UI=1
echo "启动 Boss-Agent v6 React + nanobot 本地研发环境（联网 DeepSeek，不是离线模型）。"
cd "$ROOT"
exec npm --prefix validation/desktop run start
