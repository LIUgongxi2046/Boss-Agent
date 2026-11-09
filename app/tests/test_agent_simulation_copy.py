import sqlite3
from contextlib import closing

import pytest

from agent_simulation_copy import publish_simulation_copy
from controls import ControlStore


def test_simulated_database_copy_publish_and_retry(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    output = tmp_path / "isolated"
    output.mkdir()
    with closing(sqlite3.connect(store.path)) as source:
        result = publish_simulation_copy(source, output)
        assert result["created"] is True
        assert publish_simulation_copy(source, output, expected_sha256=result["sha256"]) == {"sha256": result["sha256"], "created": False}
        with pytest.raises(ValueError, match="摘要不符"):
            publish_simulation_copy(source, output, expected_sha256="0" * 64)
        with pytest.raises(ValueError, match="已经存在"):
            publish_simulation_copy(source, output)
    with closing(sqlite3.connect(output / "published.sqlite")) as copied, store.connect() as original:
        assert copied.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert copied.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall() == original.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()
    assert sorted(item.name for item in output.iterdir()) == ["published.sqlite"]


def test_copy_failure_removes_only_owned_stage(tmp_path):
    source_path = tmp_path / "business.sqlite"
    source_path.write_bytes(b"invalid sqlite file")
    output = tmp_path / "isolated"
    output.mkdir()
    preserved = output / "preserved.txt"
    preserved.write_text("keep", encoding="utf-8")
    with closing(sqlite3.connect(source_path)) as source:
        with pytest.raises(sqlite3.DatabaseError):
            publish_simulation_copy(source, output)
    assert [item.name for item in output.iterdir()] == ["preserved.txt"]
    assert preserved.read_text(encoding="utf-8") == "keep"


def test_copy_rejects_outside_simulation_directory(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with closing(sqlite3.connect(store.path)) as source:
        with pytest.raises(ValueError, match="仅允许独立模拟"):
            publish_simulation_copy(source, tmp_path.anchor)
