from aiohttp import web

from business import now, require


def memory_technical_status(store, role, namespace="ui-check"):
    require(role is not None, "需要认证身份", web.HTTPUnauthorized)
    require(role == "MAINTAINER", "需要技术维护身份", web.HTTPForbidden)
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db, namespace)
        current = store.get(db, namespace, "memory", "current")
        state = current["confirmation_state"]
        # 字段白名单只包含技术元信息，正文不进入接口结果。
        deleted = state == "DELETED"
        return {
            "projection": "memory-technical-status",
            "namespace": namespace,
            "checked_at": now(),
            "memory": {
                "memory_id": current["memory_id"],
                "version": current["version"],
                "confirmation_state": state,
                "valid_until": current.get("valid_until"),
            },
            "future_context_eligible": state == "CONFIRMED",
            "future_turn_policy": "CONFIRMED_ONLY",
            "deletion_propagation": (
                "CURRENT_CONTEXT_CLEARED" if deleted and not current.get("text")
                else "CURRENT_CONTEXT_REQUIRES_REVIEW" if deleted
                else "NOT_REQUESTED"
            ),
            "derived_memory_index": "NOT_USED",
            "model_adoption_verified": False,
            "physical_secure_erasure_verified": False,
            "private_body_available_here": False,
            "owner_content_mutation_allowed": False,
        }
