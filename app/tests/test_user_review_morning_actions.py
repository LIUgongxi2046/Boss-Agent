import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "review.sqlite")
    store.initialize("ui-check")
    return store, BossCommandAPI(store), BossPageAPI(store)


def execute(api, role, command, **payload):
    return api.execute(role, command, {"client_request_id": str(uuid4()), **payload})


def configure(api, **extra):
    return execute(api, "MAINTAINER", "boss.technical.secretary.save", **{
        "expected_version": "0", "recipient_id": "coordinator-1", "channel": "EMAIL", "address": "secretary@example.test", **extra})


def view(pages):
    status, result = pages.serve("BOSS", "/api/boss/ui/owner/morning-actions")
    assert status == 200, result
    return result


def test_configuration_permissions_and_stale_update(services):
    store, api, pages = services
    assert configure(api)[0] == 200
    assert configure(api)[0] == 409
    code, result = pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/secretary")
    assert code == 200 and result["configuration"]["channel"] == "EMAIL"
    assert pages.serve("BOSS", "/api/boss/ui/admin/technical/secretary")[0] == 403
    assert pages.serve("MAINTAINER", "/api/boss/ui/owner/morning-actions")[0] == 403
    assert execute(api, "BOSS", "boss.technical.secretary.save", expected_version="1", recipient_id="coordinator-1", channel="EMAIL", address="secretary@example.test")[0] == 403
    assert configure(api, expected_version="1", address="invalid-address")[0] == 400
    assert configure(api, expected_version="1", channel="INTERNAL_IM", address="secretary-001")[0] == 200
    with store.connect() as db:
        assert store.get(db, "ui-check", "secretary_configuration", "current")["version"] == "2"


def test_one_message_for_selected_items_and_recorded_reply(services):
    store, api, pages = services
    assert configure(api)[0] == 200
    code, result = execute(api, "MAINTAINER", "boss.simulation.application.seed", application_id="application-1",
        applicant_contact_id="finance-1", amount_cny="3000.00", title="采购设备申请", description="申请采购设备，需要核查报价。",
        attachment_text="模拟采购申请：设备报价合计三千元，供本地流程验证使用。")
    assert code == 200, result
    current = view(pages)
    selected = [item["item_id"] for item in current["items"][:2]]
    assert len(selected) == 2
    payload = {"client_request_id": str(uuid4()), "snapshot_sha256": current["snapshot_sha256"], "item_ids": selected,
               "secretary_version": "1", "comment": "请协助处理并反馈。"}
    command = "boss.owner_workspace.morning-actions.delegate"
    assert api.execute("MAINTAINER", command, payload)[0] == 403
    status, receipt = api.execute("BOSS", command, payload)
    assert status == 200, receipt
    assert api.execute("BOSS", command, payload) == (status, receipt)
    messages = view(pages)["messages"]
    assert len(messages) == 1 and messages[0]["item_ids"] == selected
    assert messages[0]["channel"] == "EMAIL" and messages[0]["external_channel_invoked"] is False
    assert all(item["title"] in messages[0]["body"] for item in current["items"][:2])
    assert pages.serve("BOSS", "/api/boss/ui/owner/morning-actions/requests/" + payload["client_request_id"]) == (status, receipt)
    code, result = execute(api, "MAINTAINER", "boss.simulation.message.reply", message_id=messages[0]["message_id"], author_contact_id="coordinator-1", text="已经安排核查，下午反馈。")
    assert code == 200, result
    assert view(pages)["replies"][0]["text"] == "已经安排核查，下午反馈。"
    status, audit = pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/audit")
    assert status == 200
    record = next(record for record in audit["records"] if record["action"] == command)
    assert record["result_refs"][0]["id"] == messages[0]["message_id"]
    assert record["role"] == "BOSS" and "body" not in record
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_outbox'").fetchone()[0] == 1


def test_stale_configuration_and_missing_items_do_not_send(services):
    store, api, pages = services
    assert configure(api)[0] == 200
    current = view(pages)
    payload = {"snapshot_sha256": current["snapshot_sha256"], "item_ids": [current["items"][0]["item_id"]], "secretary_version": "1", "comment": "请处理当前事项。"}
    assert configure(api, expected_version="1", channel="INTERNAL_IM", address="assistant-user")[0] == 200
    assert execute(api, "BOSS", "boss.owner_workspace.morning-actions.delegate", **payload)[0] == 409
    assert execute(api, "BOSS", "boss.owner_workspace.morning-actions.delegate", **{**payload, "secretary_version": "2", "item_ids": ["application:absent"]})[0] == 409
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_outbox'").fetchone()[0] == 0


def test_non_application_cannot_be_approved(services):
    _, api, pages = services
    current = view(pages)
    item = next(item for item in current["items"] if item["approval"] is None)
    code, result = execute(api, "BOSS", "boss.owner_workspace.morning-actions.approve", snapshot_sha256=current["snapshot_sha256"], item_ids=[item["item_id"]], comment="确认处理。")
    assert code == 400, result


@pytest.mark.parametrize("action,expected", [("approve", "APPROVED_RECORDED"), ("reject", "REJECTED_RECORDED")])
def test_application_decision_persists_and_rejects_stale_selection(services, action, expected):
    store, api, pages = services
    code, result = execute(api, "MAINTAINER", "boss.simulation.application.seed", application_id="application-1",
        applicant_contact_id="finance-1", amount_cny="3000.00", title="采购设备申请", description="申请采购设备，需要核查报价。",
        attachment_text="模拟采购申请：设备报价合计三千元，供本地流程验证使用。")
    assert code == 200, result
    current = view(pages)
    item = next(item for item in current["items"] if item["approval"] is not None)
    assert item["approval"]["amount"] == "3000.00"
    payload = {"snapshot_sha256": current["snapshot_sha256"], "item_ids": [item["item_id"]], "comment": "已核查金额与附件。"}
    code, result = execute(api, "BOSS", "boss.owner_workspace.morning-actions." + action, **payload)
    assert code == 200, result
    assert execute(api, "BOSS", "boss.owner_workspace.morning-actions." + action, **payload)[0] == 409
    with store.connect() as db:
        assert store.get(db, "ui-check", "application", "application-1")["state"] == expected
    assert item["item_id"] not in [item["item_id"] for item in view(pages)["items"]]
