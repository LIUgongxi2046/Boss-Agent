set -euo pipefail

if [ "${1:-}" = child ]; then
    yes > /dev/null &
    yes > /dev/null &
    wait
fi

source=/run/boss-checks/guest-cpu-aggregate.sh
systemd-run --unit=boss-cpu-aggregate --property=Type=exec --property=KillMode=control-group --property=CPUAccounting=yes --property=CPUQuota=100% --property=TasksMax=32 /bin/bash "$source" child
trap 'systemctl stop boss-cpu-aggregate.service' EXIT
sleep 0.5
first=$(systemctl show boss-cpu-aggregate.service --property=CPUUsageNSec --value)
sleep 1
second=$(systemctl show boss-cpu-aggregate.service --property=CPUUsageNSec --value)
test "$first" -gt 0
test "$second" -gt "$first"
printf 'CPU_USAGE_FIRST_NS=%s\nCPU_USAGE_SECOND_NS=%s\n' "$first" "$second"
systemctl stop boss-cpu-aggregate.service
trap - EXIT
