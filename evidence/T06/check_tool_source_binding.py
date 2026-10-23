import argparse
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_page_api import BossPageAPI
from controls import ControlStore

parser = argparse.ArgumentParser()
parser.add_argument("--run-dir", type=Path, required=True)
parser.add_argument("--reference-policy", type=Path, required=True)
arguments = parser.parse_args()
run_dir = arguments.run_dir.resolve()
assert run_dir.is_relative_to(ROOT / ".work")
run_dir.mkdir(parents=True, exist_ok=True)
policy_sha256 = hashlib.sha256((ROOT / "validation/boss_source_policy.py").read_bytes()).hexdigest()
assert policy_sha256 == hashlib.sha256(arguments.reference_policy.read_bytes()).hexdigest()
assert policy_sha256 == "6565c180348dc23f60c80e9b4947ab4e46c1e4a83a0fd0ee22d2d1bd0d681896"
store = ControlStore(run_dir / (str(uuid4()) + ".sqlite"))
store.initialize("ui-check")
pages = BossPageAPI(store)
status, response = pages.serve("BOSS", "/api/boss/ui/metrics")
assert status == 200
previous = response["result"]
with store.connect() as db:
    document = store.get(db, "ui-check", "document", "finance-note")
    original = document["content"]
    document["version"] = str(int(document["version"]) + 1)
    store.put(db, "ui-check", "document", "finance-note", document)
with pytest.raises(web.HTTPConflict):
    store.invoke("read_evidence", {"envelope": previous["envelope"], "query_id": previous["query_id"],
        "source_ids": ["finance-note"], "detail_refs": previous["detail_refs"]})
status, response = pages.serve("BOSS", "/api/boss/ui/metrics")
assert status == 200
current = response["result"]
result = store.invoke("read_evidence", {"envelope": current["envelope"], "query_id": current["query_id"],
    "source_ids": ["finance-note"], "detail_refs": current["detail_refs"]})
record = next(row for row in result["original_records"] if row["record_id"] == "finance-note")
assert current["sources"][0]["version"] == result["sources"][0]["version"] == record["version"] == record["content"]["version"] == document["version"]
assert record["content"]["content"] == original
print(json.dumps({"status": "PASS", "source_id": "finance-note", "current_document_version": document["version"],
    "reported_source_version": result["sources"][0]["version"], "source_version_matches": True,
    "earlier_query_requires_refresh": True, "original_body_unchanged": True,
    "policy_sha256": policy_sha256, "policy_owner": "W2", "external_request_sent": False}, ensure_ascii=False))
