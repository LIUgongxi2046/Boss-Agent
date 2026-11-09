import json
import os
import sys
from pathlib import Path

import pytest

from hermes_process_launch import process_launch_options
from test_hermes_process_evidence import running_process_store


def test_launch_closes_inherited_descriptors_and_limits_environment(tmp_path):
    _, _, evidence, run_id, epoch = running_process_store(tmp_path)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(read_fd, True)
    previous = os.environ.get("HERMES_PROCESS_TEST_VARIABLE")
    os.environ["HERMES_PROCESS_TEST_VARIABLE"] = "test"
    output = tmp_path / "result.json"
    probe = Path(__file__).with_name("hermes_launch_boundary_probe.py").resolve()
    try:
        evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check",
                       [sys.executable, str(probe), str(output), str(read_fd)], cwd=tmp_path)
        process = evidence.processes[(run_id, "slot")]
        assert process.wait(timeout=10) == 0
        result = json.loads(output.read_text(encoding="utf-8"))
        assert result["null_streams"] == [True, True, True]
        assert result["descriptor_present"] is False
        assert result["test_variable_present"] is False
        assert set(result["environment_names"]).issubset({"PATH", "HOME", "TMPDIR", "HERMES_HOME", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"})
        assert evidence.observe_exit(run_id, "slot")["exit_scope"] == "LEADER_ONLY"
    finally:
        if previous is None:
            del os.environ["HERMES_PROCESS_TEST_VARIABLE"]
        else:
            os.environ["HERMES_PROCESS_TEST_VARIABLE"] = previous
        os.close(read_fd)
        os.close(write_fd)


def test_launch_options_reject_symlink_workspace(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="工作目录无效"):
        process_launch_options(link)
