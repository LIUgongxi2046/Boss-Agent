import hashlib
import json
from pathlib import Path

from filelock import FileLock

from agent_run_method_selection import AgentRunMethodSelection
from agent_run_store import RunStore
from business import checksum


VERSION = "upgrade2_artifact_goal_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class AgentArtifactGoal:
    def __init__(self, runs, *, allow_migration=False):
        if not isinstance(runs, RunStore):
            raise ValueError("成果目标需要运行数据库")
        self.runs = runs
        with FileLock(str(runs.path) + ".migration.lock", timeout=10), runs.connect() as db:
            if self.schema_state(db):
                return
            if not allow_migration:
                raise ValueError("成果目标迁移尚未安装")
            db.executescript("BEGIN IMMEDIATE;\n" + MIGRATION.read_text(encoding="utf-8"))
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, hashlib.sha256(MIGRATION.read_bytes()).hexdigest()))

    @staticmethod
    def schema_state(db):
        row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_goals'").fetchone()
        if row is None and table is None:
            return False
        if row is None or table is None or row[0] != hashlib.sha256(MIGRATION.read_bytes()).hexdigest():
            raise ValueError("成果目标迁移不可核查")
        return True

    @staticmethod
    def record_in_transaction(db, run_id, artifact_id):
        if not db.in_transaction:
            raise ValueError("成果目标保存需要当前事务")
        if not AgentArtifactGoal.schema_state(db):
            return
        run = db.execute("SELECT goal_revision,applied_goal_revision,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[0] != run[1] or run[2:] != ("RUNNING", None):
            raise ValueError("成果目标版本不可保存")
        goal, scope = AgentRunMethodSelection._goal_snapshot(db, run_id, run[0])
        events = db.execute("SELECT event_id,payload FROM agent_run_events WHERE run_id=? AND type='ARTIFACT_CANDIDATE' AND json_extract(payload,'$.artifact_id')=?", (run_id, artifact_id)).fetchall()
        artifact = db.execute("SELECT version,media_type,sha256 FROM agent_artifacts WHERE artifact_id=? AND run_id=?", (artifact_id, run_id)).fetchone()
        if len(events) != 1 or artifact is None or json.loads(events[0][1]) != {"artifact_id": artifact_id, "version": artifact[0], "media_type": artifact[1], "sha256": artifact[2]}:
            raise ValueError("成果事件不可核查")
        db.execute("INSERT INTO agent_artifact_goals VALUES (?,?,?,?,?,?)", (artifact_id, run_id, run[0], checksum(goal), scope, events[0][0]))

    @staticmethod
    def read_in_transaction(db, record):
        if not db.in_transaction:
            raise ValueError("成果目标读取需要当前事务")
        if not AgentArtifactGoal.schema_state(db):
            return None
        row = db.execute("SELECT run_id,goal_revision,goal_sha256,scope_sha256,event_id FROM agent_artifact_goals WHERE artifact_id=?", (record["artifact_id"],)).fetchone()
        if row is None:
            return None
        goal, scope = AgentRunMethodSelection._goal_snapshot(db, row[0], row[1], allow_historical=True)
        event = db.execute("SELECT type,payload,seq FROM agent_run_events WHERE run_id=? AND event_id=?", (row[0], row[4])).fetchone()
        expected = {"artifact_id": record["artifact_id"], "version": record["version"], "media_type": record["media_type"], "sha256": record["sha256"]}
        count = db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='ARTIFACT_CANDIDATE' AND json_extract(payload,'$.artifact_id')=?", (row[0], record["artifact_id"])).fetchone()[0]
        if row[0] != record["run_id"] or row[2] != checksum(goal) or row[3] != scope or event is None or count != 1 or event[0] != "ARTIFACT_CANDIDATE" or json.loads(event[1]) != expected:
            raise ValueError("成果目标记录不可核查")
        for input_row in db.execute("SELECT applied_event_id FROM agent_run_inputs WHERE run_id=? AND goal_revision<=? ORDER BY input_seq", (row[0], row[1])).fetchall():
            applied = db.execute("SELECT seq FROM agent_run_events WHERE run_id=? AND event_id=?", (row[0], input_row[0])).fetchone()
            if applied is None or applied[0] >= event[2]:
                raise ValueError("成果目标事件顺序不可核查")
        return row[1]
