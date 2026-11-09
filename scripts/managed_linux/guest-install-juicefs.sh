set -euo pipefail

SOURCE="$1"
TARGET=/usr/local/lib/boss-vm/juicefs
EXPECTED=6d450d3c151b6affede364d9a198d2505111b0612a5fb4d31613444c635174cc

if [[ "$(id -u)" != 0 || ! -f "$SOURCE" || -L "$SOURCE" || "$(realpath "$SOURCE")" != "$SOURCE" ]]; then
  echo "JuiceFS 安装来源不可核查。" >&2
  exit 1
fi
if [[ "$(sha256sum "$SOURCE" | cut -d ' ' -f 1)" != "$EXPECTED" ]]; then
  echo "JuiceFS 安装来源摘要不匹配。" >&2
  exit 1
fi
if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  echo "JuiceFS 安装目标已经存在。" >&2
  exit 1
fi
install -m 0755 "$SOURCE" "$TARGET"
if [[ "$(stat -c '%u:%a:%h' "$TARGET")" != '0:755:1' || "$(sha256sum "$TARGET" | cut -d ' ' -f 1)" != "$EXPECTED" ]]; then
  echo "JuiceFS 安装结果不可核查。" >&2
  exit 1
fi
