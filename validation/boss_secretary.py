from email.headerregistry import Address

from aiohttp import web

from business import now, require
from boss_message_calendar import _contact
from boss_v7_store import NAMESPACE, optional, text


def read_secretary(store, db, snapshot):
    return {"configuration": optional(db, "secretary_configuration", "current"),
            "contacts": [{"id": row["contact_id"], "name": row["name"], "organization": row["organization"]}
                         for row in snapshot["contacts"]]}


def save_secretary(api, db, snapshot, payload):
    api._exact(payload, {"client_request_id", "expected_version", "recipient_id", "channel", "address"})
    previous = optional(db, "secretary_configuration", "current")
    require(payload["expected_version"] == (previous["version"] if previous else "0"), "秘书配置已经变化，请重新读取")
    recipient = _contact(api, db, snapshot, payload["recipient_id"])
    require(payload["channel"] in {"EMAIL", "INTERNAL_IM"}, "请选择邮件或内部 IM", web.HTTPBadRequest)
    address = text(payload["address"], "接收地址", 320)
    if payload["channel"] == "EMAIL":
        parsed = Address(addr_spec=address)
        require(bool(parsed.username) and bool(parsed.domain), "邮件地址无效", web.HTTPBadRequest)
    value = {"version": str(int(previous["version"]) + 1) if previous else "1",
             "recipient_id": recipient["contact_id"], "recipient_name": recipient["name"],
             "channel": payload["channel"], "address": address, "updated_at": now(), "source_type": "SIMULATED"}
    if previous:
        api.store.put(db, NAMESPACE, "secretary_configuration_revision", previous["version"], previous)
    api.store.put(db, NAMESPACE, "secretary_configuration", "current", value)
    return {"object_id": "secretary", "version": value["version"], "state": "SAVED"}
