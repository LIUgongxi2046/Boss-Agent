import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_page_api import BossPageAPI
from controls import ControlStore


def test_public_runtime_records_use_authenticated_technical_scope(tmp_path):
    store = ControlStore(tmp_path / "runtime-access.sqlite")
    store.initialize("ui-check")
    pages = BossPageAPI(store)
    for role in ("BOSS", "MAINTAINER"):
        status, result = pages.serve(role, "/api/boss/ui/runtime-records")
        assert status == 200
        assert result["projection"] == "runtime-records"
        assert result["source_type"] == "RUNTIME_RECORD"
        assert result["runs"] == [] and result["matched_count"] == 0
        assert result["private_body_available_here"] is False
        assert result["business_mutation_performed"] is False
        schema = json.loads((Path(__file__).resolve().parents[2] / "specs/runtime-records.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    assert pages.serve(None, "/api/boss/ui/runtime-records")[0] == 401
    assert pages.serve("contact-2", "/api/boss/ui/runtime-records")[0] == 401


def test_public_runtime_queries_reject_duplicates_unknown_fields_and_missing_runs(tmp_path):
    store = ControlStore(tmp_path / "runtime-query.sqlite")
    store.initialize("ui-check")
    pages = BossPageAPI(store)
    for query in ("provider=deepseek&provider=deepseek", "namespace=ui-check", "limit=101", "run_id=",
                  "cursor_run_id=missing", "started_from=not-a-date"):
        assert pages.serve("MAINTAINER", "/api/boss/ui/runtime-records", query)[0] == 400
    assert pages.serve("MAINTAINER", "/api/boss/ui/runtime-records", "run_id=unrecorded-run")[0] == 404
    assert pages.serve("MAINTAINER", "/api/boss/ui/runtime-records", "provider=deepseek&limit=1")[0] == 200
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='runtime_run'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','outbox')").fetchone()[0] == 0
