#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
comparison_dir="$project_dir/.work/user-review-20261027"
source_dir="$comparison_dir/native-upstream"
instance_dir="$comparison_dir/native-instance"

test -f "$source_dir/nanobot/web/dist/index.html"
mkdir -p "$instance_dir/workspace"
cd "$source_dir"
export PYTHONPATH="$source_dir"
exec "$project_dir/validation/.venv/bin/python" -m nanobot webui \
  --config "$instance_dir/config.json" \
  --workspace "$instance_dir/workspace" \
  --port 9172 --gateway-port 18991 --no-open --yes
