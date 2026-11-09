set -euo pipefail

mkdir /sys/fs/cgroup/boss-tree-probe
for index in 1 2 3 4; do
    bash /mnt/boss-probe/guest-cgroup-probe.sh launch &
done
exec sleep 300
