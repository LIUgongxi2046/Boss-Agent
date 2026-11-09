import json
from pathlib import Path

from aiohttp import web

from boss_memory_runtime import memory_adoption
from boss_simulation_api import _context
from business import checksum


def require_current_run_memory_in_transaction(db, store, run_id):
    main = db.execute("PRAGMA database_list").fetchone()
    if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != store.path.resolve():
        raise ValueError("运行记忆核查需要同一数据库事务")
    context = _context(db)
    namespace = context["namespace"]
    reference, eligible = memory_adoption(store, db, namespace)
    deletions = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='memory_deletion' LIMIT 1", (namespace,)).fetchone() is not None
    current, seen = run_id, set()
    while current is not None:
        if current in seen:
            raise ValueError("运行关系存在循环")
        seen.add(current)
        run = db.execute("SELECT actor_id,space_id,conversation_id,scope_proof,parent_run_id FROM agent_runs WHERE run_id=?", (current,)).fetchone()
        if run is None or (run[0], run[1]) != (context["owner_id"], namespace):
            raise ValueError("运行记忆身份不可核查")
        if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (namespace, current)).fetchone() is not None:
            raise web.HTTPConflict(text="运行记忆引用已经失效")
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_memory_adoption' AND id=?", (namespace, current)).fetchone()
        if row is None:
            if deletions:
                raise web.HTTPConflict(text="运行记忆来源缺少记录")
        else:
            marker = json.loads(row[0])
            proof = json.loads(run[3]) if run[3] is not None else None
            expected = {"owner_id": context["owner_id"], "namespace": namespace, "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"], "conversation_id": run[2], "scope_sha256": checksum(proof), "memory_reference": reference, "content_sha256": checksum(eligible) if eligible is not None else None}
            if proof is None or marker != expected:
                raise web.HTTPConflict(text="运行记忆引用已经变化")
        current = run[4]
