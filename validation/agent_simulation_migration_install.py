import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from filelock import FileLock

from agent_simulation_snapshot import SIMULATION_ROOT


MIGRATIONS = (
    ("upgrade2_001", "agent_schema_migrations"),
    ("upgrade2_artifact_goal_001", "agent_schema_migrations"),
    ("upgrade2_artifact_workspace_001", "agent_schema_migrations"),
    ("upgrade2_dispatch_receipts_001", "agent_schema_migrations"),
    ("upgrade2_run_requirements_001", "agent_schema_migrations"),
    ("upgrade2_run_method_selection_001", "agent_schema_migrations"),
    ("upgrade2_run_method_reselection_001", "agent_schema_migrations"),
    ("upgrade2_run_object_scope_001", "agent_schema_migrations"),
    ("upgrade2_artifact_brief_001", "agent_schema_migrations"),
    ("upgrade2_artifact_brief_cleanup_001", "agent_schema_migrations"),
    ("upgrade2_concurrency_001", "agent_schema_migrations"),
    ("upgrade2_tool_budget_001", "agent_schema_migrations"),
    ("hermes_budget_001", "agent_schema_migrations"),
    ("hermes_budget_002", "agent_schema_migrations"),
    ("hermes_process_evidence_001", "agent_schema_migrations"),
    ("hermes_vm_binding_001", "agent_schema_migrations"),
    ("hermes_cpu_budget_001", "agent_schema_migrations"),
    ("hermes_cpu_budget_002", "agent_schema_migrations"),
    ("hermes_cpu_budget_003", "agent_schema_migrations"),
    ("hermes_cpu_budget_004", "agent_schema_migrations"),
    ("hermes_cpu_budget_005", "agent_schema_migrations"),
    ("hermes_cpu_budget_006", "agent_schema_migrations"),
    ("hermes_cpu_budget_007", "agent_schema_migrations"),
    ("hermes_anchor_evidence_001", "agent_schema_migrations"),
    ("upgrade2_intents_001", "agent_schema_migrations"),
    ("upgrade2_business_receipts_001", "agent_schema_migrations"),
    ("upgrade2_chat_budget_001", "agent_schema_migrations"),
    ("hermes_schedule_001", "hermes_schedule_migrations"),
    ("hermes_schedule_002", "hermes_schedule_migrations"),
    ("hermes_schedule_003", "hermes_schedule_migrations"),
    ("upgrade2_inventory_001", "agent_schema_migrations"),
    ("upgrade2_legacy_inventory_001", "agent_schema_migrations"),
    ("upgrade2_legacy_links_001", "agent_schema_migrations"),
    ("upgrade2_plan_handover_001", "agent_schema_migrations"),
    ("upgrade2_schedule_inspection_001", "agent_schema_migrations"),
    ("upgrade2_schedule_stop_observation_001", "agent_schema_migrations"),
    ("upgrade2_schedule_occurrence_gate_001", "agent_schema_migrations"),
    ("upgrade2_recovery_checkpoint_001", "agent_schema_migrations"),
    ("upgrade2_simulation_snapshot_001", "agent_schema_migrations"),
    ("upgrade2_simulation_recovery_journal_001", "agent_schema_migrations"),
    ("upgrade2_simulation_deletion_baseline_001", "agent_schema_migrations"),
)
DEPENDENCIES = {
    "upgrade2_artifact_workspace_001": ("upgrade2_001",),
    "upgrade2_dispatch_receipts_001": ("upgrade2_001",),
    "upgrade2_artifact_brief_001": ("upgrade2_artifact_goal_001",),
    "upgrade2_artifact_brief_cleanup_001": ("upgrade2_artifact_brief_001",),
    "upgrade2_run_method_selection_001": ("upgrade2_001",),
    "upgrade2_run_method_reselection_001": ("upgrade2_run_method_selection_001",),
    "upgrade2_run_object_scope_001": ("upgrade2_001",),
    "upgrade2_business_receipts_001": ("upgrade2_run_requirements_001", "upgrade2_intents_001"),
    "hermes_budget_002": ("hermes_budget_001",),
    "hermes_process_evidence_001": ("upgrade2_concurrency_001",),
    "hermes_vm_binding_001": ("hermes_process_evidence_001",),
    "hermes_cpu_budget_001": ("hermes_vm_binding_001",),
    "hermes_cpu_budget_002": ("hermes_cpu_budget_001",),
    "hermes_cpu_budget_003": ("hermes_cpu_budget_002",),
    "hermes_cpu_budget_004": ("hermes_cpu_budget_003",),
    "hermes_cpu_budget_005": ("hermes_cpu_budget_004",),
    "hermes_cpu_budget_006": ("hermes_cpu_budget_005",),
    "hermes_cpu_budget_007": ("hermes_cpu_budget_006",),
    "hermes_anchor_evidence_001": ("hermes_process_evidence_001",),
    "hermes_schedule_002": ("hermes_schedule_001",),
    "hermes_schedule_003": ("hermes_schedule_002",),
    "upgrade2_legacy_links_001": ("upgrade2_legacy_inventory_001",),
    "upgrade2_schedule_stop_observation_001": ("upgrade2_schedule_inspection_001",),
    "upgrade2_simulation_snapshot_001": ("upgrade2_recovery_checkpoint_001",),
    "upgrade2_simulation_recovery_journal_001": ("upgrade2_simulation_snapshot_001",),
    "upgrade2_simulation_deletion_baseline_001": ("upgrade2_recovery_checkpoint_001",),
}
MIGRATION_DIR = Path(__file__).parent / "migrations"
REPLACEMENTS = {"upgrade2_artifact_brief_cleanup_001": {("trigger", "agent_artifact_briefs_no_delete")},
                "hermes_cpu_budget_006": {("trigger", "agent_concurrency_reservation_transition")}}


def _schema(db):
    return {(kind, name): sql for kind, name, sql in db.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL")}


def _catalog():
    result = []
    with closing(sqlite3.connect(":memory:")) as reference:
        for version, ledger in MIGRATIONS:
            source = (MIGRATION_DIR / (version + ".sql")).read_bytes()
            digest = hashlib.sha256(source).hexdigest()
            before = _schema(reference)
            reference.executescript(source.decode("utf-8"))
            after = _schema(reference)
            replacements = REPLACEMENTS.get(version, set())
            changed = {key for key, sql in before.items() if after.get(key) != sql}
            objects = {key: sql for key, sql in after.items() if key not in before or key in replacements}
            if not objects or changed != replacements or any(key not in before or key not in after for key in replacements):
                raise ValueError("迁移对象清单不可核查")
            result.append((version, ledger, source.decode("utf-8"), digest, objects))
    return result


def _prepare(db):
    catalog = _catalog()
    schema_version = db.execute("PRAGMA schema_version").fetchone()[0]
    data_version = db.execute("PRAGMA data_version").fetchone()[0]
    schema = _schema(db)
    installed = {}
    for ledger in ("agent_schema_migrations", "hermes_schedule_migrations"):
        if ("table", ledger) in schema:
            installed.update({(ledger, version): digest for version, digest in db.execute("SELECT version,sha256 FROM " + ledger)})
    known = {(ledger, version) for version, ledger, _, _, _ in catalog}
    if set(installed) - known:
        raise ValueError("存在未知迁移版本")
    effective = {}
    for version, ledger, _, digest, objects in catalog:
        if (ledger, version) in installed:
            effective.update(objects)
    for version, ledger, _, digest, objects in catalog:
        saved = installed.get((ledger, version))
        if saved is not None and saved != digest:
            raise ValueError("迁移版本摘要不符")
        if saved is not None:
            if any(schema.get(key) != effective[key] for key in objects):
                raise ValueError("已登记迁移对象不可核查")
            for dependency in DEPENDENCIES.get(version, ()):
                dependency_ledger = dict(MIGRATIONS)[dependency]
                if (dependency_ledger, dependency) not in installed:
                    raise ValueError("已登记迁移缺少依赖")
            if version != "upgrade2_001" and ("agent_schema_migrations", "upgrade2_001") not in installed:
                raise ValueError("已登记迁移缺少运行基础")
        elif any(key in schema for key in objects if key not in REPLACEMENTS.get(version, set())):
            raise ValueError("迁移对象缺少版本登记")
    if db.execute("PRAGMA integrity_check").fetchone() != ("ok",) or db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("迁移前数据库完整性不可核查")
    if db.execute("PRAGMA schema_version").fetchone()[0] != schema_version or db.execute("PRAGMA data_version").fetchone()[0] != data_version:
        raise ValueError("迁移前数据库已经变化")
    parts = ["BEGIN IMMEDIATE;", "CREATE TEMP TABLE migration_guard (ok INTEGER NOT NULL CHECK(ok=1));",
             f"INSERT INTO migration_guard SELECT schema_version={schema_version} FROM pragma_schema_version;",
             f"INSERT INTO migration_guard SELECT data_version={data_version} FROM pragma_data_version;"]
    pending = []
    for version, ledger, source, digest, _ in catalog:
        if (ledger, version) not in installed:
            pending.append(version)
            parts.extend((source, f"INSERT INTO {ledger} VALUES ('{version}', '{digest}');"))
    parts.extend(("INSERT INTO migration_guard SELECT count(*)=0 FROM pragma_foreign_key_check;",
                  "INSERT INTO migration_guard SELECT count(*)=1 AND min(integrity_check)='ok' FROM pragma_integrity_check;",
                  "DROP TABLE migration_guard;", "COMMIT;"))
    return "\n".join(parts), pending


def install_simulation_migrations(path):
    path = Path(path)
    root = SIMULATION_ROOT.resolve()
    if not path.is_absolute():
        raise ValueError("独立模拟业务数据库必须使用绝对路径")
    from application_paths import _reject_symlink_components
    _reject_symlink_components(path.parent)
    if path.is_symlink() or not path.is_file() or path.name != "business.sqlite" or not path.resolve().is_relative_to(root):
        raise ValueError("仅允许独立模拟业务数据库")
    path = path.resolve()
    with FileLock(str(path) + ".migration.lock", timeout=10), FileLock(str(path) + ".schedule-migration.lock", timeout=10), closing(sqlite3.connect(path, timeout=10)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        script, pending = _prepare(db)
        db.executescript(script)
        return {"installed": pending, "versions": [version for version, _ in MIGRATIONS]}
