import sys
from pathlib import Path

import pytest

from hermes_guest_systemd import HermesGuestSystemd
from hermes_guest_control import HermesGuestControl


def test_guest_systemd_refuses_non_linux_host():
    if sys.platform == "linux":
        pytest.skip("此检查针对非 Linux 宿主")
    current = Path(__file__).resolve()
    with pytest.raises(ValueError, match="Linux 系统管理权限"):
        HermesGuestSystemd(python=Path(sys.executable), entry=current, engine=current.parent, dependencies=current.parent,
                           workspace_root=current.parent, identities=None, supervisor_unit="boss-test-control.service")


def test_guest_control_requires_systemd_manager():
    with pytest.raises(ValueError, match="需要 systemd 管理器"):
        HermesGuestControl(None, None, None, "")
