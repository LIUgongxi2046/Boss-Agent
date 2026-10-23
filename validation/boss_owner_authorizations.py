"""N10: BOSS-only revocation of an existing, still-valid authorization.

Revocation blocks future *use* of that authorization. It never unsends an
already simulated message, undoes an earlier decision, or rewrites an audit.
All state and the original request receipt are committed atomically.
"""
from __future__ import annotations

from datetime import datetime, timezone

from aiohttp import web

from business import checksum, now, require

NS = "ui-check"


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
    try:
        expiry = datetime.fromisoformat(current["valid_until"])
    except (KeyError, ValueError, TypeError):
        raise web.HTTPConflict(text="原授权有效期无法核实") from None
    require(expiry.tzinfo is not None and expiry > datetime.now(timezone.utc),
            "已到期授权不再可使用，不需重复撤销", web.HTTPConflict)
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
    return {
        "source_type": "SIMULATED", "authorization_id": identifier,
        "version": current["version"], "revoked": True,
        "revoked_at": current["revoked_at"],
        "revocation_authorization_id": revocation_auth,
        "future_authorization_use_blocked": True,
        "historical_business_actions_undone": False,
        "external_delivery_recalled": False,
    }
