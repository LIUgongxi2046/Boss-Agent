import hashlib
import json
from pathlib import Path

from filelock import FileLock
from jsonschema import Draft202012Validator

from agent_run_store import RunStore, utc_now
from business import checksum


VERSION = "upgrade2_run_requirements_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")
SCHEMA = json.loads((Path(__file__).parent.parent / "specs" / "agent-runs.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator({"$ref": "#/$defs/required_outputs", "$defs": SCHEMA["$defs"]})


class RunRequirements:
    def __init__(self, store, *, allow_migration=False):
        if not isinstance(store, RunStore):
            raise ValueError("需要运行存储")
        self.store = store
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            state = self.schema_state(db)
            if state:
                return
            if not allow_migration:
                raise ValueError("运行成果要求迁移尚未安装")
            source = MIGRATION.read_bytes()
            db.executescript("BEGIN IMMEDIATE;\n" + source.decode("utf-8"))
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, hashlib.sha256(source).hexdigest()))

    @staticmethod
    def schema_state(db):
        row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_run_requirements'").fetchone()
        if row is None and table is None:
            return False
        if row is None or table is None or row[0] != hashlib.sha256(MIGRATION.read_bytes()).hexdigest():
            raise ValueError("运行成果要求迁移不可核查")
        return True

    @staticmethod
    def read_in_transaction(db, run_id, goal_revision):
        if not db.in_transaction or type(goal_revision) is not int or goal_revision < 1:
            raise ValueError("成果要求读取需要当前事务和有效版本")
        if not RunRequirements.schema_state(db):
            return {"goal_revision": goal_revision, "state": "UNAVAILABLE", "required_outputs": None}
        row = db.execute("SELECT required_outputs,requirements_sha256 FROM agent_run_requirements WHERE run_id=? AND goal_revision=?", (run_id, goal_revision)).fetchone()
        if row is None:
            return {"goal_revision": goal_revision, "state": "PENDING_CONFIRMATION", "required_outputs": None}
        selected = json.loads(row[0])
        if not VALIDATOR.is_valid(selected) or checksum(selected) != row[1]:
            raise ValueError("成果要求内容不可核查")
        return {"goal_revision": goal_revision, "state": "CONFIRMED", "required_outputs": selected}

    @staticmethod
    def save_in_transaction(db, run_id, goal_revision, request_key, outputs):
        if not db.in_transaction or type(goal_revision) is not int or goal_revision < 1 or not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128 or not VALIDATOR.is_valid(outputs):
            raise ValueError("成果要求字段无效")
        if not RunRequirements.schema_state(db):
            raise ValueError("运行成果要求迁移尚未安装")
        run = db.execute("SELECT goal_revision,cancel_requested_at,status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[0] != goal_revision or run[1] is not None or run[2] not in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"}:
            raise ValueError("成果要求目标版本不可保存")
        encoded = json.dumps(outputs, ensure_ascii=False, separators=(",", ":"))
        db.execute("INSERT INTO agent_run_requirements VALUES (?,?,?,?,?,?)", (run_id, goal_revision, request_key, encoded, checksum(outputs), utc_now().isoformat()))
