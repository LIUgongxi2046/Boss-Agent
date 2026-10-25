#!/bin/bash
# A deliberately opt-in N02 version-locked launcher for an existing,
# manually provisioned isolated review directory. No automatic login,
# credential access, initialization, demo data injection or auto-repair.
# Does not open or change the previously protected N02 v6 experience.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="${BOSS_N02_REVIEW_BUNDLE:-$ROOT/.work/product}"
REVIEW_WORK="${BOSS_N02_REVIEW_WORK_DIR:-$ROOT/validation/.work/menu-n02-v7-review-local}"
PORTS="${BOSS_N02_REVIEW_PORTS:-}"
if [[ -z "$PORTS" ]]; then
  PORTS='{"business":11421,"webui":11422,"gateway":21421}'
fi
PYTHON="$ROOT/validation/.venv/bin/python"
ELECTRON="$ROOT/validation/desktop/node_modules/.bin/electron"

if [[ ! -x "$PYTHON" || ! -x "$ELECTRON" ]]; then
  echo "缺少已安装的 Python/Electron 依赖；本入口不会自动安装或认证。" >&2
  exit 2
fi

"$PYTHON" "$ROOT/scripts/verify_f01_candidate.py" --bundle "$BUNDLE" --require-head

export BOSS_N02_REVIEW_ROOT="$ROOT"
export BOSS_N02_REVIEW_WORK="$REVIEW_WORK"
export BOSS_N02_REVIEW_BUNDLE="$BUNDLE"
export BOSS_N02_REVIEW_PORTS="$PORTS"
"$PYTHON" - <<'PY'
import json
import os
import socket
from pathlib import Path

root = Path(os.environ["BOSS_N02_REVIEW_ROOT"]).resolve()
work = Path(os.environ["BOSS_N02_REVIEW_WORK"])
bundle = Path(os.environ["BOSS_N02_REVIEW_BUNDLE"])
allowed = (root / "validation/.work").resolve()
assert work.is_absolute() and work.resolve().parent == allowed and work.name.startswith("menu-n02-v7-review-"), (
    "N02复核必须采用工程内独立资料目录，不得复用任何原有用户体验"
)
assert work.is_dir() and not work.is_symlink(), "N02隔离资料目录尚未由本人显式准备"
for filename in ("accounts/accounts.sqlite", "accounts/credentials.json"):
    file = work / filename
    assert file.is_file() and not file.is_symlink(), "缺少已由本人独立准备的账号资料：" + filename
assert not (work / "instance.json").exists(), "N02目录有实例记录；不得自动复用或终止，请选择新的隔离目录"
assert bundle.resolve().is_relative_to(root), "编译文件必须位于当前项目范围内"
ports = json.loads(os.environ["BOSS_N02_REVIEW_PORTS"])
assert isinstance(ports, dict) and set(ports) == {"business", "webui", "gateway"}
values = list(ports.values())
assert len(set(values)) == 3 and all(type(port) is int and 1024 <= port <= 65535 for port in values)
protected = {8871,8872,18791,9961,9962,19961,10411,10412,20411,10611,10612,20611,10621,10622,20621,10711,10712,20711,10791,10792,20791,11321,11322,21321}
assert not (set(values) & protected), "N02隔离端口不能覆盖已有研发/用户体验"
for port in values:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
        check.bind(("127.0.0.1", port))
print("通过：源码提交、前端摘要、隔离资料与端口；后续登录必须由本人手动完成")
PY

export BOSS_VALIDATION_ROOT="$ROOT/validation"
export BOSS_PRODUCT_UI=1
export BOSS_EXECUTION_SCOPE=BOSS-PRIORITY-ITERATION
export BOSS_INITIAL_PAGE=N02
export BOSS_DEMO_ACCOUNT_INJECTION=0
export BOSS_PRODUCT_FRONTEND_DIR="$BUNDLE/nanobot/nanobot/web/dist"
export BOSS_APPLICATION_WORK_DIR="$REVIEW_WORK"
export BOSS_APPLICATION_PORTS="$PORTS"
export TMPDIR="$REVIEW_WORK/tmp"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$TMPDIR"
echo "仅在新的隔离目录启动 N02。未自动登录、未调用外部模型；由本人手动认证与检查。"
cd "$ROOT/validation/desktop"
exec "$ELECTRON" .
