#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/.work/product/nanobot/nanobot/web/dist/index.html"
PYTHON="$ROOT/validation/.venv/bin/python"
# Credentials stay on this Mac. The user-provided Markdown is Git-ignored,
# and the generated connection.json stores only a file reference.
if [[ ! -f "$ROOT/boss agent.md" ]]; then
  echo "缺少本机凭据文件 boss agent.md。请先将用户提供的附件保存于项目根目录。" >&2
  exit 2
fi
python3 "$ROOT/scripts/configure_local_deepseek.py" >/dev/null
if [[ ! -f "$ROOT/validation/connection.json" ]]; then
  echo "本机服务端 DeepSeek 连接配置未生成，拒绝启动。" >&2
  exit 2
fi
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
