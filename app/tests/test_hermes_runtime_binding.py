import shutil
import subprocess
from pathlib import Path

import pytest

from hermes_runtime_binding import HermesDeploymentConfig, HermesExecutionFactory, require_editable_runtime_binding
from hermes_process_launch import process_launch_options
from test_agent_run_dispatcher import services_for


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / ".work/upgrade2/u2-03/dependency-audit-001"
ENGINE = AUDIT / "source"
PYTHON = AUDIT / "environment/bin/python"
SITE = AUDIT / "environment/lib/python3.14/site-packages"


def test_editable_runtime_uses_verified_source_and_rejects_changed_paths(tmp_path):
    require_editable_runtime_binding(PYTHON, ENGINE)
    with pytest.raises(ValueError, match="安装来源"):
        require_editable_runtime_binding(PYTHON, AUDIT / "verified-source")
    environment = process_launch_options(tmp_path)["env"]
    process = subprocess.run([str(PYTHON), "-c", "import site,run_agent,model_tools,tools.registry; assert site.ENABLE_USER_SITE is False; print(run_agent.__file__); print(model_tools.__file__); print(tools.registry.__file__)"],
                             cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60, check=True)
    assert len(process.stdout.splitlines()) == 3
    assert all(Path(line).resolve().is_relative_to(ENGINE.resolve()) for line in process.stdout.splitlines())


def test_editable_runtime_rejects_extra_startup_path(tmp_path):
    site = tmp_path / "env/lib/python3.14/site-packages"
    site.mkdir(parents=True)
    executable = tmp_path / "env/bin/python"
    executable.parent.mkdir()
    shutil.copy2(AUDIT / "environment/pyvenv.cfg", tmp_path / "env/pyvenv.cfg")
    shutil.copy2(SITE / "__editable__.hermes_agent-0.0.0.pth", site)
    shutil.copy2(SITE / "__editable___hermes_agent_0_0_0_finder.py", site)
    shutil.copytree(SITE / "hermes_agent-0.0.0.dist-info", site / "hermes_agent-0.0.0.dist-info")
    require_editable_runtime_binding(executable, ENGINE)
    (site / "unverified.pth").touch()
    with pytest.raises(ValueError, match="启动路径"):
        require_editable_runtime_binding(executable, ENGINE)


def test_execution_factory_rejects_unverified_vm_manager(tmp_path):
    services = services_for(tmp_path)
    path = tmp_path.resolve()
    deployment = HermesDeploymentConfig(path, path, path, path, path, path, 1234, None, True, "unverified")
    with pytest.raises(ValueError, match="管理器不可核查"):
        HermesExecutionFactory(services, deployment)
