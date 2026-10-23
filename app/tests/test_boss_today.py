import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from controls import ControlStore
from boss_today import TodayAPI


def test_classification_provenance_order_cas_and_restart(tmp_path):
    store = ControlStore(tmp_path / "today.sqlite")
    store.initialize("ui-check")
    today = TodayAPI(store)
    view = today.read("BOSS")
    assert view["coverage_state"] == "PARTIAL"
    assert view["missing_sources"]
    assert len({i["item_id"] for i in view["items"]}) == len(view["items"])
    assert {i["category"] for i in view["items"]} <= {"DECIDE", "COORDINATE", "INFORM"}
    assert all(i["reason"] and i["source_refs"] for i in view["items"])
    order = list(reversed([i["item_id"] for i in view["items"]]))
    payload = {"client_request_id": "today-order-save", "expected_version": "0",
               "snapshot_sha256": view["snapshot_sha256"], "item_ids": order}
    saved = today.reorder("BOSS", payload)
    assert saved["version"] == "1"
    assert today.reorder("BOSS", payload) == saved
    assert [i["item_id"] for i in TodayAPI(ControlStore(store.path)).read("BOSS")["items"]] == order
    with pytest.raises(web.HTTPConflict):
        today.reorder("BOSS", {**payload, "client_request_id": "today-stale-version"})
    with pytest.raises(web.HTTPBadRequest):
        today.reorder("BOSS", {**payload, "client_request_id": "today-incomplete-order",
                              "expected_version": "1", "item_ids": order[:-1]})


def test_changed_sources_reject_old_order_and_private_roles(tmp_path):
    store = ControlStore(tmp_path / "today-cas.sqlite")
    store.initialize("ui-check")
    today = TodayAPI(store)
    view = today.read("BOSS")
    store.control("ui-check", "clock", {"at": "2026-10-23T09:00:00+08:00"})
    with pytest.raises(web.HTTPConflict):
        today.reorder("BOSS", {"client_request_id": "today-stale-source", "expected_version": "0",
                               "snapshot_sha256": view["snapshot_sha256"],
                               "item_ids": [i["item_id"] for i in view["items"]]})
    for role, error in [(None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)]:
        with pytest.raises(error):
            today.read(role)
        with pytest.raises(error):
            today.reorder(role, {})
