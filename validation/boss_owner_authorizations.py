from __future__ import annotations

import json
from datetime import datetime, timezone

from aiohttp import web

from business import checksum, now, require

NS = "ui-check"
CONTINUING_USE_ACTIONS = frozenset({"memory.confirm", "owner_goals.confirm", "owner_notice.confirm",
                                   "owner_plan.save", "owner_plan.resume", "calendar.share",
                                   "business_alert.rule.activate", "business_alert.snooze"})


def authorization_can_revoke(authorization, owner_id, namespace):
    if (authorization.get("owner_id") != owner_id or authorization.get("scope") != namespace
            or authorization.get("issuer_identity") != "BOSS" or authorization.get("revoked") is not False
            or not isinstance(authorization.get("action"), str) or not authorization["action"]
            or authorization["action"] == "authorization.revoke"):
        return False
    expiry = datetime.fromisoformat(authorization["valid_until"])
    return expiry.tzinfo is not None and (authorization["action"] in CONTINUING_USE_ACTIONS or expiry > datetime.now(timezone.utc))


def revoke(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "authorization_id", "expected_version", "reason",
    })
    identifier = payload["authorization_id"]
    reason = payload["reason"]
    require(isinstance(identifier, str) and 0 < len(identifier) <= 128,
            "授权编号无效", web.HTTPBadRequest)
    require(isinstance(reason, str) and 0 < len(reason.strip()) <= 400,
            "必须填写具体的撤销理由", web.HTTPBadRequest)
    current = api.store.get(db, NS, "authorization", identifier)
    require(current.get("owner_id") == data["owner_id"]
            and current.get("issuer_identity") == "BOSS"
            and current.get("scope") == NS,
            "仅能撤销本人此前明确授权的对象", web.HTTPForbidden)
    require(current.get("action") != "authorization.revoke",
            "撤销回执不是新的业务授权", web.HTTPForbidden)
    require(current.get("version") == payload["expected_version"],
            "原授权版本已经变化", web.HTTPConflict)
    require(current.get("revoked") is False,
            "该授权已经撤销，不能重复撤销", web.HTTPConflict)
    require(authorization_can_revoke(current, data["owner_id"], NS),
            "原授权当前不满足撤销条件", web.HTTPConflict)
    revocation_auth = api._authorize(db, "authorization.revoke", {
        "target_authorization_id": identifier,
        "expected_version": current["version"],
        "reason_sha256": checksum(reason.strip()),
    }, identifier, current["version"])
    current.update({
        "revoked": True, "revoked_at": now(),
        "revocation_reason_sha256": checksum(reason.strip()),
        "revocation_authorization_id": revocation_auth,
        "version": str(int(current["version"]) + 1),
    })
    api.store.put(db, NS, "authorization", identifier, current)
    if current["action"] == "calendar.share":
        for share_id, body in db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='calendar_share'", (NS,)).fetchall():
            share = json.loads(body)
            if share["authorization_id"] == identifier and not share["revoked"]:
                share.update(revoked=True, revoked_at=current["revoked_at"], revocation_reason="AUTHORIZATION_REVOKED")
                api.store.put(db, NS, "calendar_share", share_id, share)
    return {
        "source_type": "SIMULATED", "authorization_id": identifier,
        "version": current["version"], "revoked": True,
        "revoked_at": current["revoked_at"],
        "revocation_authorization_id": revocation_auth,
        "future_authorization_use_blocked": True,
        "historical_business_actions_undone": False,
        "external_delivery_recalled": False,
    }
