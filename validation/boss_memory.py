import json
from datetime import datetime

from aiohttp import web

from business import require


def current_memory(db, namespace):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='memory' AND id='current'", (namespace,)).fetchone()
    return json.loads(row[0]) if row is not None else None


def confirmed_memory(db, namespace, memory, owner_id):
    if memory is None:
        return None
    if memory["confirmation_state"] != "CONFIRMED":
        return None
    if memory.get("valid_until") is not None:
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='clock' AND id='current'", (namespace,)).fetchone()
        require(row is not None, "记忆有效期缺少业务时钟")
        expiry = datetime.fromisoformat(memory["valid_until"])
        reference = datetime.fromisoformat(json.loads(row[0])["at"])
        require(expiry.tzinfo is not None and reference.tzinfo is not None, "记忆有效期需要包含时区")
        if reference >= expiry:
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
