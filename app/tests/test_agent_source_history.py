import json
import multiprocessing
import os
import sqlite3
from dataclasses import asdict
from uuid import uuid4

import pytest
from aiohttp import web

from agent_source_history import AgentSourceHistory
from agent_source_history_routes import VALIDATOR
from agent_run_store import RunStore
from agent_recovery_preflight import AgentRecoveryPreflight
from boss_command_api import BossCommandAPI
from boss_knowledge_ingestion import revise
from boss_morning_inputs import MorningInputAPI
from business import checksum
from controls import ControlStore
from test_agent_run_result import setup_result


def revise_and_exit(path, payload):
    store = ControlStore(path)
    commands = BossCommandAPI(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        data = store.get(db, "ui-check", "initial", "snapshot")
        revise(commands, db, data, payload)
        os._exit(23)


def prepare_history(path):
    store, runs, results, sink = setup_result(path)
    commands = BossCommandAPI(store)
    create = {"client_request_id": "history-create", "source_id": "sim-doc-history-check", "title": "模拟会议资料", "author_contact_id": "finance-1", "published_at": "2020-01-01", "content": "模拟会议资料包含讨论事项、负责人和用于验证资料历史读取的完整原始正文。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.create", create)[0] == 200
    session_id = results.scope.sources.sessions.get_or_create("websocket:result-check").key
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        document = store.get(db, "ui-check", "document", create["source_id"])
        binding = store.get(db, "ui-check", "conversation_source_binding", session_id)
        binding["source_refs"] = [{"source_id": document["source_id"], "version": document["version"]}]
        binding["source_pins"] = [{**binding["source_refs"][0], "content_sha256": checksum(document)}]
        store.put(db, "ui-check", "conversation_source_binding", session_id, binding)
    proof = results.scope.prove("result-check", [create["source_id"]])
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", (json.dumps([create["source_id"]]), json.dumps(asdict(proof)), sink.config.run_id))
    result = results.record(sink, "history-result", 1, "会议资料技术记录", [{"source_id": create["source_id"], "locator": "讨论事项"}])
    return store, runs, results, sink, commands, create, result, session_id


def test_history_uses_recorded_source_revision_and_current_scope(tmp_path):
    store, runs, results, sink, commands, create, result, session_id = prepare_history(tmp_path)
    service = AgentSourceHistory(runs, results.scope)
    with runs.connect() as db:
        db.execute("BEGIN")
        current = service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1")
        assert current["historical"] is False and current["content"] == create["content"]
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="同一数据库事务"):
            service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1")
    revision = {**create, "client_request_id": "history-revise", "expected_version": "1", "content": "模拟会议资料已经更新，包含新的讨论事项、负责人以及当前版本的完整原文。"}
    process = multiprocessing.get_context("spawn").Process(target=revise_and_exit, args=(store.path, revision))
    process.start()
    process.join(60)
    assert process.exitcode == 23
    with store.connect() as db:
        assert store.get(db, "ui-check", "document", create["source_id"])["version"] == "1"
        original = store.get(db, "ui-check", "document", create["source_id"])
        saved = store.get(db, "ui-check", "document_revision", create["source_id"] + ":v1")
        assert saved == original
    assert commands.execute("MAINTAINER", "boss.knowledge.source.revise", revision)[0] == 200
    assert commands.execute("MAINTAINER", "boss.knowledge.source.revise", revision)[0] == 200
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPConflict):
            service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = store.get(db, "ui-check", "document", create["source_id"])
        binding = store.get(db, "ui-check", "conversation_source_binding", session_id)
        binding["source_refs"] = [{"source_id": current["source_id"], "version": current["version"]}]
        binding["source_pins"] = [{**binding["source_refs"][0], "content_sha256": checksum(current)}]
        store.put(db, "ui-check", "conversation_source_binding", session_id, binding)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        read = service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1")
        VALIDATOR.validate(read)
        assert read["content"] == create["content"] and read["current_version"] == "2" and read["historical"] is True
        assert read["citations"] == [{"locator": "讨论事项", "locator_verification": "NOT_VERIFIED"}]
        assert service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1") == read
        with pytest.raises(web.HTTPNotFound):
            service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "2")
        with pytest.raises(web.HTTPNotFound):
            service.read_in_transaction(db, sink.config.run_id, str(uuid4()), create["source_id"], "1")
        with pytest.raises(web.HTTPForbidden):
            service.read_in_transaction(db, sink.config.run_id, result["event_id"], "finance-note", "1")
        db.execute("DELETE FROM objects WHERE namespace='ui-check' AND kind='document_revision' AND id=?", (create["source_id"] + ":v1",))
        with pytest.raises(web.HTTPNotFound) as error:
            service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1")
        assert error.value.text == "历史来源正文未保存"
        db.rollback()
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1") == read
    reopened = AgentSourceHistory(RunStore(runs.path, allow_migration=False), results.scope)
    with reopened.runs.connect() as db:
        db.execute("BEGIN")
        assert reopened.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1") == read
    store.hermes_source_sessions = results.scope.sources.sessions
    withdrawal = {"client_request_id": "history-withdraw", "source_id": create["source_id"], "expected_version": "2"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)[0] == 200
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises((web.HTTPGone, web.HTTPConflict)):
            service.read_in_transaction(db, sink.config.run_id, result["event_id"], create["source_id"], "1")


def test_result_retains_real_source_in_same_transaction(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    preflight = AgentRecoveryPreflight(store)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before = preflight.current_state_in_transaction(db)
        result = results.record_in_transaction(db, sink, "history-atomic", 1, "技术结果", [{"source_id": "finance-note", "locator": "第一节"}])
        original = store.get(db, "ui-check", "document", "finance-note")
        assert store.get(db, "ui-check", "document_revision", "finance-note:v1") == original
        assert runs.result_in_transaction(db, sink.config.run_id, 1) == result
        after = preflight.current_state_in_transaction(db)
        assert after["state_sha256"] != before["state_sha256"]
        assert after["restore_state"] == "BLOCKED"
        db.rollback()
    with runs.connect() as db:
        db.execute("BEGIN")
        assert runs.result_in_transaction(db, sink.config.run_id, 1) is None
        assert db.execute("SELECT 1 FROM objects WHERE namespace='ui-check' AND kind='document_revision' AND id='finance-note:v1'").fetchone() is None
    result = results.record(sink, "history-atomic", 1, "技术结果", [{"source_id": "finance-note", "locator": "第一节"}])
    assert results.record(sink, "history-atomic", 1, "技术结果", [{"source_id": "finance-note", "locator": "第一节"}]) == result
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind='document_revision' AND id='finance-note:v1'").fetchone() == (1,)


def test_history_reads_existing_document_history_from_actual_update(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    inputs = MorningInputAPI(store)
    request = {"date": "2026-10-24", "timezone": "Asia/Shanghai", "client_request_id": "history-coverage-create", "mode": "SIMULATED", "generator_version": "FC03-COVERAGE-1", "seed": 20261024, "expected_version": "0"}
    first = inputs.load("MAINTAINER", request)
    session_id = results.scope.sources.sessions.get_or_create("websocket:result-check").key
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        document = store.get(db, "ui-check", "document", first["source_id"])
        binding = store.get(db, "ui-check", "conversation_source_binding", session_id)
        binding["source_refs"] = [{"source_id": document["source_id"], "version": document["version"]}]
        binding["source_pins"] = [{**binding["source_refs"][0], "content_sha256": checksum(document)}]
        store.put(db, "ui-check", "conversation_source_binding", session_id, binding)
    proof = results.scope.prove("result-check", [first["source_id"]])
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", (json.dumps([first["source_id"]]), json.dumps(asdict(proof)), sink.config.run_id))
    result = results.record(sink, "coverage-result", 1, "覆盖资料技术记录", [{"source_id": first["source_id"], "locator": "regions"}])
    revised = inputs.load("MAINTAINER", {**request, "client_request_id": "history-coverage-revise", "expected_version": "1"})
    assert revised["version"] == "2"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = store.get(db, "ui-check", "document", first["source_id"])
        binding = store.get(db, "ui-check", "conversation_source_binding", session_id)
        binding["source_refs"] = [{"source_id": current["source_id"], "version": current["version"]}]
        binding["source_pins"] = [{**binding["source_refs"][0], "content_sha256": checksum(current)}]
        store.put(db, "ui-check", "conversation_source_binding", session_id, binding)
    history = AgentSourceHistory(runs, results.scope)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert store.get(db, "ui-check", "document_revision", first["source_id"] + ":v1") == document
        assert store.get(db, "ui-check", "document_history", first["source_id"] + ":1") == document
        assert history.read_in_transaction(db, sink.config.run_id, result["event_id"], first["source_id"], "1")["content"] == document["content"]
        db.execute("DELETE FROM objects WHERE namespace='ui-check' AND kind='document_revision' AND id=?", (first["source_id"] + ":v1",))
        assert history.read_in_transaction(db, sink.config.run_id, result["event_id"], first["source_id"], "1")["content"] == document["content"]
        db.rollback()
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM objects WHERE namespace='ui-check' AND kind='document_history' AND id=?", (first["source_id"] + ":1",))
        assert history.read_in_transaction(db, sink.config.run_id, result["event_id"], first["source_id"], "1")["content"] == document["content"]
        db.rollback()
