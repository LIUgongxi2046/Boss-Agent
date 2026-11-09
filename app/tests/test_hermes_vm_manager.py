import os
import subprocess

import pytest

from hermes_vm_manager import HermesVMLock, require_diagnostic_stderr, require_guest_policy, require_workspace_ports, require_workspace_port_sets


def test_diagnostic_stderr_requires_private_writable_regular_file(tmp_path):
    path = tmp_path / "diagnostic.log"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        assert require_diagnostic_stderr(descriptor) == descriptor
        os.chmod(path, 0o644)
        with pytest.raises(ValueError):
            require_diagnostic_stderr(descriptor)
        os.chmod(path, 0o600)
        os.link(path, tmp_path / "linked.log")
        with pytest.raises(ValueError):
            require_diagnostic_stderr(descriptor)
    finally:
        os.close(descriptor)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(ValueError):
            require_diagnostic_stderr(descriptor)
    finally:
        os.close(descriptor)


def test_vm_manager_lock_rejects_concurrent_owner(tmp_path):
    directory = tmp_path.resolve()
    first = HermesVMLock(directory)
    try:
        first.require()
        with pytest.raises(BlockingIOError):
            HermesVMLock(directory)
    finally:
        first.close()
    second = HermesVMLock(directory)
    second.close()


def test_vm_manager_lock_rejects_symbolic_link(tmp_path):
    directory = tmp_path.resolve()
    target = directory / "other"
    target.touch(mode=0o600)
    (directory / "manager.lock").symlink_to(target)
    with pytest.raises(OSError):
        HermesVMLock(directory)
    assert os.stat(target).st_size == 0


def test_vm_manager_lock_remains_held_by_real_child_after_parent_descriptor_closes(tmp_path):
    directory = tmp_path.resolve()
    lock = HermesVMLock(directory)
    process = subprocess.Popen(["/bin/sleep", "30"], pass_fds=(lock.descriptor,))
    os.close(lock.descriptor)
    try:
        with pytest.raises(BlockingIOError):
            HermesVMLock(directory)
    finally:
        process.terminate()
        process.wait(timeout=10)
    replacement = HermesVMLock(directory)
    replacement.close()


def test_guest_policy_respects_virtual_machine_limits():
    require_guest_policy({"memory_bytes": 1024 * 1024 * 1024, "processes": 64, "cpu_percent": 100})
    with pytest.raises(ValueError, match="超出环境范围"):
        require_guest_policy({"memory_bytes": 3 * 1024 * 1024 * 1024, "processes": 64, "cpu_percent": 100})


def test_workspace_forward_ports_cannot_reuse_control_or_other_channels():
    assert require_workspace_ports([(1026, 21001), (1027, 21002)], 20001, 20002) == ((1026, 21001), (1027, 21002))
    for value in ([(1024, 21001)], [(1026, 20001)], [(1026, 21001), (1026, 21002)],
                  [(1026, 21001), (1027, 21001)], [(1026, True)]):
        with pytest.raises(ValueError):
            require_workspace_ports(value, 20001, 20002)


def test_workspace_forward_and_reverse_ports_are_distinct():
    assert require_workspace_port_sets([(1026, 21001)], [(1027, 21002)], 20001, 20002) == (((1026, 21001),), ((1027, 21002),))
    for reverse in ([(1026, 21002)], [(1027, 21001)], [(1027, 20002)]):
        with pytest.raises(ValueError):
            require_workspace_port_sets([(1026, 21001)], reverse, 20001, 20002)
