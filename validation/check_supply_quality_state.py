import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from business import checksum, initial_materials

ROOT = Path(__file__).resolve().parents[1]


def inspect(directory):
    directory = directory.resolve(strict=True)
    assert directory.parent == (ROOT / "validation/.work").resolve()
    database = directory / "business.sqlite"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        before = tuple(db.iterdump())
        def objects(kind):
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind=? ORDER BY id", (kind,))]
        initial = objects("initial")[0]
        assert initial == initial_materials()
        tasks = objects("task")
        events = objects("production_event")
        inventory = objects("inventory_lot")
        result = {"initial_sha256": checksum(initial), "task_count": len(tasks),
            "tasks": [{key: task[key] for key in ("task_id", "version", "status", "related_meeting_id", "related_event_ids")} for task in tasks],
            "production_events": [{"id": event["data"]["event_id"], "state": event["data"]["state"]} for event in events],
            "inventory": [{"id": row["data"]["inventory_id"], "quality_state": row["data"]["quality_state"]} for row in inventory],
            "counts": {kind: len(objects(kind)) for kind in ("outbox", "feedback", "authorization", "external_import", "runtime_run")},
            "account_sha256": hashlib.sha256((directory / "accounts/accounts.sqlite").read_bytes()).hexdigest(),
            "business_sha256": checksum(before)}
        assert tuple(db.iterdump()) == before
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--application-directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.application_directory), ensure_ascii=False))
