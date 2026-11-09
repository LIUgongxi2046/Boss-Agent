set -euo pipefail

vm_id=$1
workspace_uuid=$2
install -d -m 0700 /run/boss-vm /var/lib/boss-vm/identities
/bin/bash /usr/local/lib/boss-vm/guest-workspace-mount.sh "$workspace_uuid"
install -d -m 0700 /run/boss-vm/credential-share
install -d -m 0755 /run/boss-dependencies /run/boss-engine
mount -t virtiofs -o ro boss-probe /run/boss-vm/credential-share
mount -t virtiofs -o ro boss-dependencies /run/boss-dependencies
mount -t virtiofs -o ro boss-engine /run/boss-engine
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/run/boss-dependencies
exec /opt/boss/python-3.14.9/bin/python3.14 -m hermes_guest_agent \
    --vm-id "$vm_id" --credentials "/run/boss-vm/$vm_id" --install-shared-credentials \
    --python /opt/boss/python-3.14.9/bin/python3.14 \
    --entry /opt/boss/python-3.14.9/lib/python3.14/site-packages/hermes_engine_entry.py \
    --engine /run/boss-engine --dependencies /run/boss-dependencies --workspace-root /var/lib/boss-vm/workspaces/runs \
    --juicefs /usr/local/lib/boss-vm/juicefs --juicefs-sha256 6d450d3c151b6affede364d9a198d2505111b0612a5fb4d31613444c635174cc \
    --identity-directory /var/lib/boss-vm/identities --supervisor-unit boss-vm-agent.service
