import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from application_paths import application_work_directory, application_ports


def test_default_and_explicit_application_directories_are_isolated(tmp_path):
    parent = tmp_path / ".work"
    parent.mkdir()
    assert application_work_directory(tmp_path) == parent / "application"
    selected = parent / "meeting-held"
    assert application_work_directory(tmp_path, str(selected)) == selected
    selected.mkdir()
    (selected / "state.txt").write_text("独立检查目录")
    assert not (parent / "application").exists()


@pytest.mark.parametrize("candidate", ["relative", "/", "outside"])
def test_application_directory_rejects_relative_and_external_paths(tmp_path, candidate):
    value = str(tmp_path / candidate) if candidate == "outside" else candidate
    with pytest.raises(ValueError):
        application_work_directory(tmp_path, value)


def test_application_directory_rejects_parent_nested_and_external_symlink(tmp_path):
    parent = tmp_path / ".work"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = parent / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    for candidate in (parent, parent / "nested" / "application", linked):
        with pytest.raises(ValueError):
            application_work_directory(tmp_path, str(candidate))


def test_application_ports_keep_defaults_and_accept_distinct_explicit_ports():
    assert application_ports() == {"business": 8871, "webui": 8872, "gateway": 18791}
    explicit = {"business": 8971, "webui": 8972, "gateway": 18971}
    assert application_ports(json.dumps(explicit)) == explicit


@pytest.mark.parametrize("configured", [
    [], {}, {"business": 8971, "webui": 8972},
    {"business": 8971, "webui": 8971, "gateway": 18971},
    {"business": True, "webui": 8972, "gateway": 18971},
    {"business": "8971", "webui": 8972, "gateway": 18971},
    {"business": 8971.5, "webui": 8972, "gateway": 18971},
    {"business": 1023, "webui": 8972, "gateway": 18971},
    {"business": 65536, "webui": 8972, "gateway": 18971},
    {"business": 8971, "webui": 8972, "gateway": 18971, "extra": 8973},
])
def test_application_ports_reject_incomplete_or_invalid_configuration(configured):
    with pytest.raises(ValueError):
        application_ports(json.dumps(configured))
