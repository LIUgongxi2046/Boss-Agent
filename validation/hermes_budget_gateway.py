import hmac
import hashlib
import json
import secrets
import sqlite3
import uuid
from pathlib import Path

import httpx
from aiohttp import web
from httpx_sse import aconnect_sse
from sse_starlette.sse import ServerSentEvent
from filelock import FileLock

from hermes_bridge import EngineEventSink


VERSION_002 = "hermes_budget_002"
MIGRATION_002 = Path(__file__).parent / "migrations" / (VERSION_002 + ".sql")


class BudgetStore:
    def __init__(self, path: Path, run_id: str, request_limit: int):
        if not run_id or isinstance(request_limit, bool) or not isinstance(request_limit, int) or request_limit <= 0:
            raise ValueError("运行编号与请求额度无效")
        self.path, self.run_id, self.request_limit = Path(path), run_id, request_limit
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("CREATE TABLE IF NOT EXISTS budgets (run_id TEXT PRIMARY KEY, request_limit INTEGER NOT NULL CHECK(request_limit > 0))")
            db.execute("CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, state TEXT NOT NULL, usage TEXT, FOREIGN KEY(run_id) REFERENCES budgets(run_id))")
            db.execute("INSERT OR IGNORE INTO budgets VALUES (?, ?)", (run_id, request_limit))
            if db.execute("SELECT request_limit FROM budgets WHERE run_id=?", (run_id,)).fetchone()[0] != request_limit:
                raise ValueError("已保存的运行额度不匹配")

    def reserve(self):
        request_id = str(uuid.uuid4())
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT COUNT(*) FROM requests WHERE run_id=?", (self.run_id,)).fetchone()[0]
            if used >= self.request_limit:
                raise web.HTTPTooManyRequests(text="request budget exhausted")
            db.execute("INSERT INTO requests VALUES (?, ?, 'UNKNOWN', NULL)", (request_id, self.run_id))
        return request_id

    def complete(self, request_id, usage):
        with sqlite3.connect(self.path, timeout=30) as db:
            result = db.execute("UPDATE requests SET state='COMPLETED', usage=? WHERE run_id=? AND request_id=? AND state='UNKNOWN'", (json.dumps(usage) if usage is not None else None, self.run_id, request_id))
            if result.rowcount != 1:
                raise RuntimeError("请求预留状态无效")

    def usage_report(self):
        with sqlite3.connect(self.path, timeout=30) as db:
            rows = db.execute("SELECT request_id,state,usage FROM requests WHERE run_id=? ORDER BY rowid", (self.run_id,)).fetchall()
        return self._report(rows)

    def _report(self, rows):
        requests = []
        known_tokens = 0
        known_requests = 0
        unknown_requests = 0
        for request_id, state, raw_usage in rows:
            usage = json.loads(raw_usage) if raw_usage is not None else None
            total = usage.get("total_tokens") if isinstance(usage, dict) else None
            valid = state == "COMPLETED" and not isinstance(total, bool) and isinstance(total, int) and total >= 0
            if valid:
                known_requests += 1
                known_tokens += total
            else:
                unknown_requests += 1
            requests.append({"request_id": request_id, "state": state, "usage": usage,
                             "usage_state": "KNOWN" if valid else "UNKNOWN",
                             "total_tokens": total if valid else None})
        used = len(rows)
        if used == 0:
            usage_state = "EMPTY"
        elif unknown_requests == 0:
            usage_state = "COMPLETE"
        elif known_requests:
            usage_state = "PARTIAL"
        else:
            usage_state = "UNKNOWN"
        return {"run_id": self.run_id, "root_run_id": self.run_id, "request_limit": self.request_limit, "requests_used": used,
                "remaining_requests": max(0, self.request_limit - used),
                "request_limit_reached": used >= self.request_limit,
                "known_requests": known_requests, "unknown_requests": unknown_requests,
                "usage_state": usage_state,
                "known_total_tokens": known_tokens, "total_tokens": known_tokens if unknown_requests == 0 else None,
                "cost": None, "cost_state": "UNKNOWN", "currency": None, "requests": requests}


class RunBoundBudgetStore(BudgetStore):
    def __init__(self, sink, *, allow_migration=False):
        if not isinstance(sink, EngineEventSink):
            raise ValueError("模型预算需要有效的运行入口")
        self.sink = sink
        self.path = sink.store.path
        migration = Path(__file__).parent / "migrations/hermes_budget_001.sql"
        script = migration.read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(self.path) + ".migration.lock", timeout=10):
            with sink.store.connect() as db:
                row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("hermes_budget_001",)).fetchone()
                if row is None:
                    existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('hermes_model_budgets','hermes_model_requests')").fetchone()
                    if existing is not None or not allow_migration:
                        raise ValueError("模型预算迁移尚未完成或已有未登记的表")
                    db.executescript("BEGIN IMMEDIATE;\n" + script + "\nINSERT INTO agent_schema_migrations VALUES ('hermes_budget_001', '" + digest + "');\nCOMMIT;")
                elif row[0] != digest:
                    raise ValueError("模型预算迁移摘要不符")
            extra = MIGRATION_002.read_text(encoding="utf-8")
            extra_digest = hashlib.sha256(extra.encode("utf-8")).hexdigest()
            with sink.store.connect() as db:
                row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION_002,)).fetchone()
                if row is None:
                    existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_usage_revisions'").fetchone()
                    if existing is not None or not allow_migration:
                        raise ValueError("用量版本迁移尚未完成或已有未登记的表")
                    db.executescript("BEGIN IMMEDIATE;\n" + extra + "\nINSERT INTO agent_schema_migrations VALUES ('" + VERSION_002 + "', '" + extra_digest + "');\nCOMMIT;")
                elif row[0] != extra_digest:
                    raise ValueError("用量版本迁移摘要不符")
        with sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sink.store._require_lease(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)
            root = sink.store.require_active_lineage(db, sink.config.run_id)
            existing = db.execute("SELECT request_limit FROM hermes_model_budgets WHERE root_run_id=?", (root,)).fetchone()
            if existing is None:
                if root != sink.config.run_id:
                    raise ValueError("根运行尚未配置模型预算")
                db.execute("INSERT INTO hermes_model_budgets VALUES (?, ?)", (root, sink.config.request_limit))
            elif existing[0] != sink.config.request_limit:
                raise ValueError("已保存的运行额度不匹配")
        self.run_id, self.request_limit = root, sink.config.request_limit
        self.authority = None

    def bind_authority(self, authority):
        from hermes_run_authority import HermesRunAuthority
        if not isinstance(authority, HermesRunAuthority) or authority.sink is not self.sink or self.authority is not None:
            raise ValueError("模型预算与运行授权不匹配")
        self.authority = authority

    def reserve(self):
        request_id = str(uuid.uuid4())
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self.authority is not None:
                self.authority.require_in_transaction(db)
            from hermes_source_invalidation import require_source_cleanup_complete
            require_source_cleanup_complete(db, self.sink.config.run_id)
            self.sink.store._require_lease(db, self.sink.config.run_id, self.sink.lease_owner, self.sink.config.lease_epoch)
            root = self.sink.store.require_active_lineage(db, self.sink.config.run_id)
            status = db.execute("SELECT status FROM agent_runs WHERE run_id=?", (self.sink.config.run_id,)).fetchone()
            if root != self.run_id or status is None or status[0] != "RUNNING":
                raise ValueError("模型请求的运行关系或状态无效")
            used = db.execute("SELECT COUNT(*) FROM hermes_model_requests WHERE root_run_id=?", (root,)).fetchone()[0]
            if used >= self.request_limit:
                raise web.HTTPTooManyRequests(text="request budget exhausted")
            db.execute("INSERT INTO hermes_model_requests VALUES (?, ?, ?, ?, 'UNKNOWN', NULL)", (request_id, root, self.sink.config.run_id, self.sink.config.lease_epoch))
        return request_id

    def complete(self, request_id, usage):
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.sink.store._require_lease(db, self.sink.config.run_id, self.sink.lease_owner, self.sink.config.lease_epoch)
            if self.sink.store.require_active_lineage(db, self.sink.config.run_id) != self.run_id:
                raise ValueError("模型请求的运行关系无效")
            if self.authority is not None:
                self.authority.require_in_transaction(db)
            result = db.execute("UPDATE hermes_model_requests SET state='COMPLETED', usage=? WHERE root_run_id=? AND run_id=? AND lease_epoch=? AND request_id=? AND state='UNKNOWN'", (json.dumps(usage, allow_nan=False) if usage is not None else None, self.run_id, self.sink.config.run_id, self.sink.config.lease_epoch, request_id))
            if result.rowcount != 1:
                raise RuntimeError("请求预留状态无效")

    def peek_usage_report(self):
        with self.sink.store.connect() as db:
            rows = db.execute("SELECT request_id,state,usage FROM hermes_model_requests WHERE root_run_id=? ORDER BY rowid", (self.run_id,)).fetchall()
        return self._report(rows)

    def usage_report(self):
        return self.peek_usage_report()

    def _require_usage_lineage(self, db):
        current = self.sink.config.run_id
        seen = set()
        identity = None
        canceled_lineage = False
        while current is not None:
            if current in seen:
                raise ValueError("运行关系存在循环")
            seen.add(current)
            row = db.execute("SELECT parent_run_id,actor_id,space_id,status,cancel_requested_at,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (current,)).fetchone()
            if row is None:
                raise ValueError("运行或父运行不存在")
            if identity is None:
                identity = row[1:3]
            if row[1:3] != identity:
                raise ValueError("父子运行主体或空间不一致")
            self.sink.store._require_lease(db, current, row[5], row[6])
            active = row[3] in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"} and row[4] is None
            canceled = row[3] in {"CANCEL_REQUESTED", "RECONCILING"} and row[4] is not None
            if not active and not canceled:
                raise ValueError("运行或父运行已经取消或不可执行")
            canceled_lineage = canceled_lineage or canceled
            root = current
            current = row[0]
        return root, canceled_lineage

    def record_usage_snapshot(self):
        origin = "usage-recorded:" + self.sink.config.run_id + ":" + str(self.sink.config.lease_epoch)
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.sink.store._require_lease(db, self.sink.config.run_id, self.sink.lease_owner, self.sink.config.lease_epoch)
            root, canceled = self._require_usage_lineage(db)
            if root != self.run_id:
                raise ValueError("用量快照的根运行不匹配")
            from hermes_source_invalidation import require_source_cleanup_complete
            require_source_cleanup_complete(db, self.sink.config.run_id)
            if self.authority is not None:
                if canceled:
                    self.authority.require_cancelled_usage_in_transaction(db)
                else:
                    state = db.execute("SELECT status FROM agent_runs WHERE run_id=?", (self.sink.config.run_id,)).fetchone()
                    if state is not None and state[0] in {"WAITING_INPUT", "WAITING_CONFIRMATION"}:
                        self.authority.require_waiting_in_transaction(db)
                    else:
                        self.authority.require_in_transaction(db)
            if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION_002,)).fetchone() != (hashlib.sha256(MIGRATION_002.read_bytes()).hexdigest(),):
                raise ValueError("用量版本迁移尚未完成")
            existing = db.execute("SELECT event_id, seq, type, occurred_at, trace_id, payload_version, payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=?", (self.sink.config.run_id, self.sink.config.lease_epoch, origin)).fetchone()
            if existing is not None:
                return self.sink.store._event(self.sink.config.run_id, existing)
            rows = db.execute("SELECT request_id,state,usage FROM hermes_model_requests WHERE root_run_id=? ORDER BY rowid", (self.run_id,)).fetchall()
            report = self._report(rows)
            row = db.execute("SELECT revision FROM hermes_usage_revisions WHERE root_run_id=?", (self.run_id,)).fetchone()
            revision = 1 if row is None else row[0] + 1
            if row is None:
                db.execute("INSERT INTO hermes_usage_revisions VALUES (?, ?)", (self.run_id, revision))
            else:
                db.execute("UPDATE hermes_usage_revisions SET revision=? WHERE root_run_id=?", (revision, self.run_id))
            payload = {"root_run_id": report["root_run_id"], "usage_kind": "CUMULATIVE_SNAPSHOT",
                       "snapshot_revision": revision, "snapshot_final": False, "lease_epoch": self.sink.config.lease_epoch,
                       "request_limit": report["request_limit"], "requests_used": report["requests_used"],
                       "known_requests": report["known_requests"], "usage_state": report["usage_state"],
                       "known_total_tokens": report["known_total_tokens"], "total_tokens": report["total_tokens"],
                       "cost": report["cost"], "cost_state": report["cost_state"], "currency": report["currency"]}
            return self.sink.store.append_event_in_transaction(db, self.sink.config.run_id, self.sink.lease_owner, self.sink.config.lease_epoch, origin, "USAGE_RECORDED", payload)


class ProviderGateway:
    def __init__(self, store: BudgetStore, capability: str, provider_key: str | None, *, offline=False):
        if type(offline) is not bool or not capability or not offline and not provider_key:
            raise ValueError("缺少入口凭据或 Provider 凭据")
        self.store, self.capability, self.provider_key = store, capability, provider_key
        self.offline = offline

    def require_current_authority(self):
        if isinstance(self.store, RunBoundBudgetStore) and self.store.authority is not None:
            self.store.authority.require()

    async def completions(self, request):
        if self.capability is None or not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + self.capability):
            raise web.HTTPUnauthorized()
        if self.offline:
            raise web.HTTPServiceUnavailable(text="模型入口离线不可用")
        payload = await request.json()
        if not isinstance(payload, dict) or payload.get("model") != "deepseek-flash" or not isinstance(payload.get("stream", False), bool):
            raise web.HTTPBadRequest(text="unsupported provider request")
        stream = payload.get("stream", False)
        if stream:
            options = payload.get("stream_options", {})
            if not isinstance(options, dict):
                raise web.HTTPBadRequest(text="invalid stream options")
            payload["stream_options"] = {**options, "include_usage": True}
        request_id = self.store.reserve()
        self.require_current_authority()
        headers = {"Authorization": "Bearer " + self.provider_key}
        async with httpx.AsyncClient(timeout=60) as client:
            if not stream:
                response = await client.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload)
                if response.is_error:
                    return web.json_response({"error": "PROVIDER_ERROR", "provider_status": response.status_code}, status=response.status_code)
                body = response.json()
                self.require_current_authority()
                self.store.complete(request_id, body.get("usage"))
                return web.json_response(body)
            async with aconnect_sse(client, "POST", "https://api.deepseek.com/chat/completions", headers=headers, json=payload) as source:
                if source.response.is_error:
                    return web.json_response({"error": "PROVIDER_ERROR", "provider_status": source.response.status_code}, status=source.response.status_code)
                output = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
                await output.prepare(request)
                usage = None
                finished = False
                async for event in source.aiter_sse():
                    self.require_current_authority()
                    if event.data == "[DONE]":
                        finished = True
                    else:
                        chunk = json.loads(event.data)
                        if chunk.get("usage") is not None:
                            usage = chunk["usage"]
                    await output.write(ServerSentEvent(data=event.data, event=event.event if event.event != "message" else None, id=event.id or None).encode())
                if not finished:
                    raise RuntimeError("Provider 流式响应未完成")
                self.store.complete(request_id, usage)
                await output.write_eof()
                return output

    def application(self):
        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.router.add_post("/chat/completions", self.completions)
        return app

    def close(self):
        self.capability = None
        self.provider_key = None


def create_run_provider_gateway(sink: EngineEventSink, provider_key: str):
    return ProviderGateway(RunBoundBudgetStore(sink), secrets.token_urlsafe(32), provider_key)
