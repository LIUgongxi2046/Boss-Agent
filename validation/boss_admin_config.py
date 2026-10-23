from aiohttp import web

from business import now, require
from boss_prompt_config import KINDS, _select_runtime_prompts, obj
from boss_source_policy import source_validity
from boss_memory import confirmed_memory


def prompt_technical_status(store, role, namespace="ui-check"):
    require(role is not None, "需要认证身份", web.HTTPUnauthorized)
    require(role == "MAINTAINER", "需要技术维护身份", web.HTTPForbidden)
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db, namespace)
        data = store.get(db, namespace, "initial", "snapshot")
        clock = store.get(db, namespace, "clock", "current")["at"]
        selected = {item["kind"] for item in _select_runtime_prompts(store, db, namespace)}
        items = []
        for kind in KINDS:
            active = obj(db, "prompt_active", kind, namespace)
            reasons, sources = [], []
            draft = obj(db, "prompt_draft", active["prompt_id"], namespace) if active else None
            if active is None:
                reasons.append("NOT_CONFIGURED")
            elif not active["enabled"]:
                reasons.append("DISABLED")
            elif draft is None:
                reasons.append("DRAFT_MISSING")
            elif draft["version"] != active["prompt_version"] or draft["content_sha256"] != active["content_sha256"]:
                reasons.append("DRAFT_VERSION_CHANGED")
            elif draft["validation_status"] != "VALIDATED_STATIC_ONLY":
                reasons.append("DRAFT_NOT_VALIDATED")
            if active and active["enabled"] and draft and not reasons:
                for reference in draft["source_refs"]:
                    source = obj(db, "document", reference["source_id"], namespace)
                    accessible = source is not None and source.get("access_scope") == data["owner_id"] and source.get("source_type") == "SIMULATED"
                    state = source_validity(source, clock) if accessible else "MISSING" if source is None else "FORBIDDEN"
                    current_version = source.get("version") if accessible else None
                    if state != "VALID":
                        reasons.append("SOURCE_" + state)
                    if accessible and current_version != reference["version"]:
                        reasons.append("SOURCE_VERSION_CHANGED")
                    sources.append({
                        "source_id": reference["source_id"], "pinned_version": reference["version"],
                        "current_version": current_version, "validity_state": state,
                    })
            eligible = kind in selected
            require(eligible == (not reasons), "Prompt采用诊断与当前选择结果不一致")
            items.append({
                "kind": kind, "configured": active is not None,
                "enabled": active["enabled"] if active else False,
                "prompt_id": active["prompt_id"] if active else None,
                "prompt_version": active["prompt_version"] if active else None,
                "active_version": active["active_version"] if active else None,
                "future_context_eligible": eligible,
                "exclusion_reasons": list(dict.fromkeys(reasons)), "source_status": sources,
            })
        return {
            "projection": "prompt-technical-status", "namespace": namespace,
            "checked_at": now(), "items": items,
            "private_body_available_here": False, "configuration_mutation_performed": False,
            "context_load_recorded": False, "model_adoption_verified": False,
        }


def memory_technical_status(store, role, namespace="ui-check"):
    require(role is not None, "需要认证身份", web.HTTPUnauthorized)
    require(role == "MAINTAINER", "需要技术维护身份", web.HTTPForbidden)
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db, namespace)
        current = store.get(db, namespace, "memory", "current")
        owner = store.get(db, namespace, "initial", "snapshot")["owner_id"]
        eligible = confirmed_memory(db, namespace, current, owner) is not None
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
            "future_context_eligible": eligible,
            "future_turn_policy": "CURRENT_CONFIRMATION_REQUIRED",
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
