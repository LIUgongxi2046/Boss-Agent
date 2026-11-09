set -euo pipefail

state=/var/lib/boss-vm/quota-check-001
mountpoint=/run/boss-quota-check-001
mkdir "$state" "$mountpoint"
truncate -s 64M "$state/workspace.ext4"
mkfs.ext4 -F -q -O quota,project -E quotatype=prjquota "$state/workspace.ext4"
device=$(losetup --find --show "$state/workspace.ext4")
mounted=no
cleanup() {
    if [ "$mounted" = yes ]; then
        umount "$mountpoint"
    fi
    losetup --detach "$device"
}
trap cleanup EXIT
mount -o prjquota "$device" "$mountpoint"
mounted=yes
mkdir "$mountpoint/count" "$mountpoint/bytes"
chown isolation:isolation "$mountpoint/count" "$mountpoint/bytes"
chattr -p 800001 +P "$mountpoint/count"
chattr -p 800002 +P "$mountpoint/bytes"
setquota -P 800001 0 0 3 3 "$mountpoint"
setquota -P 800002 16 16 0 0 "$mountpoint"
runuser -u isolation -- touch "$mountpoint/count/one" "$mountpoint/count/two"
if runuser -u isolation -- touch "$mountpoint/count/three"; then
    exit 1
fi
if runuser -u isolation -- dd if=/dev/zero of="$mountpoint/bytes/filled" bs=1024 count=32 status=none; then
    exit 1
fi
runuser -u isolation -- truncate -s 1048576 "$mountpoint/bytes/sparse"
test "$(stat -c %s "$mountpoint/bytes/sparse")" = 1048576
repquota -P "$mountpoint"
printf 'PROJECT_INODE_AND_ALLOCATED_BLOCK_LIMITS_ENFORCED\n'
printf 'SPARSE_LOGICAL_BYTES_EXCEED_ALLOCATED_BLOCK_LIMIT\n'
