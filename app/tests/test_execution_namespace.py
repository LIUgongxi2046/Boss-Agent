import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_dataset_generator import GENERATOR_VERSION, RELATIONSHIP_VERSION
from boss_execution_scope import validate_namespace
from boss_v7_datasets import DatasetWorkspace
from controls import ControlStore


def test_generated_space_uses_current_services_in_a_new_process(tmp_path):
    store = ControlStore(tmp_path / "spaces.sqlite")
    store.initialize("ui-check")
    api = BossCommandAPI(store)
    generation_request_id = str(uuid4())
    status, receipt = api.execute("MAINTAINER", "boss.technical.datasets.generate", {
        "client_request_id": generation_request_id, "seed": 20261026, "scale": "MEDIUM", "period_start": "2026-09", "period_end": "2026-10",
        "generator_version": GENERATOR_VERSION, "relationship_version": RELATIONSHIP_VERSION,
    })
    assert status == 200, receipt
    identifier = receipt["result"]["dataset_id"]
    workspace = DatasetWorkspace(store)
    target = "execution-" + str(uuid4())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before = db.execute("SELECT kind,id,body FROM objects WHERE namespace='ui-check' ORDER BY kind,id").fetchall()
        staged = workspace.stage_execution(db, identifier, "1", target, "ui-check")
        assert staged["state"] == "PREPARED"
        assert db.execute("SELECT namespace FROM spaces WHERE active=1").fetchall() == [("ui-check",)]
        switched = workspace.commit_execution(db, target, "ui-check", staged["facts_sha256"])
        assert switched["state"] == "PENDING_RUNTIME"
    assert api.execute("MAINTAINER", "boss.technical.datasets.validate", {
        "client_request_id": str(uuid4()), "dataset_id": identifier, "expected_dataset_version": "1",
    })[0] == 409
    environment = {**os.environ, "BOSS_EXECUTION_NAMESPACE": target}
    result = subprocess.run([sys.executable, str(ROOT / "app/tests/helpers/namespace_runtime_probe.py"), str(store.path), target, identifier, generation_request_id],
                            env=environment, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["namespace"] == target and observed["interfaces"] == 14
    assert observed["native_run_id"]
    with store.connect() as db:
        assert before == db.execute("SELECT kind,id,body FROM objects WHERE namespace='ui-check' ORDER BY kind,id").fetchall()
        assert db.execute("SELECT namespace FROM spaces WHERE active=1").fetchall() == [(target,)]
        assert store.get(db, target, "memory", "current")["version"] == "1"
        assert store.get(db, "ui-check", "memory", "current")["version"] == "1"
        with pytest.raises(web.HTTPConflict):
            workspace.commit_execution(db, target, "ui-check", staged["facts_sha256"])


@pytest.mark.parametrize("value", ["", "../outside", "dataset-catalog", "dataset-candidate:abc", "space/name", "无效", "a" * 161])
def test_instance_namespace_rejects_non_execution_identifiers(value):
    with pytest.raises(ValueError):
        validate_namespace(value)
