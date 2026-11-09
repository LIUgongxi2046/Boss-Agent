import os
import hashlib
import plistlib
import pty
import select
import subprocess
from pathlib import Path

import pytest

from hermes_workspace_image import ExperimentalWorkspaceImage
from hermes_bridge import EngineProcessConfig, EngineRunConfig
from hermes_process_anchor import AnchorProcessGroup
from hermes_runtime_transport import experimental_sandbox_command


@pytest.mark.parametrize("condition", ["normal", "operation_failure", "mount_failure"])
def test_experimental_workspace_image_lifecycle(condition):
    workspace = ExperimentalWorkspaceImage(32)
    try:
        if condition == "mount_failure":
            workspace.mount.rmdir()
            workspace.mount.write_text("独立技术资料", encoding="utf-8")
            with pytest.raises(subprocess.CalledProcessError):
                with workspace:
                    raise AssertionError("无效挂载点不能使用")
        elif condition == "operation_failure":
            with pytest.raises(FileNotFoundError):
                with workspace as mount:
                    (mount / "missing.txt").read_bytes()
        else:
            with workspace as mount:
                assert os.path.ismount(mount)
                assert os.stat(workspace._attached_device()).st_rdev == mount.stat().st_dev
                (mount / "test.txt").write_text("独立技术资料", encoding="utf-8")
                root = Path(__file__).resolve().parents[2]
                profile = (root / "app/tests/hermes_isolation_adapter_candidate.sb").read_text(encoding="utf-8")
                base = root / ".work/upgrade2/u2-01/python/cpython-3.14.9-macos-x86_64-none"
                command = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(base), "-D", "RUNTIME=" + str(base),
                           "-D", "ENGINE=" + str(mount), "-D", "ADAPTER=" + str(mount), "-D", "WORK=" + str(mount),
                           "-D", "ENDPOINT=localhost:1", "-p", profile, str(base / "bin/python3.14"), "-c",
                           "import sys; open(sys.argv[1],'wb').write(b'x'*(40*1024*1024))", str(mount / "bounded.bin")]
                result = subprocess.run(command, cwd=mount, env=workspace.environment, capture_output=True, timeout=30)
                assert result.returncode != 0 and b"No space left on device" in result.stderr
        assert not os.path.ismount(workspace.mount)
        assert workspace._attached_device() is None
        assert workspace.image.is_file()
    finally:
        if workspace._attached_device() is None and not os.path.ismount(workspace.mount):
            if workspace.image.exists():
                workspace.image.unlink()
            if workspace.mount.is_file():
                workspace.mount.unlink()
            elif workspace.mount.is_dir():
                workspace.mount.rmdir()
            workspace.directory.rmdir()


def test_experimental_workspace_image_rejects_invalid_capacity():
    for value in (0, 15, 257, True, 32.0):
        with pytest.raises(ValueError, match="容量无效"):
            ExperimentalWorkspaceImage(value)
    for run_id in ("mount", "../escape", "", True):
        with pytest.raises(ValueError):
            ExperimentalWorkspaceImage(32, run_id=run_id)


def test_experimental_workspace_images_keep_separate_mounts():
    workspaces = [ExperimentalWorkspaceImage(32), ExperimentalWorkspaceImage(32)]
    first, second = workspaces
    try:
        assert first.directory != second.directory
        with first as first_mount:
            with second as second_mount:
                assert first_mount != second_mount
                assert first._attached_device() != second._attached_device()
            assert os.path.ismount(first_mount)
            assert second._attached_device() is None
        assert first._attached_device() is None
    finally:
        for workspace in workspaces:
            if workspace._attached_device() is None and not os.path.ismount(workspace.mount):
                if workspace.image.exists():
                    workspace.image.unlink()
                workspace.mount.rmdir()
                workspace.directory.rmdir()


def test_guardian_uses_experimental_sandbox_with_image_workspace(tmp_path):
    from test_agent_run_result import setup_result
    _, _, _, sink = setup_result(tmp_path)
    root = Path(__file__).resolve().parents[2]
    audit = root / ".work/upgrade2/u2-03/dependency-audit-001"
    executable = audit / "environment/bin/python"
    adapter = root / ".work/upgrade2/u2-01/hermes-adapter-env-001/lib/python3.14/site-packages"
    profile_path = root / "app/tests/hermes_isolation_adapter_candidate.sb"
    profile = profile_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(profile.encode()).hexdigest()
    workspace = ExperimentalWorkspaceImage(32, run_id=sink.config.run_id)
    try:
        with workspace as mount:
            workspace.require_capacity(sink.config.run_id, mount, 32 * 1024 * 1024)
            with pytest.raises(ValueError, match="超过磁盘容量上限"):
                workspace.require_capacity(sink.config.run_id, mount, 16 * 1024 * 1024)
            run = EngineRunConfig(sink.config.run_id, sink.config.lease_epoch, sink.config.engine_commit, "http://127.0.0.1:1", 1)
            config = EngineProcessConfig(run, audit / "source", root / ".work/upgrade2/u2-01/hermes.tar.gz",
                                         executable.resolve().parent, executable, workspace.directory, mount, profile_path,
                                         1, 1, 30, 1, 128, 1, 8388608, 128, 30)
            environment = {"PATH": "/usr/bin:/bin", "HOME": str(mount), "TMPDIR": str(mount),
                           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
            cases = [(mount / "allowed.bin", 1, 0), (Path("/dev/null"), 1, 0), (workspace.directory / "outside.bin", 1, 1),
                     (mount / "large.bin", 40 * 1024 * 1024, 1)]
            for path, size, expected in cases:
                if size == 1:
                    command = [str(executable), "-c", "import sys; open(sys.argv[1],'wb').write(b'x')", str(path)]
                else:
                    command = [str(executable), "-c", "import sys; f=open(sys.argv[1],'wb',buffering=0); sum(f.write(b'x'*1048576) for _ in range(40))", str(path)]
                command = experimental_sandbox_command(command, config, adapter, profile, digest)
                anchor = AnchorProcessGroup.start(command, cwd=mount, env=environment, deferred=True, guarded=True)
                try:
                    anchor.release_engine()
                    assert anchor.read_engine_exit(timeout=30) == expected
                finally:
                    if anchor.process.poll() is None:
                        anchor.reclaim()
                    anchor.close_control()
            assert (mount / "allowed.bin").read_bytes() == b"x"
            assert not (workspace.directory / "outside.bin").exists()
            assert 0 < (mount / "large.bin").stat().st_size < 32 * 1024 * 1024
            capacity = os.statvfs(mount)
            assert capacity.f_bavail * capacity.f_frsize < 1024 * 1024
            command = [str(executable), "-c", "import os; assert len(os.urandom(16))==16; assert len(open('/dev/urandom','rb').read(1))==1"]
            command = experimental_sandbox_command(command, config, adapter, profile, digest)
            anchor = AnchorProcessGroup.start(command, cwd=mount, env=environment, deferred=True, guarded=True)
            try:
                anchor.release_engine()
                assert anchor.read_engine_exit(timeout=30) == 0
            finally:
                if anchor.process.poll() is None:
                    anchor.reclaim()
                anchor.close_control()
            master, slave = pty.openpty()
            try:
                command = [str(executable), "-c", "import sys; open(sys.argv[1],'wb',buffering=0).write(b'technical')", os.ttyname(slave)]
                control = subprocess.run(command, cwd=mount, env=environment, capture_output=True, timeout=30)
                assert control.returncode == 0
                assert select.select([master], [], [], 5)[0] and os.read(master, 64) == b"technical"
                command = experimental_sandbox_command(command, config, adapter, profile, digest)
                anchor = AnchorProcessGroup.start(command, cwd=mount, env=environment, deferred=True, guarded=True)
                try:
                    anchor.release_engine()
                    assert anchor.read_engine_exit(timeout=30) != 0
                finally:
                    if anchor.process.poll() is None:
                        anchor.reclaim()
                    anchor.close_control()
                assert not select.select([master], [], [], 0)[0]
            finally:
                os.close(master)
                os.close(slave)
        assert workspace._attached_device() is None and not os.path.ismount(workspace.mount)
    finally:
        if workspace._attached_device() is None and not os.path.ismount(workspace.mount):
            if workspace.image.exists():
                workspace.image.unlink()
            workspace.mount.rmdir()
            workspace.directory.rmdir()


def test_bounded_image_limits_independent_process_writes(tmp_path):
    root = Path(__file__).resolve().parents[2]
    image = tmp_path / "independent-workspace.dmg"
    mount = tmp_path / "independent-mount"
    mount.mkdir()
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path)}
    created = subprocess.run(["/usr/bin/hdiutil", "create", "-size", "32m", "-fs", "HFS+", "-type", "UDIF",
                              "-volname", "BossAgentCapacityCheck", "-nospotlight", str(image)],
                             env=environment, capture_output=True, timeout=60)
    assert created.returncode == 0, created.stderr.decode(errors="replace")
    processes = []
    try:
        result = subprocess.run(["/usr/bin/hdiutil", "attach", str(image), "-mountpoint", str(mount),
                                 "-noautoopen", "-plist"], env=environment, capture_output=True, check=True, timeout=60)
        entities = plistlib.loads(result.stdout)["system-entities"]
        assert [item["mount-point"] for item in entities if "mount-point" in item] == [str(mount)]
        assert os.path.ismount(mount)
        profile = (root / "app/tests/hermes_isolation_adapter_candidate.sb").read_text(encoding="utf-8")
        base = root / ".work/upgrade2/u2-01/python/cpython-3.14.9-macos-x86_64-none"
        executable = base / "bin/python3.14"
        for index in range(2):
            command = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(base), "-D", "RUNTIME=" + str(base),
                       "-D", "ENGINE=" + str(mount), "-D", "ADAPTER=" + str(mount), "-D", "WORK=" + str(mount),
                       "-D", "ENDPOINT=localhost:1", "-p", profile, str(executable), "-c",
                       "import sys; open(sys.argv[1],'wb').write(b'x'*(20*1024*1024))", str(mount / (str(index) + ".bin"))]
            processes.append(subprocess.Popen(command, cwd=mount, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        results = [process.communicate(timeout=30) for process in processes]
        assert any(process.returncode != 0 for process in processes)
        assert any(b"No space left on device" in stderr for _, stderr in results)
        assert sum(path.stat().st_size for path in mount.glob("*.bin")) <= 32 * 1024 * 1024
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        if os.path.ismount(mount):
            subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], env=environment,
                           capture_output=True, check=True, timeout=60)
            assert not os.path.ismount(mount)
