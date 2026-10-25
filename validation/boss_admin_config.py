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
        snapshot = store.get(db, namespace, "initial", "snapshot")
        owner = snapshot["owner_id"]
        eligible = confirmed_memory(db, namespace, current, owner) is not None
        state = current["confirmation_state"]
        condition = "namespace=? AND kind='runtime_run' AND json_extract(body,'$.memory_reference.memory_id')=? AND json_extract(body,'$.memory_reference.confirmation_authority_checked')=1"
        parameters = (namespace, current["memory_id"])
        selection_count = db.execute("SELECT COUNT(*) FROM objects WHERE " + condition, parameters).fetchone()[0]
        latest = db.execute(
            "SELECT id,json_extract(body,'$.memory_reference.version'),json_extract(body,'$.memory_reference.eligible'),"
            "json_extract(body,'$.started_at'),json_extract(body,'$.status'),json_extract(body,'$.model_completion_observed') "
            "FROM objects WHERE " + condition + " ORDER BY json_extract(body,'$.started_at') DESC,id DESC LIMIT 1",
            parameters,
        ).fetchone()
        selection = None
        if latest is not None:
            require(isinstance(latest[1], str) and latest[2] in (0, 1), "记忆采用记录字段无效")
            selection = {
                "run_id": latest[0], "memory_version": latest[1], "eligible": bool(latest[2]),
                "selected_at": latest[3], "run_status": latest[4], "model_completion_observed": bool(latest[5]),
                "matches_current_memory_version": latest[1] == current["version"],
                "observation": "CONTEXT_SELECTION_RECORDED",
            }
        # 字段白名单只包含技术元信息，正文不进入接口结果。
        deleted = state == "DELETED"
        return {
            "projection": "memory-technical-status",
            "source_type": "RUNTIME_RECORD",
            "namespace": namespace,
            "checked_at": now(),
            "owner_scope": {key: snapshot[key] for key in ("owner_id", "dataset_id", "dataset_version")},
            "memory_source_type": snapshot["source_type"],
            "memory": {
                "memory_id": current["memory_id"],
                "version": current["version"],
                "confirmation_state": state,
                "valid_until": current.get("valid_until"),
            },
            "future_context_eligible": eligible,
            "confirmation_authority_checked": True,
            "next_context_memory_version": current["version"] if eligible else None,
            "latest_context_selection": selection,
            "context_selection_count": selection_count,
            "future_turn_policy": "CURRENT_CONFIRMATION_REQUIRED",
            "deletion_propagation": (
                "CURRENT_CONTEXT_CLEARED" if deleted and not current.get("text")
                else "CURRENT_CONTEXT_REQUIRES_REVIEW" if deleted
                else "NOT_REQUESTED"
            ),
            "derived_memory_index": "NOT_USED",
            "deletion_scopes": {
                "current_memory_content": "CLEARED" if deleted and not current.get("text") else "RETAINED" if deleted else "NOT_REQUESTED",
                "initial_approved_source": "RETAINED" if snapshot.get("memory", {}).get("text") else "NOT_PRESENT",
                "loaded_sessions": "NOT_VERIFIED", "backups": "NOT_VERIFIED", "physical_erasure": "NOT_VERIFIED",
            },
            "model_adoption_verified": False,
            "physical_secure_erasure_verified": False,
            "private_body_available_here": False,
            "owner_content_mutation_allowed": False,
        }
