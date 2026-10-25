import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from business import initial_materials


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report_path = args.report.resolve(strict=True)
    assert report_path.is_relative_to(ROOT / "evidence/T11")
    report = json.loads(report_path.read_text())
    assert report["status"] == "PASS_PUBLIC_F06_SOURCE_REVIEW_AND_LEGACY_UPGRADE"
    directory = (ROOT / "validation/.work" / report["run_id"]).resolve(strict=True)
    assert directory.parent == (ROOT / "validation/.work").resolve()
    source = directory / "business.sqlite"
    output = ROOT / "app/tests/fixtures/observed-owner-state"
    output.mkdir(parents=True)
    target = output / "business.sqlite"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        original.execute("BEGIN")
        snapshot = json.loads(original.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='initial' AND id='snapshot'").fetchone()[0])
        assert snapshot == initial_materials()
        assert original.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 2
        assert original.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
        source_rows = tuple(original.iterdump())
        with sqlite3.connect(target) as copied:
            original.backup(copied)
            assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert tuple(copied.iterdump()) == source_rows
    paths = ("validation/boss_today.py", "validation/boss_owner_plans.py", "validation/boss_meetings.py",
             "validation/export_public_store_fixture.py")
    manifest = {"status": "ACTUAL_PUBLIC_GUI_NATIVE_SQLITE_BACKUP", "source_type": "SIMULATED",
                "producer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "source_report": str(report_path.relative_to(ROOT)), "source_report_sha256": digest(report_path),
                "source_database_sha256": digest(source), "fixture_database_sha256": digest(target),
                "source_sha256": {name: digest(ROOT / name) for name in paths},
                "logical_copy_identical": True, "integrity_check": "ok", "source_modified": False,
                "export_requested_model_calls": False}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
