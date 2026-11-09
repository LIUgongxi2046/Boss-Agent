import sqlite3

import pytest

from agent_run_store import RunStore
from controls import ControlStore


def backup(source, target):
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def test_simulated_business_backup_migration_and_restore(tmp_path):
    original = tmp_path / "business.sqlite"
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    restored = tmp_path / "restored.sqlite"
    restored_before = tmp_path / "restored-before.sqlite"
    store = ControlStore(original)
    store.initialize("ui-check")
    with store.connect() as db:
        baseline = db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()
        spaces = db.execute("SELECT namespace,active,snapshot FROM spaces ORDER BY namespace").fetchall()
    backup(original, before)
    with pytest.raises(ValueError, match="尚未完成迁移"):
        RunStore(original, allow_migration=False)
    with sqlite3.connect(original) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_runs'").fetchone() is None
    runs = RunStore(original)
    assert RunStore(original, allow_migration=False).path == original
    run_id = runs.create_run("boss-1", "ui-check", "request-1", "digest-1")
    assert RunStore(original).read_run(run_id)["run_id"] == run_id
    with store.connect() as db:
        assert db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall() == baseline
        assert db.execute("SELECT namespace,active,snapshot FROM spaces ORDER BY namespace").fetchall() == spaces
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    backup(original, after)
    backup(after, restored)
    backup(before, restored_before)
    assert RunStore(restored).read_run(run_id)["run_id"] == run_id
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall() == baseline
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with sqlite3.connect(before) as db:
        assert db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall() == baseline
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_runs'").fetchone() is None
    with sqlite3.connect(restored_before) as db:
        assert db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall() == baseline
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_runs'").fetchone() is None
