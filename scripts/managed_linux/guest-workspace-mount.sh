set -euo pipefail

uuid="$1"
target=/var/lib/boss-vm/workspaces
if [[ ! "$uuid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo '工作区磁盘 UUID 无效。' >&2
  exit 1
fi
device="$(/usr/sbin/blkid -U "$uuid")"
if [[ ! -b "$device" || "$(/usr/sbin/blockdev --getsize64 "$device")" != 2147483648 || "$(/usr/sbin/blkid -s TYPE -o value "$device")" != ext4 ]]; then
  echo '工作区磁盘类型或容量不可核查。' >&2
  exit 1
fi
if [[ ! -e "$target" && ! -L "$target" ]]; then
  /usr/bin/mkdir -m 0700 "$target"
fi
if [[ -L "$target" || ! -d "$target" ]]; then
  echo '工作区挂载目录不可核查。' >&2
  exit 1
fi
mounted_here=0
if ! /usr/bin/mountpoint -q "$target"; then
  if [[ -n "$(/usr/bin/find "$target" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo '工作区挂载目录包含已有内容。' >&2
    exit 1
  fi
  /usr/bin/mount -t ext4 -o rw,nosuid,nodev "$device" "$target"
  mounted_here=1
fi
read -r mounted_uuid filesystem options < <(/usr/bin/findmnt -n -M "$target" -o UUID,FSTYPE,OPTIONS)
if [[ "$mounted_uuid" != "$uuid" || "$filesystem" != ext4 || ",$options," != *,rw,* || ",$options," != *,nosuid,* || ",$options," != *,nodev,* ]]; then
  if [[ "$mounted_here" == 1 ]]; then
    /usr/bin/umount "$target"
  fi
  echo '工作区挂载身份或权限不可核查。' >&2
  exit 1
fi
runs="$target/runs"
if [[ ! -e "$runs" && ! -L "$runs" ]]; then
  /usr/bin/mkdir -m 0700 "$runs"
fi
if [[ -L "$runs" || ! -d "$runs" || "$(/usr/bin/stat -c '%u:%g:%a' "$runs")" != 0:0:700 ]]; then
  if [[ "$mounted_here" == 1 ]]; then
    /usr/bin/umount "$target"
  fi
  echo '运行工作区根目录不可核查。' >&2
  exit 1
fi
printf 'WORKSPACE_MOUNT_VERIFIED %s %s\n' "$uuid" "$runs"
