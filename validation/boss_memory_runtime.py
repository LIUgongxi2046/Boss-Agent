from aiohttp import web
from nanobot import RuntimeContextBlock

from business import encode, require
from boss_memory import confirmed_memory


class OwnerMemoryContext:
    def __init__(self, store, namespace="ui-check"):
        self.store = store
        self.namespace = namespace

    async def __call__(self, request):
        require(request.sender_id == "boss-1", "记忆上下文只允许本人采用", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, self.namespace)
            current = self.store.get(db, self.namespace, "memory", "current")
            owner = self.store.get(db, self.namespace, "initial", "snapshot")["owner_id"]
            eligible = confirmed_memory(db, self.namespace, current, owner)
            request.attributes["boss_memory_reference"] = {
                "memory_id": current["memory_id"], "version": current["version"],
                "confirmation_state": current["confirmation_state"], "eligible": eligible is not None,
                "confirmation_authority_checked": True,
            }
            return RuntimeContextBlock(source="boss-confirmed-memory", content=encode({
                "memory": {key: eligible[key] for key in ("memory_id", "version", "confirmation_state", "text")} if eligible is not None else None,
                "memory_version": current["version"],
            }))
