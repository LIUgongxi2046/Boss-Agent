import socket
import select
import hashlib
import fcntl
import os
import subprocess
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from hermes_process_anchor import AnchorProcessGroup
from hermes_bridge import EngineProcessConfig, EngineRunConfig
from hermes_runtime_transport import experimental_sandbox_command


PROFILE = Path(__file__).with_name("hermes_isolation_probe.sb").resolve()
PROBE = Path(__file__).with_name("hermes_isolation_probe.py").resolve()
CANDIDATE = Path(__file__).with_name("hermes_isolation_candidate.sb").resolve()
SYSCTL_CANDIDATE = Path(__file__).with_name("hermes_isolation_sysctl_candidate.sb").resolve()
ADAPTER_CANDIDATE = Path(__file__).with_name("hermes_isolation_adapter_candidate.sb").resolve()


def test_experimental_sandbox_command_runs_guarded_adapter_import(tmp_path):
    root = Path(__file__).resolve().parents[2]
    audit = root / ".work/upgrade2/u2-03/dependency-audit-001"
    executable = audit / "environment/bin/python"
    adapter = root / ".work/upgrade2/u2-01/hermes-adapter-env-001/lib/python3.14/site-packages"
    work = tmp_path / "technical-run"
    work.mkdir()
    run = EngineRunConfig("technical-run", 1, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1", 1)
    config = EngineProcessConfig(run, audit / "source", root / ".work/upgrade2/u2-01/hermes.tar.gz",
                                 executable.resolve().parent, executable, tmp_path, work, ADAPTER_CANDIDATE,
                                 1, 1, 30, 1, 128, 1, 8388608, 128, 30)
    profile = ADAPTER_CANDIDATE.read_text(encoding="utf-8")
    digest = hashlib.sha256(profile.encode("utf-8")).hexdigest()
    command = [str(executable), "-c", "import sys; sys.path.append(sys.argv[1]); import run_agent,model_tools,tools.registry,hermes_engine_entry", str(adapter)]
    with pytest.raises(ValueError, match="摘要不匹配"):
        experimental_sandbox_command(command, config, adapter, profile, "0" * 64)
    loose = "(version 1)\n(allow default)\n"
    with pytest.raises(ValueError, match="受控模板"):
        experimental_sandbox_command(command, config, adapter, loose, hashlib.sha256(loose.encode()).hexdigest())
    with pytest.raises(ValueError, match="受控范围"):
        experimental_sandbox_command(command, replace(config, workspace=root), adapter, profile, digest)
    linked = tmp_path / "linked-workspace"
    linked.symlink_to(work, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        experimental_sandbox_command(command, replace(config, workspace=linked), adapter, profile, digest)
    with pytest.raises(ValueError, match="受控范围"):
        experimental_sandbox_command(command, config, root / "validation", profile, digest)
    with pytest.raises(ValueError, match="受控范围"):
        experimental_sandbox_command(command, replace(config, source_archive=root / "AGENTS.md"), adapter, profile, digest)
    wrong_run = tmp_path / "another-run"
    wrong_run.mkdir()
    with pytest.raises(ValueError, match="工作目录与运行不匹配"):
        experimental_sandbox_command(command, replace(config, workspace=wrong_run), adapter, profile, digest)
    sandboxed = experimental_sandbox_command(command, config, adapter, profile, digest)
    anchor = AnchorProcessGroup.start(sandboxed, cwd=work, env={"PATH": "/usr/bin:/bin", "HOME": str(work),
                                      "TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
                                      deferred=True, guarded=True)
    try:
        anchor.release_engine()
        assert anchor.read_engine_exit(timeout=30) == 0
    finally:
        if anchor.process.poll() is None:
            anchor.reclaim()
        anchor.close_control()


def test_fixed_hermes_and_installed_adapter_in_candidate(tmp_path):
    root = Path(__file__).resolve().parents[2]
    audit = root / ".work/upgrade2/u2-03/dependency-audit-001"
    executable = audit / "environment/bin/python"
    adapter = root / ".work/upgrade2/u2-01/hermes-adapter-env-001/lib/python3.14/site-packages"
    wheel = root / ".work/upgrade2/u2-01/hermes-adapter-wheel-002/boss_agent_hermes_adapter-0.1.0-py3-none-any.whl"
    with wheel.open("rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == "6d75a9c17199482558df7b2ff14b70688271cf83050ba0169f352fc9d28e0ac3"
    entries = (root / "hermes-engine-resources.txt").read_text(encoding="utf-8").splitlines()
    assert len(entries) == len(set(entries)) == 12
    with zipfile.ZipFile(wheel) as archive:
        for entry in entries:
            original = root / entry
            installed = adapter / original.name
            assert not original.is_symlink() and not installed.is_symlink()
            assert original.read_bytes() == archive.read(original.name) == installed.read_bytes()
    work = tmp_path / "workspace"
    work.mkdir()
    profile = ADAPTER_CANDIDATE.read_bytes()
    assert hashlib.sha256(profile).hexdigest() == "356937ae87b8dc6c5fcaaa6ea8b4e711c26585030e872b2a9a38bd41304eb2e8"
    command = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(executable.resolve().parent.parent),
               "-D", "RUNTIME=" + str(audit / "environment"), "-D", "ENGINE=" + str(audit / "source"),
               "-D", "ADAPTER=" + str(adapter), "-D", "WORK=" + str(work), "-D", "ENDPOINT=localhost:1",
               "-p", profile.decode("utf-8"), str(executable), "-c",
               "import sys; from pathlib import Path; sys.path.append(sys.argv[1]); import run_agent,model_tools,tools.registry,hermes_engine_entry,hermes_transport_client,hermes_tool_registration,hermes_domain_schema; assert Path(hermes_engine_entry.__file__).resolve().parent == Path(sys.argv[1]).resolve(); print('IMPORT_OK')", str(adapter)]
    result = subprocess.run(command, cwd=work, env={"PATH": "/usr/bin:/bin", "HOME": str(work),
                            "TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "IMPORT_OK"
    outside = tmp_path / "private.txt"
    outside.write_text("独立测试资料", encoding="utf-8")
    denied_command = command[:-4] + [str(executable), "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).read_bytes()", str(outside)]
    denied = subprocess.run(denied_command, cwd=work, env={"PATH": "/usr/bin:/bin", "HOME": str(work),
                            "TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
    assert denied.returncode != 0 and "PermissionError" in denied.stderr


def test_limited_sysctl_candidate_imports_fixed_hermes(tmp_path):
    root = Path(__file__).resolve().parents[2]
    audit = root / ".work/upgrade2/u2-03/dependency-audit-001"
    executable = audit / "environment/bin/python"
    work = tmp_path / "workspace"
    work.mkdir()
    profile = SYSCTL_CANDIDATE.read_text(encoding="utf-8")
    command = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(executable.resolve().parent.parent),
               "-D", "RUNTIME=" + str(audit / "environment"), "-D", "ENGINE=" + str(audit / "source"),
               "-D", "VALIDATION=" + str(PROBE.parent), "-D", "WORK=" + str(work),
               "-D", "ENDPOINT=localhost:1", "-p", profile, str(executable), "-c",
               "import run_agent,model_tools,tools.registry; print('IMPORT_OK')"]
    result = subprocess.run(command, cwd=work, env={"PATH": "/usr/bin:/bin", "HOME": str(work),
                            "TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "IMPORT_OK"


def test_guarded_process_does_not_inherit_unrelated_unix_connection(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    profile = CANDIDATE.read_bytes()
    assert hashlib.sha256(profile).hexdigest() == "ad4b84b8438832994ef7807fa620eaec5889e7a6ef485690d9411451db4a8942"
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    descriptor = fcntl.fcntl(child.fileno(), fcntl.F_DUPFD, 200)
    try:
        command = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(Path(sys.executable).resolve().parent.parent),
                   "-D", "RUNTIME=" + str(Path(sys.executable).parent.parent), "-D", "ENGINE=" + str(PROBE.parent),
                   "-D", "VALIDATION=" + str(PROBE.parent), "-D", "WORK=" + str(work), "-D", "ENDPOINT=localhost:1",
                   "-p", profile.decode("utf-8"), sys.executable, str(PROBE), "inherited-unix", str(descriptor)]
        anchor = AnchorProcessGroup.start(command, cwd=work, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                                          deferred=True, guarded=True)
        try:
            anchor.release_engine()
            assert anchor.read_engine_exit(timeout=10) != 0
            assert select.select([parent], [], [], 0)[0] == []
        finally:
            if anchor.process.poll() is None:
                anchor.reclaim()
            anchor.close_control()
    finally:
        os.close(descriptor)
        parent.close()
        child.close()


def test_default_deny_candidate_inherited_unix_connection(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    profile = CANDIDATE.read_bytes()
    assert hashlib.sha256(profile).hexdigest() == "ad4b84b8438832994ef7807fa620eaec5889e7a6ef485690d9411451db4a8942"
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        command = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(Path(sys.executable).resolve().parent.parent),
                   "-D", "RUNTIME=" + str(Path(sys.executable).parent.parent), "-D", "ENGINE=" + str(PROBE.parent),
                   "-D", "VALIDATION=" + str(PROBE.parent), "-D", "WORK=" + str(work), "-D", "ENDPOINT=localhost:1",
                   "-p", profile.decode("utf-8"), sys.executable, str(PROBE), "inherited-unix", str(child.fileno())]
        result = subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, capture_output=True,
                                pass_fds=(child.fileno(),), timeout=10, check=False)
        assert result.returncode == 0
        parent.settimeout(3)
        assert parent.recv(5) == b"probe"
    finally:
        parent.close()
        child.close()


def test_default_deny_candidate_local_proxy_paths(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    previous_cwd = Path.cwd()
    allowed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    denied_ipv4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    denied_ipv6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    denied_unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        allowed.bind(("127.0.0.1", 0))
        allowed.listen()
        denied_ipv4.bind(("127.0.0.1", 0))
        denied_ipv4.listen()
        denied_ipv6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        denied_ipv6.bind(("::1", 0))
        denied_ipv6.listen()
        os.chdir(work)
        unix_path = "local.sock"
        denied_unix.bind(unix_path)
        denied_unix.listen()
        profile = CANDIDATE.read_bytes()
        assert hashlib.sha256(profile).hexdigest() == "ad4b84b8438832994ef7807fa620eaec5889e7a6ef485690d9411451db4a8942"
        prefix = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(Path(sys.executable).resolve().parent.parent),
                  "-D", "RUNTIME=" + str(Path(sys.executable).parent.parent), "-D", "ENGINE=" + str(PROBE.parent),
                  "-D", "VALIDATION=" + str(PROBE.parent), "-D", "WORK=" + str(work),
                  "-D", "ENDPOINT=localhost:" + str(allowed.getsockname()[1]), "-p", profile.decode("utf-8"),
                  sys.executable, str(PROBE)]
        cases = (("connect", denied_ipv4.getsockname()[1], denied_ipv4),
                 ("connect-mapped", denied_ipv4.getsockname()[1], denied_ipv4),
                 ("connect-ipv6", denied_ipv6.getsockname()[1], denied_ipv6),
                 ("connect-unix", str(unix_path), denied_unix))
        for action, target, listener in cases:
            command = [sys.executable, str(PROBE), action, str(target)]
            control = subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
            assert control.returncode == 0
            connection, _ = listener.accept()
            connection.close()
            restricted = subprocess.run(prefix + [action, str(target)], cwd=work, stdin=subprocess.DEVNULL,
                                        capture_output=True, timeout=10, check=False)
            assert restricted.returncode != 0
            assert select.select([listener], [], [], 0)[0] == []
    finally:
        os.chdir(previous_cwd)
        allowed.close()
        denied_ipv4.close()
        denied_ipv6.close()
        denied_unix.close()


def test_verified_profile_text_argument_with_guarded_process(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    profile = CANDIDATE.read_bytes()
    assert hashlib.sha256(profile).hexdigest() == "ad4b84b8438832994ef7807fa620eaec5889e7a6ef485690d9411451db4a8942"
    profile_text = profile.decode("utf-8")
    allowed = socket.socket()
    denied = socket.socket()
    try:
        allowed.bind(("127.0.0.1", 0))
        allowed.listen()
        denied.bind(("127.0.0.1", 0))
        denied.listen()
        allowed_port = allowed.getsockname()[1]
        denied_port = denied.getsockname()[1]
        prefix = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(Path(sys.executable).resolve().parent.parent),
                  "-D", "RUNTIME=" + str(Path(sys.executable).parent.parent), "-D", "ENGINE=" + str(PROBE.parent),
                  "-D", "VALIDATION=" + str(PROBE.parent), "-D", "WORK=" + str(work),
                  "-D", "ENDPOINT=localhost:" + str(allowed_port), "-p", profile_text,
                  sys.executable, str(PROBE), "connect"]
        for port, accepted in ((allowed_port, True), (denied_port, False)):
            anchor = AnchorProcessGroup.start(prefix + [str(port)], cwd=work,
                                              env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                                              deferred=True, guarded=True)
            try:
                anchor.release_engine()
                assert (anchor.read_engine_exit(timeout=10) == 0) is accepted
            finally:
                if anchor.process.poll() is None:
                    anchor.reclaim()
                anchor.close_control()
        assert select.select([allowed], [], [], 0)[0] == [allowed]
        assert select.select([denied], [], [], 0)[0] == []
    finally:
        allowed.close()
        denied.close()


def test_default_deny_candidate_imports_fixed_hermes(tmp_path):
    root = Path(__file__).resolve().parents[2]
    audit = root / ".work/upgrade2/u2-03/dependency-audit-001"
    executable = audit / "environment/bin/python"
    work = tmp_path / "workspace"
    work.mkdir()
    profile = CANDIDATE.read_bytes()
    assert hashlib.sha256(profile).hexdigest() == "ad4b84b8438832994ef7807fa620eaec5889e7a6ef485690d9411451db4a8942"
    command = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(executable.resolve().parent.parent),
               "-D", "RUNTIME=" + str(audit / "environment"), "-D", "ENGINE=" + str(audit / "source"),
               "-D", "VALIDATION=" + str(PROBE.parent), "-D", "WORK=" + str(work),
               "-D", "ENDPOINT=localhost:1", "-p", profile.decode("utf-8"), str(executable), "-c",
               "import run_agent,model_tools,tools.registry; print('IMPORT_OK')"]
    result = subprocess.run(command, cwd=work, env={"PATH": "/usr/bin:/bin", "HOME": str(work),
                            "TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "IMPORT_OK"


def test_candidate_digest_and_open_profile_descriptor_rejected(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    path = Path(__file__).with_name("hermes_isolation_candidate.sb")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(os.dup(descriptor), "rb") as profile:
            assert hashlib.file_digest(profile, "sha256").hexdigest() == "ad4b84b8438832994ef7807fa620eaec5889e7a6ef485690d9411451db4a8942"
        os.lseek(descriptor, 0, os.SEEK_SET)
        command = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(Path(sys.executable).resolve().parent.parent), "-D", "RUNTIME=" + str(Path(sys.executable).parent.parent),
                   "-D", "ENGINE=" + str(PROBE.parent), "-D", "VALIDATION=" + str(PROBE.parent),
                   "-D", "WORK=" + str(work), "-D", "ENDPOINT=localhost:1",
                   "-f", "/dev/fd/" + str(descriptor), sys.executable, str(PROBE), "write", str(work / "output")]
        result = subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, capture_output=True,
                                pass_fds=(descriptor,), timeout=10, check=False)
        assert result.returncode == 65
        assert b"No such file or directory" in result.stderr
        assert not (work / "output").exists()
    finally:
        os.close(descriptor)


def test_default_deny_candidate_with_guarded_process(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    allowed = socket.socket()
    denied = socket.socket()
    try:
        allowed.bind(("127.0.0.1", 0))
        allowed.listen()
        denied.bind(("127.0.0.1", 0))
        denied.listen()
        allowed_port = allowed.getsockname()[1]
        denied_port = denied.getsockname()[1]
        prefix = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(Path(sys.executable).resolve().parent.parent), "-D", "RUNTIME=" + str(Path(sys.executable).parent.parent),
                  "-D", "ENGINE=" + str(PROBE.parent), "-D", "VALIDATION=" + str(PROBE.parent),
                  "-D", "WORK=" + str(work), "-D", "ENDPOINT=localhost:" + str(allowed_port),
                  "-f", str(CANDIDATE), sys.executable, str(PROBE), "connect"]
        for port, accepted in ((allowed_port, True), (denied_port, False)):
            anchor = AnchorProcessGroup.start(prefix + [str(port)], cwd=work,
                                              env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                                              deferred=True, guarded=True)
            try:
                anchor.release_engine()
                assert (anchor.read_engine_exit(timeout=10) == 0) is accepted
            finally:
                if anchor.process.poll() is None:
                    anchor.reclaim()
                anchor.close_control()
        assert select.select([allowed], [], [], 0)[0] == [allowed]
        assert select.select([denied], [], [], 0)[0] == []
    finally:
        allowed.close()
        denied.close()


def test_default_deny_candidate_runs_local_probe(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("模拟隔离资料", encoding="utf-8")
    (work / "alias").symlink_to(outside)
    allowed = socket.socket()
    denied = socket.socket()
    try:
        allowed.bind(("127.0.0.1", 0))
        allowed.listen()
        denied.bind(("127.0.0.1", 0))
        denied.listen()
        allowed_port = allowed.getsockname()[1]
        denied_port = denied.getsockname()[1]
        prefix = ["/usr/bin/sandbox-exec", "-D", "PYTHON_BASE=" + str(Path(sys.executable).resolve().parent.parent), "-D", "RUNTIME=" + str(Path(sys.executable).parent.parent),
                  "-D", "ENGINE=" + str(PROBE.parent), "-D", "VALIDATION=" + str(PROBE.parent),
                  "-D", "WORK=" + str(work), "-D", "ENDPOINT=localhost:" + str(allowed_port),
                  "-f", str(CANDIDATE), sys.executable, str(PROBE)]

        def check(action, target):
            return subprocess.run(prefix + [action, str(target)], cwd=work, stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=10, check=False)

        assert check("write", work / "inside.txt").returncode == 0
        assert check("read", work / "inside.txt").returncode == 0
        assert check("read", outside).returncode != 0
        assert check("read", work / "alias").returncode != 0
        assert check("write", tmp_path / "outside-new.txt").returncode != 0
        assert check("connect", allowed_port).returncode == 0
        assert check("connect", denied_port).returncode != 0
        process_probe = Path(__file__).with_name("hermes_process_isolation_probe.py").resolve()
        for action in ("fork", "exec"):
            result = subprocess.run(prefix[:-1] + [str(process_probe), action, "unused"], cwd=work,
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
            assert result.returncode != 0
    finally:
        allowed.close()
        denied.close()


def test_workspace_and_local_endpoint_restrictions(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    protected = tmp_path / "outside.txt"
    protected.write_text("模拟隔离资料", encoding="utf-8")
    (work / "alias").symlink_to(protected)
    allowed_listener = socket.socket()
    denied_listener = socket.socket()
    try:
        allowed_listener.bind(("127.0.0.1", 0))
        allowed_listener.listen()
        denied_listener.bind(("127.0.0.1", 0))
        denied_listener.listen()
        allowed_port = allowed_listener.getsockname()[1]
        denied_port = denied_listener.getsockname()[1]
        prefix = ["/usr/bin/sandbox-exec", "-D", "PROTECTED=" + str(tmp_path), "-D", "WORK=" + str(work),
                  "-D", "ENDPOINT=localhost:" + str(allowed_port), "-f", str(PROFILE), sys.executable, str(PROBE)]

        def check(action, target):
            return subprocess.run(prefix + [action, str(target)], cwd=work, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)

        assert check("write", work / "inside.txt").returncode == 0
        assert check("read", work / "inside.txt").returncode == 0
        assert check("read", protected).returncode != 0
        assert check("read", work / "alias").returncode != 0
        assert check("write", tmp_path / "outside-new.txt").returncode != 0
        assert check("write", protected).returncode != 0
        assert check("connect", allowed_port).returncode == 0
        assert check("connect", denied_port).returncode != 0
    finally:
        allowed_listener.close()
        denied_listener.close()


def test_system_configuration_remains_available(tmp_path):
    command = ["/usr/sbin/scutil", "--dns"]
    control = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
    restricted = subprocess.run(["/usr/bin/sandbox-exec", "-D", "PROTECTED=" + str(tmp_path), "-D", "WORK=" + str(tmp_path),
                                 "-D", "ENDPOINT=localhost:1", "-f", str(PROFILE), *command],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
    assert control.returncode == 0 and restricted.returncode == 0
    assert b"nameserver[" in control.stdout and b"nameserver[" in restricted.stdout


def test_dns_resolution_and_system_configuration_remain_reachable(tmp_path):
    commands = [
        ["/usr/sbin/scutil", "--dns"],
        ["/usr/bin/dscacheutil", "-q", "host", "-a", "name", "localhost"],
    ]
    for command in commands:
        control = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
        restricted = subprocess.run(["/usr/bin/sandbox-exec", "-D", "PROTECTED=" + str(tmp_path),
                                     "-D", "WORK=" + str(tmp_path), "-D", "ENDPOINT=localhost:1",
                                     "-f", str(PROFILE), *command],
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
        assert control.returncode == 0
        assert restricted.returncode == 0
        assert control.stdout
        assert restricted.stdout
