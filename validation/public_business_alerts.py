import json
from urllib.parse import parse_qs

from aiohttp import web

from business import require


def read_alerts(store, role, namespace, query_string):
    from boss_business_alerts import BusinessAlertsAPI

    require(role == "BOSS", "经营提醒仅限本人读取", web.HTTPForbidden)
    require(namespace == "ui-check", "经营提醒执行范围无效", web.HTTPConflict)
    values = parse_qs(query_string, keep_blank_values=True)
    require(not values or set(values) == {"event_id"} and len(values["event_id"]) == 1
            and 0 < len(values["event_id"][0]) <= 200, "经营提醒查询参数无效", web.HTTPBadRequest)
    return BusinessAlertsAPI(store).read(role, values["event_id"][0] if values else None)


def read_rules(store, role, namespace, query_string):
    from boss_alert_rules import BusinessAlertRulesAPI

    require(namespace == "ui-check", "经营规则执行范围无效", web.HTTPConflict)
    require(query_string == "", "经营规则不接受额外查询参数", web.HTTPBadRequest)
    return BusinessAlertRulesAPI(store).read(role)


def input_catalog(store, role, namespace, query_string):
    from boss_alert_policy import MANIFEST, GENERATOR

    require(role == "MAINTAINER", "演示输入仅限技术维护", web.HTTPForbidden)
    require(namespace == "ui-check" and query_string == "", "演示输入查询范围无效", web.HTTPBadRequest)
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db, namespace)
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='event' AND id=? AND json_extract(body,'$.generated_by')=?",
                         (namespace, MANIFEST["event_id"], GENERATOR)).fetchone()
        event = json.loads(row[0]) if row else None
        clock = store.get(db, namespace, "clock", "current")
    return {"source_type": "SIMULATED", "definition": MANIFEST,
            "event_version": event["version"] if event else "0", "business_clock": clock["at"],
            "business_authorization_granted": False, "private_body_included": False}
