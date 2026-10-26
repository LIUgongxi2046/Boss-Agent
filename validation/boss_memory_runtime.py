import asyncio

from aiohttp import web
from nanobot import RuntimeContextBlock

from business import checksum, encode, require
from boss_execution_scope import NAMESPACE
from boss_memory import confirmed_memory, current_memory


class MemoryContextInvalidated(asyncio.CancelledError):
    pass


def memory_adoption(store, db, namespace):
    current = current_memory(db, namespace)
    owner = store.get(db, namespace, "initial", "snapshot")["owner_id"]
    eligible = confirmed_memory(db, namespace, current, owner)
    reference = {
        "memory_id": current["memory_id"], "version": current["version"],
        "confirmation_state": current["confirmation_state"], "eligible": eligible is not None,
        "confirmation_authority_checked": True,
    } if current is not None else None
    return reference, eligible


def memory_context_source(reference):
    return "boss-confirmed-memory:" + checksum(reference)


def require_current_memory_reference(store, db, namespace, reference):
    if reference is None or reference["eligible"] is not True:
        return
    current = current_memory(db, namespace)
    owner = store.get(db, namespace, "initial", "snapshot")["owner_id"]
    eligible = confirmed_memory(db, namespace, current, owner)
    if eligible is None or any(eligible[key] != reference[key] for key in ("memory_id", "version")):
        raise MemoryContextInvalidated("OWNER_MEMORY_CONTEXT_CHANGED")


class OwnerMemoryContext:
    def __init__(self, store, namespace=NAMESPACE):
        self.store = store
        self.namespace = namespace

    async def __call__(self, request):
        require(request.sender_id == "boss-1", "记忆上下文只允许本人采用", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, self.namespace)
            reference, eligible = memory_adoption(self.store, db, self.namespace)
            request.attributes["boss_memory_reference"] = reference
            return RuntimeContextBlock(source=memory_context_source(reference), content=encode({
                "memory": {key: eligible[key] for key in ("memory_id", "version", "confirmation_state", "text")} if eligible is not None else None,
                "memory_version": reference["version"] if reference else None,
            }))
