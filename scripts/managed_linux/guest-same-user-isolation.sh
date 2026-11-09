set -euo pipefail

root=/run/boss-same-user-isolation-v3
source=/run/boss-readonly-source/guest-same-user-isolation.sh

if [ "${1:-}" = holder ]; then
    test "$(cat "$root/run-a/input")" = "run-a"
    id -u > "$root/run-a/uid"
    printf 'ready\n' > "$root/run-a/ready"
    sleep 30
    exit 0
fi

if [ "${1:-}" = checker ]; then
    test "$(cat "$root/run-b/input")" = "run-b"
    if cat "$root/run-a/input" > /dev/null 2>&1; then
        printf 'CROSS_WORKSPACE_ALLOWED\n' >&2
        exit 1
    fi
    if cat "/proc/$2/root$root/run-a/input" > /dev/null 2>&1; then
        printf 'CROSS_PROCESS_ROOT_ALLOWED\n' >&2
        exit 1
    fi
    if cat "/proc/$2/environ" > /dev/null 2>&1; then
        printf 'CROSS_PROCESS_ENVIRONMENT_ALLOWED\n' >&2
        exit 1
    fi
    if ls "/proc/$2/fd" > /dev/null 2>&1; then
        printf 'CROSS_PROCESS_DESCRIPTORS_ALLOWED\n' >&2
        exit 1
    fi
    if kill -0 "$2" 2> /dev/null; then
        printf 'CROSS_PROCESS_SIGNAL_ALLOWED\n' >&2
        exit 1
    fi
    printf 'ENGINE_UID=%s\n' "$(id -u)"
    printf 'OWN_WORKSPACE_ALLOWED\nCROSS_WORKSPACE_REJECTED\nCROSS_PROCESS_ROOT_REJECTED\nCROSS_PROCESS_ENVIRONMENT_REJECTED\nCROSS_PROCESS_DESCRIPTORS_REJECTED\nCROSS_PROCESS_SIGNAL_REJECTED\n'
    exit 0
fi

test ! -e "$root"
mkdir -m 0755 "$root"
mkdir -m 0700 "$root/run-a" "$root/run-b"
chown isolation:isolation "$root/run-a"
chown bossrunprobe:bossrunprobe "$root/run-b"
printf 'run-a\n' > "$root/run-a/input"
printf 'run-b\n' > "$root/run-b/input"
chown isolation:isolation "$root/run-a/input"
chown bossrunprobe:bossrunprobe "$root/run-b/input"
chmod 600 "$root/run-a/input" "$root/run-b/input"
systemd-run --unit=boss-distinct-user-a --property=Type=exec --property=KillMode=control-group --property=User=isolation --property=NoNewPrivileges=yes --property=PrivateUsers=yes --property=ProtectProc=invisible --property=ProcSubset=pid --property=ProtectSystem=strict --property="TemporaryFileSystem=$root:ro" --property="BindPaths=$root/run-a" /bin/bash "$source" holder
trap 'systemctl stop boss-distinct-user-a.service' EXIT
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if test -f "$root/run-a/ready"; then break; fi
    sleep 0.25
done
test -f "$root/run-a/ready"
holder_pid=$(systemctl show boss-distinct-user-a.service --property=MainPID --value)
test "$holder_pid" -gt 0
printf 'HOLDER_UID=%s\n' "$(cat "$root/run-a/uid")"
systemctl show boss-distinct-user-a.service --property=User --property=PrivateUsers --property=ProtectProc --property=ProcSubset
systemd-run --wait --pipe --unit=boss-distinct-user-b --property=Type=exec --property=KillMode=control-group --property=User=bossrunprobe --property=NoNewPrivileges=yes --property=PrivateUsers=yes --property=ProtectProc=invisible --property=ProcSubset=pid --property=ProtectSystem=strict --property="TemporaryFileSystem=$root:ro" --property="BindPaths=$root/run-b" /bin/bash "$source" checker "$holder_pid"
systemctl stop boss-distinct-user-a.service
trap - EXIT
