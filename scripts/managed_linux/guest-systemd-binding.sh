set -euo pipefail

guard=boss-binding-guard.service
work=boss-binding-work.service
cleanup() {
    if systemctl is-active --quiet "$work"; then
        systemctl stop "$work"
    fi
    if systemctl is-active --quiet "$guard"; then
        systemctl stop "$guard"
    fi
    if systemctl is-failed --quiet "$work"; then
        systemctl reset-failed "$work"
    fi
    if systemctl is-failed --quiet "$guard"; then
        systemctl reset-failed "$guard"
    fi
}
trap cleanup EXIT
systemd-run --unit=boss-binding-guard --property=Type=exec /usr/bin/sleep 30
systemd-run --unit=boss-binding-work --property=Type=exec --property=KillMode=control-group --property=BindsTo="$guard" --property=After="$guard" /bin/bash -c 'sleep 30 & wait'
test "$(systemctl show "$work" --property=ActiveState --value)" = active
systemctl kill --kill-whom=main --signal=KILL "$guard"
for iteration in $(seq 1 100); do
    state=$(systemctl show "$work" --property=ActiveState --value)
    if [ "$state" = inactive ] || [ "$state" = failed ]; then
        test -z "$(systemctl show "$work" --property=ControlGroup --value)"
        printf 'GUARD_FAILURE_WORK_STOPPED state=%s\n' "$state"
        exit 0
    fi
    sleep 0.1
done
exit 1
