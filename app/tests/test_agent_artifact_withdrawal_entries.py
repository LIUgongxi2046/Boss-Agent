import json
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from agent_artifacts import ArtifactPreparation
from agent_artifact_withdrawal import propagate_domain_source_withdrawal_in_transaction
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_command_api import BossCommandAPI
from boss_memory_sessions import MemorySessionManager
from boss_simulation_api import _context
from boss_supply_quality import IMPORT_ACTION, WITHDRAW_ACTION, SupplyQualityAPI
from business import checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from test_agent_artifacts import series_prepared


def artifact_series(store, tmp_path, source_id, prefix):
    sessions = MemorySessionManager(tmp_path / ("workspace-" + prefix), business_store=store, sessions_root=tmp_path / ("sessions-" + prefix))
    chat_id = "entry-" + prefix
    session = sessions.get_or_create("websocket:" + chat_id)
    sessions.save(session, fsync=True)
    scope = RunScopeService(store, sessions, "ui-check")
    with store.connect() as db:
        context = _context(db)
        document = store.get(db, "ui-check", "document", source_id)
        pin = {"source_id": source_id, "version": document["version"], "content_sha256": checksum(document)}
        binding = {key: context[key] for key in ("namespace", "owner_id", "dataset_id", "dataset_version")}
        binding.update({"chat_id": chat_id, "session_id": session.key, "native_session_created_at": session.created_at.isoformat(),
                        "binding_id": "entry-binding-" + prefix, "context_version": "1",
                        "source_refs": [{"source_id": source_id, "version": document["version"]}], "source_pins": [pin]})
        store.put(db, "ui-check", "conversation_source_binding", session.key, binding)
    proof = scope.prove(chat_id, [source_id])
    runs = RunStore(store.path)
    run_id = runs.create_run(proof.owner_id, proof.namespace, "entry-create-" + prefix, "entry-digest-" + prefix)
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?",
                   (chat_id, "入口成果传播检查", json.dumps([source_id]), json.dumps(asdict(proof)), run_id))
    lease = runs.acquire_queued_for_execution(run_id, 0, "entry-worker", 60)
    runs.configure_file_budget(run_id, "entry-worker", lease["epoch"], 4, 1000000)
    gate = EngineEventSink(runs, EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 2), "entry-worker")
    workspace = tmp_path / ("artifacts-" + prefix)
    workspace.mkdir()
    preparation = ArtifactPreparation(store, workspace, run_gate=gate, scope_service=scope, max_files=4, max_bytes=1000000)
    first = preparation.create_meeting_brief(run_id, [source_id], request_key=prefix + "-v1", format_name="MARKDOWN")
    second = preparation.create_meeting_brief(run_id, [source_id], request_key=prefix + "-v2", format_name="MARKDOWN",
                                              previous_artifact_id=first["artifact_id"], expected_version=1)
    return runs, run_id, first, second


def test_knowledge_entry_commits_series_revocation_and_duplicate(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    created = {"client_request_id": "entry-knowledge-create", "source_id": "sim-doc-entry-knowledge", "title": "模拟资料",
               "author_contact_id": "finance-1", "published_at": "2026-10-22",
               "content": "这是用于入口成果传播检查的模拟资料正文，包含足够长度的说明内容。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.create", created)[0] == 200
    _, _, first, second = artifact_series(store, tmp_path, created["source_id"], "knowledge")
    withdrawal = {"client_request_id": "entry-knowledge-withdraw", "source_id": created["source_id"], "expected_version": "1"}
    first_result = commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)
    second_result = commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)
    assert first_result == second_result and first_result[0] == 200
    with store.connect() as db:
        rows = dict(db.execute("SELECT artifact_id,status FROM agent_artifacts").fetchall())
        assert rows == {first["artifact_id"]: "REVOKED", second["artifact_id"]: "REVOKED"}
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM objects WHERE kind='source_withdrawal_event'").fetchone() == (1,)


def add_title(store, source_id):
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", source_id)
        document["title"] = "模拟外部资料"
        store.put(db, "ui-check", "document", source_id, document)
        for binding_id, body in db.execute("SELECT id,body FROM objects WHERE namespace='ui-check' AND kind='external_record_binding'").fetchall():
            binding = json.loads(body)
            changed = False
            for reference in binding["sources"]:
                if reference["source_id"] == source_id:
                    reference.update(version=document["version"], source_sha256=checksum(document))
                    changed = True
            if changed:
                store.put(db, "ui-check", "external_record_binding", binding_id, binding)


def test_supply_entry_commits_series_revocation_and_duplicate(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    supply = SupplyQualityAPI(store)
    data = yaml.safe_load((Path(__file__).resolve().parents[2] / "data/simulation/supply-quality-v1.yaml").read_text())
    assert supply.execute("MAINTAINER", IMPORT_ACTION, data["initial_request"])["state"] == "SUCCESS"
    with store.connect() as db:
        record = store.get(db, "ui-check", "inventory_lot", "sim-stock-available-1")
    add_title(store, record["source_id"])
    _, _, first, second = artifact_series(store, tmp_path, record["source_id"], "supply")
    withdrawal = {"client_request_id": "entry-supply-withdraw", "entity_type": "inventory_lot",
                  "record_id": "sim-stock-available-1", "expected_version": "1", "reason": "模拟来源撤销"}
    first_result = supply.execute("MAINTAINER", WITHDRAW_ACTION, withdrawal)
    second_result = supply.execute("MAINTAINER", WITHDRAW_ACTION, withdrawal)
    assert first_result == second_result and first_result["record_state"] == "WITHDRAWN"
    with store.connect() as db:
        rows = dict(db.execute("SELECT artifact_id,status FROM agent_artifacts").fetchall())
        assert rows == {first["artifact_id"]: "REVOKED", second["artifact_id"]: "REVOKED"}
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM objects WHERE kind='source_withdrawal_event'").fetchone() == (1,)


def test_control_entry_failure_leaves_no_partial_update(series_prepared):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="failure-v1", format_name="MARKDOWN")
    second = service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="failure-v2", format_name="MARKDOWN",
                                         previous_artifact_id=first["artifact_id"], expected_version=1)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "simulation-meeting-material")
        db.execute("DELETE FROM agent_schema_migrations WHERE version='upgrade2_001'")
    with pytest.raises(ValueError, match="成果升级表状态不可核查"):
        store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": document["version"]})
    with store.connect() as db:
        assert store.get(db, "ui-check", "document", "simulation-meeting-material").get("withdrawn") is not True
        assert db.execute("SELECT count(*) FROM objects WHERE kind='source_withdrawal_event'").fetchone() == (0,)
        rows = dict(db.execute("SELECT artifact_id,status FROM agent_artifacts").fetchall())
        assert rows == {first["artifact_id"]: "VERIFIED", second["artifact_id"]: "VERIFIED"}
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (0,)


def test_knowledge_entry_failure_leaves_no_partial_update(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    created = {"client_request_id": "entry-knowledge-failure-create", "source_id": "sim-doc-entry-failure", "title": "模拟资料",
               "author_contact_id": "finance-1", "published_at": "2026-10-22",
               "content": "这是用于入口失败检查的模拟资料正文，包含足够长度的说明内容。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.create", created)[0] == 200
    _, _, first, second = artifact_series(store, tmp_path, created["source_id"], "knowledge-failure")
    with store.connect() as db:
        db.execute("DELETE FROM agent_schema_migrations WHERE version='upgrade2_001'")
    withdrawal = {"client_request_id": "entry-knowledge-failure-withdraw", "source_id": created["source_id"], "expected_version": "1"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)[0] == 400
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", created["source_id"])
        assert document.get("withdrawn") is not True and document["version"] == "1"
        assert db.execute("SELECT count(*) FROM objects WHERE kind='source_withdrawal_event'").fetchone() == (0,)
        rows = dict(db.execute("SELECT artifact_id,status FROM agent_artifacts").fetchall())
        assert rows == {first["artifact_id"]: "VERIFIED", second["artifact_id"]: "VERIFIED"}
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (0,)


def test_supply_entry_failure_leaves_no_partial_update(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    supply = SupplyQualityAPI(store)
    data = yaml.safe_load((Path(__file__).resolve().parents[2] / "data/simulation/supply-quality-v1.yaml").read_text())
    assert supply.execute("MAINTAINER", IMPORT_ACTION, data["initial_request"])["state"] == "SUCCESS"
    with store.connect() as db:
        record = store.get(db, "ui-check", "inventory_lot", "sim-stock-available-1")
    add_title(store, record["source_id"])
    _, _, first, second = artifact_series(store, tmp_path, record["source_id"], "supply-failure")
    with store.connect() as db:
        db.execute("DELETE FROM agent_schema_migrations WHERE version='upgrade2_001'")
    withdrawal = {"client_request_id": "entry-supply-failure-withdraw", "entity_type": "inventory_lot",
                  "record_id": "sim-stock-available-1", "expected_version": "1", "reason": "模拟来源撤销"}
    with pytest.raises(ValueError, match="成果升级表状态不可核查"):
        supply.execute("MAINTAINER", WITHDRAW_ACTION, withdrawal)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", record["source_id"])
        assert document.get("withdrawn") is not True
        assert db.execute("SELECT count(*) FROM objects WHERE kind='source_withdrawal_event'").fetchone() == (0,)
        rows = dict(db.execute("SELECT artifact_id,status FROM agent_artifacts").fetchall())
        assert rows == {first["artifact_id"]: "VERIFIED", second["artifact_id"]: "VERIFIED"}
        assert db.execute("SELECT count(*) FROM agent_artifact_revocations").fetchone() == (0,)


def test_control_entry_on_old_database_records_event_without_artifacts(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
    assert store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": document["version"]})["withdrawn"] is True
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='source_withdrawal_event'").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='agent_artifacts'").fetchone() == (0,)
        db.execute("BEGIN IMMEDIATE")
        result = propagate_domain_source_withdrawal_in_transaction(store, db, "finance-note")
        assert result["artifact_state"] == "NOT_INSTALLED" and result["affected"] == []
