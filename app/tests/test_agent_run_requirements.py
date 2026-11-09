import asyncio
import sqlite3

import httpx
import pytest
from aiohttp import web

from agent_run_api import VALIDATORS, product_application
from agent_run_requirements import RunRequirements
from test_agent_run_dispatcher import services_for
from test_agent_run_result import setup_result


def test_requirements_schema_and_versioned_technical_records(tmp_path):
    _, runs, _, sink = setup_result(tmp_path)
    run_id = sink.config.run_id
    with runs.connect() as db:
        db.execute("BEGIN")
        assert RunRequirements.read_in_transaction(db, run_id, 1)["state"] == "UNAVAILABLE"
    RunRequirements(runs, allow_migration=True)
    RunRequirements(runs)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert RunRequirements.read_in_transaction(db, run_id, 1)["state"] == "PENDING_CONFIRMATION"
        RunRequirements.save_in_transaction(db, run_id, 1, "technical-create", ["TEXT", "PDF"])
        assert RunRequirements.read_in_transaction(db, run_id, 1)["required_outputs"] == ["TEXT", "PDF"]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE agent_run_requirements SET required_outputs='[]' WHERE run_id=?", (run_id,))
    runs.add_input(run_id, 1, "technical-input", "新的关注事项")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert RunRequirements.read_in_transaction(db, run_id, 2)["state"] == "PENDING_CONFIRMATION"
        with pytest.raises(ValueError, match="目标版本"):
            RunRequirements.save_in_transaction(db, run_id, 1, "technical-old", ["TEXT"])
        RunRequirements.save_in_transaction(db, run_id, 2, "technical-input", ["DOCX"])
        assert RunRequirements.read_in_transaction(db, run_id, 1)["required_outputs"] == ["TEXT", "PDF"]
        assert RunRequirements.read_in_transaction(db, run_id, 2)["required_outputs"] == ["DOCX"]
    runs.cancel(run_id, runs.read_run(run_id)["revision"])
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="目标版本"):
            RunRequirements.save_in_transaction(db, run_id, 2, "after-cancel", ["TEXT"])


def test_output_selection_validation():
    base = {"conversation_id": "chat", "goal": "目标", "selected_refs": [], "request_key": "key"}
    assert VALIDATORS["create"].is_valid({**base, "required_outputs": ["TEXT", "BRIEF", "SOURCE_LIST", "ACTION_DRAFT", "PDF", "BUSINESS_RECEIPT"]})
    assert VALIDATORS["create"].is_valid(base)
    for outputs in ([], ["TEXT", "TEXT"], ["UNKNOWN"], "PDF", ["PDF", {"type": "TEXT"}]):
        assert not VALIDATORS["create"].is_valid({**base, "required_outputs": outputs})
    assert VALIDATORS["inputs"].is_valid({"input": "补充", "expected_goal_revision": 1, "request_key": "key", "required_outputs": ["DOCX"]})


def test_unauthenticated_selection_request_rejected(tmp_path):
    services = services_for(tmp_path)
    RunRequirements(services.store, allow_migration=True)

    async def exercise():
        runner = web.AppRunner(product_application(services.recovery.channel, services.broker))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                base = "http://127.0.0.1:" + str(runner.addresses[0][1])
                payload = {"conversation_id": "chat", "goal": "目标", "selected_refs": [], "request_key": "key", "required_outputs": ["TEXT"]}
                assert (await client.post(base + "/api/v2/runs", json=payload)).status_code == 401
                assert (await client.post(base + "/api/v2/runs/unknown/inputs", json={"input": "补充", "expected_goal_revision": 1, "request_key": "input", "required_outputs": ["PDF"]})).status_code == 401
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
    with services.store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_run_requirements").fetchone() == (0,)
