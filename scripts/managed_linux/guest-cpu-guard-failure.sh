set -euo pipefail

supervisor=boss-test-supervisor.service
signal=${1:-KILL}
if [ "$signal" != KILL ] && [ "$signal" != STOP ]; then
    exit 1
fi
evidence=/run/boss-cpu-guard-evidence-"$signal"-$(cat /proc/sys/kernel/random/uuid)
unit=
guard=
cleanup() {
    if [ -n "$unit" ] && systemctl is-active --quiet "$unit"; then
        systemctl stop "$unit"
    fi
    if [ -n "$guard" ] && systemctl is-failed --quiet "$guard"; then
        systemctl reset-failed "$guard"
    fi
    if systemctl is-active --quiet "$supervisor"; then
        systemctl stop "$supervisor"
    fi
    if systemctl is-failed --quiet "$supervisor"; then
        systemctl reset-failed "$supervisor"
    fi
}
trap cleanup EXIT
systemd-run --unit=boss-test-supervisor --property=Type=exec --setenv=PYTHONDONTWRITEBYTECODE=1 \
    --setenv=PYTHONPATH=/run/boss-deps/linux-target --setenv=BOSS_CHECK_EVIDENCE="$evidence" \
    /opt/boss/python-3.14.9/bin/python3.14 /run/boss-checks/guest-supervisor-failure.py
for iteration in $(seq 1 150); do
    if [ -f "$evidence/ready" ]; then
        break
    fi
    sleep 0.1
done
test -f "$evidence/ready"
unit=$(cat "$evidence/unit")
guard="boss-cpu-${unit#boss-}"
parent=$(cat "$evidence/parent-pid")
child=$(cat "$evidence/child-pid")
kill -0 "$parent" "$child"
systemctl kill --kill-whom=main --signal="$signal" "$guard"
for iteration in $(seq 1 150); do
    if ! kill -0 "$parent" 2>/dev/null && ! kill -0 "$child" 2>/dev/null; then
        test -z "$(systemctl show "$unit" --property=ControlGroup --value)"
        systemctl is-active --quiet "$supervisor"
        printf 'CPU_GUARD_%s_ALL_PROCESSES_EXITED\n' "$signal"
        exit 0
    fi
    sleep 0.1
done
exit 1
