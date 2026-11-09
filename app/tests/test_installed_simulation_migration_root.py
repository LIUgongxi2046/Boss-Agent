import os
import sqlite3
import subprocess
from pathlib import Path


def test_installed_migration_root_rejects_other_databases_and_symlinks(tmp_path):
    project = Path(__file__).resolve().parents[2]
    python = project / ".work/upgrade2/u2-03/product-env-013/bin/python"
    root = project / ".work/upgrade2-u2-08-simulated"
    database = tmp_path / "business.sqlite"
    with sqlite3.connect(database):
        pass
    env = {**os.environ, "BOSS_SIMULATION_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [str(python), "-I", "-c", "from boss_agent_runtime.boss_agent_runtime_bootstrap import install_path; install_path(); from agent_simulation_migration_install import install_simulation_migrations; import sys; install_simulation_migrations(sys.argv[1])"]
    rejected = subprocess.run([*command, str(database)], env=env, capture_output=True, text=True, timeout=30)
    assert rejected.returncode != 0
    assert "仅允许独立模拟业务数据库" in rejected.stderr
    parent = tmp_path / ".work"
    parent.mkdir()
    link = parent / "upgrade2-u2-08-simulated"
    link.symlink_to(root, target_is_directory=True)
    env["BOSS_SIMULATION_ROOT"] = str(link)
    rejected_root = subprocess.run([*command, str(database)], env=env, capture_output=True, text=True, timeout=30)
    assert rejected_root.returncode != 0
    assert "符号链接" in rejected_root.stderr
