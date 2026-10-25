from aiohttp import web

from business import require
from boss_source_policy import source_validity


def require_current_simulated_source(document, owner_id, business_at):
    require(document.get("source_type") == "SIMULATED" and document.get("access_scope") == owner_id,
            "资料不属于当前本人获准范围", web.HTTPForbidden)
    state = source_validity(document, business_at)
    require(state == "VALID", "资料当前不可采用：" + state,
            web.HTTPGone if state in ("WITHDRAWN", "EXPIRED") else web.HTTPConflict)
    return document


def require_current_business_source(store, db, namespace, owner_id, source_id):
    initial = store.get(db, namespace, "initial", "snapshot")
    require(initial["owner_id"] == owner_id, "来源请求不属于当前本人范围", web.HTTPForbidden)
    document = store.get(db, namespace, "document", source_id)
    require(document.get("source_id") == source_id, "来源标识与当前记录不符", web.HTTPForbidden)
    return store.assignment_sources(db, namespace, initial, [source_id])[source_id]
