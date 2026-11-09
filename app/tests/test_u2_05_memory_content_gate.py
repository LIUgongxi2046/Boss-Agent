import json
import subprocess
from pathlib import Path

from boss_v7_memory import read_memory
from controls import ControlStore


ROOT = Path(__file__).resolve().parents[2]


def test_memory_gate_uses_independent_current_and_deleted_records(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        before = read_memory(store, db, snapshot)
        assert before["current"] and before["current"]["text"]
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        db.execute("BEGIN")
        after = read_memory(reopened, db, reopened.get(db, "ui-check", "initial", "snapshot"))
    assert after["current"] is None
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_05_memory_content_gate_check.cjs")], input=json.dumps({"before":before,"after":after}, ensure_ascii=False), text=True, capture_output=True, check=True, cwd=ROOT)
    assert json.loads(result.stdout)["stale_hidden"]
