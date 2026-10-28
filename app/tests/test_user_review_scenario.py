import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_user_review_scenario import prepare
from boss_page_api import BossPageAPI
from controls import ControlStore


def test_scenario_persists_all_library_categories_and_separate_owner_records(tmp_path):
    directory = tmp_path / "review"
    result = prepare(directory)
    assert result["external_delivery"] is False
    pages = BossPageAPI(ControlStore(directory / "business.sqlite"))
    status, library = pages.serve("BOSS", "/api/boss/ui/owner/meeting-library")
    assert status == 200
    assert {row["kind"] for row in library["records"]} == {"meeting", "document", "approval", "research", "people"}
    status, tasks = pages.serve("BOSS", "/api/boss/ui/tasks")
    assert status == 200 and len(tasks["tasks"]) == 2 and len(tasks["self_commitments"]) == 1
    assert all(task["status"] == "WAITING_FEEDBACK" for task in tasks["tasks"])
    assert pages.serve("MAINTAINER", "/api/boss/ui/tasks")[0] == 403
    with pytest.raises(FileExistsError):
        prepare(directory)
    assert pages.serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"] == tasks["tasks"]
