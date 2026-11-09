set -euo pipefail

supervisor=boss-test-supervisor.service
cleanup() {
    if systemctl is-active --quiet "$supervisor"; then
        systemctl stop "$supervisor"
    fi
}
trap cleanup EXIT
systemd-run --unit=boss-test-supervisor --property=Type=exec /usr/bin/sleep 30
if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/run/boss-deps/linux-target \
    /opt/boss/python-3.14.9/bin/python3.14 /run/boss-checks/guest-supervisor-failure.py \
    > /run/boss-supervisor-rejection.log 2>&1; then
    exit 1
fi
grep -q '客体监督服务身份不匹配' /run/boss-supervisor-rejection.log
printf 'SUPERVISOR_IDENTITY_MISMATCH_REJECTED\n'
