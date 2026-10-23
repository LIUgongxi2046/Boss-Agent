import json

from aiohttp import web

from business import require


def confirmed_memory(db, namespace, memory, owner_id):
    if memory["confirmation_state"] != "CONFIRMED":
        return None
    matches = []
    for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='authorization'", (namespace,)).fetchall():
        authorization = json.loads(row[0])
        if (authorization.get("action") == "memory.confirm"
                and authorization.get("target_id") == memory["memory_id"]
                and authorization.get("owner_id") == owner_id
                and authorization.get("issuer_identity") == "BOSS"
                and authorization.get("scope") == namespace
                and int(authorization["content_version"]) + 1 == int(memory["version"])
                and authorization["payload"].get("expected_version") == authorization["content_version"]):
            matches.append(authorization)
    require(len(matches) <= 1, "当前记忆存在相互冲突的确认授权", web.HTTPConflict)
    if memory.get("authorization_id") is not None:
        require(len(matches) == 1 and matches[0]["authorization_id"] == memory["authorization_id"],
                "当前记忆的确认授权关联不符", web.HTTPForbidden)
    # 当前确认事务以同一对象的前置版本保存授权；初始获准记忆保留其来源确认。
    if matches and matches[0]["revoked"]:
        return None
    return memory
