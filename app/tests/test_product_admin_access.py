import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_page_api import BossPageAPI
from controls import ControlStore
from boss_command_api import BossCommandAPI


def test_memory_status_route_uses_authenticated_maintenance_role(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    api = BossPageAPI(store)
    status, result = api.serve("MAINTAINER", "/api/boss/ui/admin/memory-status")
    assert status == 200
    assert result["projection"] == "memory-technical-status"
    assert result["private_body_available_here"] is False
    assert "text" not in result["memory"]
    assert api.serve("BOSS", "/api/boss/ui/admin/memory-status")[0] == 403
    assert api.serve(None, "/api/boss/ui/admin/memory-status")[0] == 401


def test_memory_status_rejects_caller_scope(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    api = BossPageAPI(store)
    assert api.serve("MAINTAINER", "/api/boss/ui/admin/memory-status", "namespace=ui-check")[0] == 400


def test_today_public_read_and_order_receipt(tmp_path):
    store = ControlStore(tmp_path / "today.sqlite")
    store.initialize("ui-check")
    reads = BossPageAPI(store)
    status, projection = reads.serve("BOSS", "/api/boss/ui/today")
    assert status == 200
    payload = {"client_request_id": "integration-today-order", "expected_version": projection["order_version"],
               "snapshot_sha256": projection["snapshot_sha256"], "item_ids": [item["item_id"] for item in projection["items"]]}
    status, saved = BossCommandAPI(store).execute("BOSS", "boss.today.reorder", payload)
    assert status == 200
    assert BossCommandAPI(store).execute("BOSS", "boss.today.reorder", payload) == (200, saved)
    assert reads.serve("MAINTAINER", "/api/boss/ui/today")[0] == 403
    assert BossCommandAPI(store).execute("MAINTAINER", "boss.today.reorder", payload)[0] == 403
    status, receipt = reads.serve("BOSS", "/api/boss/ui/operation-status", "action=boss.today.reorder&client_request_id=integration-today-order")
    assert status == 200
    assert receipt["result"]["item_ids"] == payload["item_ids"]
    assert receipt["result"]["date"] == projection["date"]


def test_owner_plans_public_read_is_owner_only(tmp_path):
    store = ControlStore(tmp_path / "plans.sqlite")
    store.initialize("ui-check")
    api = BossPageAPI(store)
    assert api.serve("BOSS", "/api/boss/ui/owner-plans")[0] == 200
    assert api.serve("MAINTAINER", "/api/boss/ui/owner-plans")[0] == 403
    assert api.serve("BOSS", "/api/boss/ui/owner-plans", "namespace=ui-check")[0] == 400
