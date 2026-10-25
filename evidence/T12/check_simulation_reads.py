import argparse
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_simulation_api import KINDS, SCHEMA, SimulationAPI
from business import checksum, initial_materials
from controls import ControlStore

parser = argparse.ArgumentParser()
parser.add_argument("--database", type=Path, required=True)
database = parser.parse_args().database
assert database.is_file(), database
store = ControlStore(database)
validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def manifest():
    tables = {"objects": "namespace,kind,id,body", "idempotency": "namespace,operation,key,digest,result",
              "audit": "id,namespace,operation,input,output,created_at", "spaces": "namespace,active,snapshot",
              "knowledge": "namespace,source_id,content"}
    with store.connect() as db:
        return {table: checksum(db.execute("SELECT " + fields + " FROM " + table + " ORDER BY " + fields).fetchall()) for table, fields in tables.items()}


before = manifest()
api = SimulationAPI(store)
interfaces = []
for interface in KINDS:
    query = {"interface_id": interface, "object_ids": [], "filters": {}}
    result = api.query("BOSS", query)
    technical = api.inspect("MAINTAINER", query)
    validator.validate(result)
    validator.validate(technical)
    assert technical["access"] == "TECHNICAL_METADATA" and technical["sources"] == []
    assert all(record["data"] is None and record["source_refs"] == [] for record in technical["records"])
    assert not result["business_actions_performed"] and not result["external_retrieval_performed"]
    interfaces.append({"interface_id": interface, "availability": result["availability"], "records": len(result["records"]),
                       "readable_records": sum(record["data"] is not None for record in result["records"]),
                       "technical_records": len(technical["records"]), "missing_fields": result["missing_fields"]})
after = manifest()
assert before == after
with store.connect() as db:
    initial = store.get(db, result["execution_namespace"], "initial", "snapshot")
    assert checksum(initial) == checksum(initial_materials())
print(json.dumps({"status": "PASS", "schema_id": SCHEMA["$id"], "interfaces": interfaces,
                  "initial_snapshot_sha256": checksum(initial), "before_tables_sha256": before, "after_tables_sha256": after,
                  "implementation_sha256": hashlib.sha256((ROOT / "validation/boss_simulation_api.py").read_bytes()).hexdigest(),
                  "schema_sha256": hashlib.sha256((ROOT / "specs/simulation-query.schema.json").read_bytes()).hexdigest(),
                  "new_model_calls": False, "new_business_actions": False}, ensure_ascii=False, indent=2))
