import json

from boss_v7_store import NAMESPACE, optional


def read_audit(db):
    records = []
    for identifier, action, raw_input, raw_output, created_at in db.execute(
        "SELECT id,operation,input,output,created_at FROM audit WHERE namespace=? ORDER BY id DESC", (NAMESPACE,)
    ).fetchall():
        request, result = json.loads(raw_input), json.loads(raw_output)
        authorization_id = result.get("authorization_id", request.get("authorization_id"))
        authorization = optional(db, "authorization", authorization_id) if authorization_id else None
        references = [{"type": kind, "id": result[field], "version": result.get("version"), "state": result.get("status", result.get("state", "RECORDED"))}
                      for field, kind in (("task_id", "task"), ("run_id", "runtime_run"), ("message_id", "message"), ("meeting_id", "meeting"), ("source_id", "document"), ("object_id", "configuration"))
                      if isinstance(result.get(field), str)]
        state = result.get("status", result.get("state", "RECORDED"))
        records.append({"id": str(identifier), "action": action,
                        "target_id": authorization["target_id"] if authorization else references[0]["id"] if references else "",
                        "target_version": authorization["content_version"] if authorization else result.get("version"),
                        "request_id": request.get("client_request_id", request.get("request_id")), "run_id": result.get("run_id"),
                        "role": request.get("role", "BOSS" if authorization else "NOT_RECORDED"), "state": state,
                        "authorization_id": authorization_id, "authorization_state": "REVOKED" if authorization and authorization.get("revoked") else "RECORDED" if authorization else "NOT_ATTACHED",
                        "scope": [authorization["scope"]] if authorization else [NAMESPACE], "valid_until": authorization.get("valid_until") if authorization else None,
                        "revoked_at": authorization.get("revoked_at") if authorization else None, "executed_at": created_at,
                        "created_at": created_at, "reason": None, "result_refs": references})
    return {"records": records}
