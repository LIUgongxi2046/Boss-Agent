import hashlib
import json
from pathlib import Path

from filelock import FileLock

from agent_run_store import RunStore, utc_now
from controls import ControlStore


VERSION = "upgrade2_inventory_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentMigrationInventory:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, ControlStore) or not Path(store.path).is_file():
            raise ValueError("需要已存在的业务数据库")
        self.store = store
        source = MIGRATION.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        RunStore(store.path, allow_migration=False)
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            installed = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_schema_migrations'").fetchone()
            if installed is None:
                raise ValueError("运行迁移尚未完成")
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("迁移清单版本摘要不符")
                return
            if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_migration_inventory'").fetchone() is not None:
                raise ValueError("迁移清单尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + source)
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, digest))

    def record_in_transaction(self, db, migration_version):
        if not db.in_transaction or not isinstance(migration_version, str) or not migration_version:
            raise ValueError("迁移清单需要当前事务和版本")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != Path(self.store.path).resolve():
            raise ValueError("迁移清单数据库不匹配")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (digest,):
            raise ValueError("迁移清单版本摘要不符")
        groups = {}
        for namespace, kind, identifier, body in db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id"):
            key = ("objects", namespace, kind)
            if key not in groups:
                groups[key] = {"count": 0, "sha256": hashlib.sha256()}
            encoded = json.dumps([namespace, kind, identifier, body], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            groups[key]["sha256"].update(len(encoded).to_bytes(8, "big"))
            groups[key]["sha256"].update(encoded)
            groups[key]["count"] += 1
        queries = (("spaces", "SELECT namespace,active,snapshot FROM spaces ORDER BY namespace"),
                   ("idempotency", "SELECT namespace,operation,key,digest,result FROM idempotency ORDER BY namespace,operation,key"),
                   ("audit", "SELECT namespace,id,operation,input,output,created_at FROM audit ORDER BY namespace,id"))
        for table, query in queries:
            for row in db.execute(query):
                key = (table, row[0], "")
                if key not in groups:
                    groups[key] = {"count": 0, "sha256": hashlib.sha256()}
                encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                groups[key]["sha256"].update(len(encoded).to_bytes(8, "big"))
                groups[key]["sha256"].update(encoded)
                groups[key]["count"] += 1
        inventory = [{"table": table, "namespace": namespace, "kind": kind, "count": group["count"], "sha256": group["sha256"].hexdigest()} for (table, namespace, kind), group in sorted(groups.items())]
        encoded = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        old = db.execute("SELECT input_digest,inventory_json FROM agent_migration_inventory WHERE migration_version=?", (migration_version,)).fetchone()
        if old is not None:
            if old != (digest, encoded):
                raise ValueError("迁移版本对应的业务资料已经变化")
            return {"input_digest": digest, "inventory": inventory, "created": False}
        db.execute("INSERT INTO agent_migration_inventory VALUES (?,?,?,?)", (migration_version, digest, encoded, utc_now().isoformat()))
        return {"input_digest": digest, "inventory": inventory, "created": True}
