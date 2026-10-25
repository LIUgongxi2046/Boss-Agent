from urllib.parse import urlencode

from test_fc03_morning import store, DAY, query, order
from boss_morning import MorningAPI, validate
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from test_boss_command_api import create_input
from test_product_morning_runtime import validate_output


def test_morning_preparation_does_not_require_unselected_business_links(store):
    morning, commands = MorningAPI(store), BossCommandAPI(store)
    view = query(morning, date="2026-10-23")
    item = next(item for item in view["items"] if item["kind"] == "meeting")
    reference = {field: view[field] for field in ("list_id", "list_version", "snapshot_sha256")}
    reference["item_id"] = item["item_id"]
    payload = create_input("menu-f01-create-current", morning_reference=reference,
        related_meeting_id=None, related_event_ids=[])
    code, created = commands.execute("BOSS", "boss.assignment.create", payload)
    assert code == 200, created
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", created["task_id"])
        assert task["related_meeting_id"] is None and task["related_event_ids"] == []
        assert store.get(db, "ui-check", "morning_assignment_reference", created["task_id"])["morning_reference"] == reference


def test_current_meeting_source_can_be_pinned_without_old_finance_fixture(store):
    """F01 must not reject another authorized simulated source solely by name."""
    morning, commands = MorningAPI(store), BossCommandAPI(store)
    view = query(morning, key="morning-meeting-only-list", date="2026-10-23")
    item = next(row for row in view["items"] if row["kind"] == "meeting")
    refs = {ref["id"]: ref["version"] for ref in item["source_refs"]
            if ref["kind"] == "document"}
    assert "meeting-minutes" in refs and refs["meeting-minutes"]
    reference = {field: view[field] for field in ("list_id", "list_version", "snapshot_sha256")}
    reference["item_id"] = item["item_id"]
    payload = create_input("f01-meeting-source-only", morning_reference=reference,
        source_refs=["meeting-minutes"], related_meeting_id=None, related_event_ids=[])
    status, created = commands.execute("BOSS", "boss.assignment.create", payload)
    assert status == 200, created
    with store.connect() as db:
        saved = store.get(db, "ui-check", "task", created["task_id"])
        assert saved["source_refs"] == ["meeting-minutes"]
        assert saved["source_versions"] == {"meeting-minutes": refs["meeting-minutes"]}
        assert saved["status"] == "OPEN"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0


def test_unbound_legacy_assignment_keeps_original_source_allowlist(store):
    """F01 verified selection does not broaden the ordinary assignment route."""
    commands = BossCommandAPI(store)
    status, result = commands.execute("BOSS", "boss.assignment.create", create_input(
        "unbound-source-whitelist-still-enforced", source_refs=["meeting-minutes"]))
    assert status == 400, result
    with store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind IN ('task','authorization','outbox')"
        ).fetchone()[0] == 0


def test_valid_unrelated_source_cannot_be_pinned_to_selected_morning_item(store):
    """Even a current BOSS-readable document cannot escape its selected item."""
    commands = BossCommandAPI(store)
    status, _ = commands.execute("MAINTAINER", "boss.knowledge.source.create", {
        "client_request_id": "f01-unrelated-current-document",
        "source_id": "sim-doc-f01-unrelated",
        "title": "另一个事项的独立模拟依据",
        "author_contact_id": "finance-1",
        "published_at": "2026-10-22",
        "content": "这份当前有效的模拟原文仅验证来源绑定，不能被未关联的晨间事项用作交办依据。",
    })
    assert status == 200
    morning = MorningAPI(store)
    view = query(morning, key="f01-isolated-source-query", date="2026-10-23")
    item = next(row for row in view["items"] if row["kind"] == "meeting")
    assert "sim-doc-f01-unrelated" not in {
        ref["id"] for ref in item["source_refs"] if ref["kind"] == "document"
    }
    reference = {field: view[field] for field in ("list_id", "list_version", "snapshot_sha256")}
    reference["item_id"] = item["item_id"]
    status, result = commands.execute("BOSS", "boss.assignment.create", create_input(
        "f01-cross-item-source-denied",
        morning_reference=reference, source_refs=["sim-doc-f01-unrelated"],
        related_meeting_id=None, related_event_ids=[],
    ))
    assert status == 409, result
    with store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind IN ('task','authorization','outbox')"
        ).fetchone()[0] == 0


def test_public_morning_day_preview_is_actual_and_strict(store):
    pages = BossPageAPI(store)
    days = [{"date": "2026-10-23", "timezone": "Asia/Shanghai"}, DAY]
    views = []
    for day in days:
        status, view = pages.serve("BOSS", "/api/boss/ui/morning/preview", urlencode(day))
        assert status == 200
        validate("View", view)
        assert view["date"] == day["date"] and view["list_id"] is None
        views.append(view)
    assert {row["object_id"] for row in views[0]["items"]} != {row["object_id"] for row in views[1]["items"]}
    for role, expected in ((None, 401), ("MAINTAINER", 403)):
        assert pages.serve(role, "/api/boss/ui/morning/preview", urlencode(DAY))[0] == expected
    for parameters in ("date=2026-10-23", "date=2026-10-23&date=2026-10-24&timezone=UTC", urlencode({**DAY, "owner_id": "other"})):
        assert pages.serve("BOSS", "/api/boss/ui/morning/preview", parameters)[0] == 400
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='morning_list'").fetchone()[0] == 0


def test_public_versioned_list_detail_source_order_and_history(store):
    api, pages, commands = MorningAPI(store), BossPageAPI(store), BossCommandAPI(store)
    view = query(api, date="2026-10-23")
    lid = view["list_id"]
    status, current = pages.serve("BOSS", "/api/boss/ui/morning/list", urlencode({"list_id": lid}))
    assert status == 200 and current["result"] == view
    for item in view["items"]:
        status, detail = pages.serve("BOSS", "/api/boss/ui/morning/detail", urlencode({"list_id": lid, "item_id": item["item_id"]}))
        assert status == 200 and detail["list_version"] == view["list_version"] and detail["item"] == item
        assert detail["business_authorization_granted"] is False
    source = next(row for row in view["source_statuses"] if row["status"] == "VALID")
    status, document = pages.serve("BOSS", "/api/boss/ui/morning/source", urlencode({"list_id": lid, "source_id": source["source_id"]}))
    assert status == 200 and document["document"]["version"] == source["version"]
    request = order(view)
    status, saved = commands.execute("BOSS", "boss.today.reorder", request)
    assert status == 200 and saved["list_id"] == lid
    status, receipt = pages.serve("BOSS", "/api/boss/ui/morning/receipt", urlencode({"action": "boss.today.reorder", "client_request_id": request["client_request_id"]}))
    assert status == 200 and receipt["result"] == saved and receipt["write_performed_by_lookup"] is False
    assert pages.serve("MAINTAINER", "/api/boss/ui/morning/list", urlencode({"list_id": lid}))[0] == 403
    assert pages.serve("BOSS", "/api/boss/ui/morning/source", urlencode({"list_id": lid, "source_id": "unrelated"}))[0] == 403
    store.control("ui-check", "withdraw", {"source_id": source["source_id"], "version": source["version"]})
    assert pages.serve("BOSS", "/api/boss/ui/morning/list", urlencode({"list_id": lid}))[0] == 409
    status, history = pages.serve("BOSS", "/api/boss/ui/morning/list", urlencode({"list_id": lid, "historical": "true"}))
    assert status == 200 and history["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"
    assert history["result"]["items"] == [] and history["result"]["conflicts"] == []
    assert pages.serve("BOSS", "/api/boss/ui/morning/detail", urlencode({"list_id": lid, "item_id": view["items"][0]["item_id"]}))[0] == 409


def test_public_maintainer_formal_coverage_load_and_receipt(store):
    pages, commands = BossPageAPI(store), BossCommandAPI(store)
    status, catalog = pages.serve("MAINTAINER", "/api/boss/ui/admin/morning-coverage")
    assert status == 200 and catalog["definition"]["generator_version"] == "FC03-COVERAGE-1"
    request = {**DAY, "mode": "SIMULATED", "generator_version": "FC03-COVERAGE-1", "seed": 20261024,
               "client_request_id": "public-morning-coverage", "expected_version": "0"}
    action = "boss.simulation.morning_coverage.load"
    assert commands.execute("BOSS", action, request)[0] == 403
    status, loaded = commands.execute("MAINTAINER", action, request)
    assert status == 200 and loaded["business_authorization_granted"] is False and loaded["external_service_invoked"] is False
    assert commands.execute("MAINTAINER", action, request) == (status, loaded)
    status, receipt = pages.serve("MAINTAINER", "/api/boss/ui/admin/morning-coverage-receipt", urlencode({"client_request_id": request["client_request_id"]}))
    assert status == 200 and receipt["result"] == loaded
    status, catalog = pages.serve("MAINTAINER", "/api/boss/ui/admin/morning-coverage")
    assert status == 200 and catalog["loaded"][0]["version"] == "1"
    view = pages.serve("BOSS", "/api/boss/ui/morning/preview", urlencode(DAY))[1]
    assert {row["state"] for row in view["source_coverage"]} == {"NOT_UPDATED", "UNSYNCHRONIZED"}
    for role, expected in (("BOSS", 403), (None, 401)):
        assert pages.serve(role, "/api/boss/ui/admin/morning-coverage")[0] == expected
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','outbox','authorization')").fetchone()[0] == 0


def test_public_assignment_confirmation_keeps_current_morning_reference(store):
    api, commands = MorningAPI(store), BossCommandAPI(store)
    view = query(api, date="2026-10-23")
    item = next(item for item in view["items"] if item["kind"] == "meeting")
    reference = {"list_id": view["list_id"], "list_version": view["list_version"], "item_id": item["item_id"], "snapshot_sha256": view["snapshot_sha256"]}
    validate_output("MorningReference", reference)
    payload = create_input("morning-current-assignment", morning_reference=reference)
    for index, (changed, expected) in enumerate((({**reference, "owner_id": "other"}, 400), ({**reference, "item_id": "unrelated-item"}, 403), ({**reference, "list_version": "999"}, 409))):
        assert commands.execute("BOSS", "boss.assignment.create", {**payload, "client_request_id": "morning-invalid-reference-" + str(index), "morning_reference": changed})[0] == expected
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('task','authorization','morning_assignment_reference')").fetchone()[0] == 0
    assert commands.execute("MAINTAINER", "boss.assignment.create", payload)[0] == 403
    status, created = commands.execute("BOSS", "boss.assignment.create", payload)
    assert status == 200, created
    assert commands.execute("BOSS", "boss.assignment.create", payload) == (status, created)
    with store.connect() as db:
        saved = store.get(db, "ui-check", "morning_assignment_reference", created["task_id"])
        assert saved["morning_reference"] == reference
        assert db.execute("SELECT count(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
    assert commands.execute("BOSS", "boss.assignment.create", {**payload, "client_request_id": "morning-stale-assignment"})[0] == 409
