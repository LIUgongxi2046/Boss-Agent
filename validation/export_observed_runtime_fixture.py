import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    evidence_root = args.evidence_root.resolve(strict=True)
    assert evidence_root.is_relative_to(ROOT / ".work")
    candidates = list(evidence_root.rglob("runtime-records.json"))
    assert len(candidates) == 1
    source_report = candidates[0]
    report = json.loads(source_report.read_text())
    assert len(report["runs"]) == 1
    run = report["runs"][0]
    assert run["status"] == "FAILED" and run["stop_reason"] == "error"
    assert run["private_body_recorded"] is False and run["cost_total"] is None
    source = (ROOT / "validation/.work" / run["namespace"] / "business.sqlite").resolve(strict=True)
    assert source.is_relative_to(ROOT / "validation/.work")
    schema_path = ROOT / "specs/runtime-records.schema.json"
    schema = json.loads(schema_path.read_text())
    schema["$ref"] = "#/$defs/CurrentRuntimeRun"
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(run)
    output = ROOT / "app/tests/fixtures/observed-runtime-failure"
    output.mkdir(parents=True)
    target = output / "business.sqlite"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        original.execute("BEGIN")
        snapshot = json.loads(original.execute("SELECT body FROM objects WHERE namespace=? AND kind='initial' AND id='snapshot'", (run["namespace"],)).fetchone()[0])
        assert snapshot["source_type"] == "SIMULATED"
        source_rows = tuple(original.iterdump())
        record = json.loads(original.execute("SELECT body FROM objects WHERE namespace=? AND kind='runtime_run' AND id=?", (run["namespace"], run["run_id"])).fetchone()[0])
        assert record == run
        task_id = next(item["task_id"] for item in run["tool_results"] if item["tool_id"] == "create_assignment")
        task = json.loads(original.execute("SELECT body FROM objects WHERE namespace=? AND kind='task' AND id=?", (run["namespace"], task_id)).fetchone()[0])
        assert task["status"] == "OPEN" and task["source_refs"] == ["finance-note"]
        assert original.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
        with sqlite3.connect(target) as copied:
            original.backup(copied)
            assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert tuple(copied.iterdump()) == source_rows
    (output / "runtime-records.json").write_bytes(source_report.read_bytes())
    shutil.copyfile(source_report.parent / "http-requests.json", output / "http-requests.json")
    input_files = ("validation/fault_probe.py", "validation/model_probe.py", "validation/business.py",
                   "validation/boss_runtime_records.py", "validation/connection.py", "validation/uv.lock",
                   "app/tests/test_boss_runtime.py", "validation/export_observed_runtime_fixture.py")
    manifest = {"status": "ACTUAL_RUNTIME_NATIVE_SQLITE_BACKUP", "producer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "source_type": "SIMULATED", "namespace": run["namespace"], "run_id": run["run_id"], "task_id": task_id,
                "source_database_sha256": digest(source), "source_report_sha256": digest(source_report),
                "fixture_database_sha256": digest(target), "logical_copy_identical": True, "integrity_check": "ok",
                "source_sha256": {name: digest(ROOT / name) for name in input_files},
                "schema_sha256": digest(schema_path), "fixture_sha256": {name: digest(output / name) for name in ("runtime-records.json", "http-requests.json")},
                "source_modified": False, "export_requested_model_calls": False, "cost_total": None}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
