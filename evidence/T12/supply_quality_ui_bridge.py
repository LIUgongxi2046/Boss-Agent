import argparse
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_assignment_sources import AssignmentSourcesAPI
from boss_supply_quality import IMPORT_ACTION, SupplyQualityAPI
from controls import ControlStore

parser = argparse.ArgumentParser()
parser.add_argument("--database", required=True, type=Path)
parser.add_argument("--mode", required=True, choices=("initialize", "read", "command", "review", "verify"))
parser.add_argument("--payload", default="{}")
arguments = parser.parse_args()
store = ControlStore(arguments.database)
api = SupplyQualityAPI(store)
payload = json.loads(arguments.payload)
if arguments.mode == "initialize":
    store.initialize("ui-check")
    definition = yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())
    result = api.execute("MAINTAINER", IMPORT_ACTION, definition["initial_request"])
elif arguments.mode == "read":
    result = api.read("BOSS", payload["interface_id"])
elif arguments.mode == "command":
    result = api.execute(payload["role"], payload["action"], payload["input"])
elif arguments.mode == "review":
    result = AssignmentSourcesAPI(store).read("BOSS", payload["task_id"])
else:
    with store.connect() as db:
        links = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='supply_quality_coordination'")]
        tasks = [store.get(db, "ui-check", "task", link["task_id"]) for link in links]
        result = {"links": links, "tasks": tasks,
                  "event_state": store.get(db, "ui-check", "production_event", "sim-production-event-1")["state"],
                  "stock_state": store.get(db, "ui-check", "inventory_lot", "sim-stock-finished-1")["state"],
                  "outbox_count": db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0]}
print(json.dumps(result, ensure_ascii=False))
