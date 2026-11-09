set -euo pipefail

mount -o nodev,nosuid /dev/vdb /srv/boss-workspace
if ! getent passwd bossrunprobe > /dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin bossrunprobe
fi
mkdir /srv/boss-workspace/run-a /srv/boss-workspace/run-b
chown isolation:isolation /srv/boss-workspace/run-a
chown bossrunprobe:bossrunprobe /srv/boss-workspace/run-b
chmod 700 /srv/boss-workspace/run-a /srv/boss-workspace/run-b
runuser -u isolation -- touch /srv/boss-workspace/run-a/access-check
runuser -u bossrunprobe -- touch /srv/boss-workspace/run-b/access-check
if runuser -u isolation -- cat /srv/boss-workspace/run-b/access-check; then
    echo "CROSS_ACCESS_ALLOWED" >&2
    exit 1
fi
if runuser -u bossrunprobe -- cat /srv/boss-workspace/run-a/access-check; then
    echo "CROSS_ACCESS_ALLOWED" >&2
    exit 1
fi
echo "OWNER_ACCESS_ALLOWED"
echo "CROSS_ACCESS_REJECTED"
