import json


def latest_usage_snapshot_in_transaction(db, run_id):
    if not db.in_transaction:
        raise ValueError("用量快照读取需要事务")
    run = db.execute("SELECT parent_run_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None:
        raise ValueError("运行不存在")
    root = run_id
    seen = {run_id}
    while run is not None and run[0] is not None:
        root = run[0]
        if root in seen:
            raise ValueError("运行关系存在循环")
        seen.add(root)
        run = db.execute("SELECT parent_run_id FROM agent_runs WHERE run_id=?", (root,)).fetchone()
        if run is None:
            raise ValueError("根运行不存在")
    rows = db.execute(
        "WITH RECURSIVE lineage(run_id) AS ("
        " SELECT run_id FROM agent_runs WHERE run_id=?"
        " UNION SELECT r.run_id FROM agent_runs r JOIN lineage l ON r.parent_run_id=l.run_id"
        ") SELECT e.event_id,e.run_id,e.seq,e.payload FROM agent_run_events e JOIN lineage l ON l.run_id=e.run_id"
        " WHERE e.type='USAGE_RECORDED' ORDER BY e.rowid",
        (root,),
    ).fetchall()
    snapshots = []
    for event_id, event_run_id, seq, encoded in rows:
        payload = json.loads(encoded)
        if payload.get("usage_kind") != "CUMULATIVE_SNAPSHOT":
            continue
        revision = payload.get("snapshot_revision")
        if type(revision) is not int or revision < 1:
            raise ValueError("用量快照版本无效")
        if payload.get("root_run_id") != root or payload.get("snapshot_final") is not False:
            raise ValueError("用量快照根运行或终止状态无效")
        snapshots.append((revision, event_id, event_run_id, seq, payload))
    if not snapshots:
        return None
    revisions = [item[0] for item in snapshots]
    if len(set(revisions)) != len(revisions):
        raise ValueError("用量快照版本重复")
    revision, event_id, event_run_id, seq, payload = max(snapshots, key=lambda item: item[0])
    return {"event_id": event_id, "run_id": event_run_id, "seq": seq, "root_run_id": root,
            "snapshot_revision": revision, "snapshot_final": False,
            "requests_used": payload["requests_used"], "known_requests": payload["known_requests"],
            "request_limit": payload["request_limit"], "usage_state": payload["usage_state"],
            "known_total_tokens": payload["known_total_tokens"], "total_tokens": payload["total_tokens"],
            "cost": payload["cost"], "cost_state": payload["cost_state"], "currency": payload["currency"],
            "lease_epoch": payload["lease_epoch"]}


def usage_lineage_in_transaction(db, run_id):
    if not db.in_transaction:
        raise ValueError("用量来源读取需要事务")
    run = db.execute("SELECT parent_run_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None:
        raise ValueError("运行不存在")
    root = run_id
    seen = {run_id}
    while run is not None and run[0] is not None:
        root = run[0]
        if root in seen:
            raise ValueError("运行关系存在循环")
        seen.add(root)
        run = db.execute("SELECT parent_run_id FROM agent_runs WHERE run_id=?", (root,)).fetchone()
        if run is None:
            raise ValueError("根运行不存在")
    rows = db.execute(
        "WITH RECURSIVE lineage(run_id) AS ("
        " SELECT run_id FROM agent_runs WHERE run_id=?"
        " UNION SELECT r.run_id FROM agent_runs r JOIN lineage l ON r.parent_run_id=l.run_id"
        ") SELECT DISTINCT r.run_id,r.actor_id,r.space_id,r.conversation_id,r.selected_refs,r.scope_proof FROM lineage l JOIN agent_runs r ON r.run_id=l.run_id ORDER BY r.run_id",
        (root,),
    ).fetchall()
    return [{"run_id": item[0], "actor_id": item[1], "space_id": item[2], "conversation_id": item[3], "selected_refs": item[4], "scope_proof": item[5]} for item in rows]
