import argparse
import json
import os
from pathlib import Path
import sqlite3

from controls import ControlStore
from boss_business_alerts import BusinessAlertsAPI


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    store = ControlStore(args.database)
    current = BusinessAlertsAPI(store).read("BOSS")["items"][0]
    assert current["reminder"]["state"] == "CLOSED"
    backup_path = Path(args.database).with_name("fc04-restart-backup.sqlite")
    assert not backup_path.exists()
    with store.connect() as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
        for table in ("spaces", "objects", "idempotency", "audit", "knowledge"):
            assert source.execute("SELECT * FROM " + table).fetchall() == target.execute("SELECT * FROM " + table).fetchall()
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    store = ControlStore(backup_path)
    assert BusinessAlertsAPI(store).read("BOSS")["items"][0]["reminder"]["state"] == "CLOSED"
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('authorization','notification','task','outbox')").fetchone()[0]
    result = store.dispatch_due("ui-check")[0]
    assert result["reason"] == "BOSS_CLOSED"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('authorization','notification','task','outbox')").fetchone()[0] == before
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    print(json.dumps({"status": "PASS", "pid": os.getpid(), "event_id": current["event_id"], "event_version": current["event_version"], "state": "CLOSED", "reason": result["reason"], "new_business_actions": 0, "backup": "VERIFIED_FIVE_TABLES"}))


if __name__ == "__main__":
    main()
