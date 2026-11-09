import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_token_change_with_unsaved_edit_shows_notice():
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_draft_token_notice_check.cjs")],
                            cwd=ROOT, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["dirty_token_change_notice"] is True
    assert value["clean_token_change_silent"] is True
    assert value["dismiss"] is True
    assert value["wiring"] is True
