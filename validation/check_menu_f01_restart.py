import argparse
import json
import os

from business import checksum
from boss_morning import MorningAPI, QUERY_ACTION, ORDER_ACTION
from controls import ControlStore


def database_digest(store):
    with store.connect() as db:
        db.execute("BEGIN")
        return checksum({table: db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
                         for table in ("spaces", "objects", "idempotency", "audit", "knowledge")})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--list-id", required=True)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--order-id", required=True)
    args = parser.parse_args()
    store = ControlStore(args.database)
    before = database_digest(store)
    morning = MorningAPI(store)
    current = morning.read_list("BOSS", args.list_id)
    query = morning.receipt("BOSS", QUERY_ACTION, args.query_id)
    order = morning.receipt("BOSS", ORDER_ACTION, args.order_id)
    assert current["adoption_state"] == "CURRENT"
    assert query["outcome"] == order["outcome"] == "RECORDED"
    assert query["result"]["list_id"] == order["result"]["list_id"] == args.list_id
    assert current["current_order"]["item_ids"] == order["result"]["item_ids"]
    assert before == database_digest(store)
    print(json.dumps({"status": "PASS", "pid": os.getpid(), "list_id": args.list_id,
        "snapshot_sha256": current["result"]["snapshot_sha256"], "order_version": current["current_order"]["version"],
        "item_ids": current["current_order"]["item_ids"], "business_changes": 0}))


if __name__ == "__main__":
    main()
