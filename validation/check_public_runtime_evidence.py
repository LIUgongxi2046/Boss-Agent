import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference")
    args = parser.parse_args()
    reference = (ROOT / args.reference).resolve(strict=True)
    if not reference.is_relative_to(ROOT / "evidence/T11"):
        raise ValueError("检查输入必须为本工程T11实际证据")
    report = json.loads(reference.read_text())
    schema_file = ROOT / "specs/runtime-records.schema.json"
    schema = json.loads(schema_file.read_text())
    schema["$ref"] = "#/$defs/CurrentRuntimeRun"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    database = ROOT / "validation/.work" / report["run_id"] / "business.sqlite"
    transport_file = database.parent / "diagnostics/http-requests.json"
    transport = json.loads(transport_file.read_text())
    actual_records = [entry["record"] for entry in report["records"] if "record" in entry]
    assert len(actual_records) == 2
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        for row in actual_records:
            validator.validate(row)
            saved = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run' AND id=?", (row["run_id"],)).fetchone()
            assert saved is not None and json.loads(saved[0]) == row
            events = [entry for entry in transport if entry.get("run_id") == row["run_id"]]
            assert sum(entry["type"] == "request" for entry in events) == len(row["model_requests"])
            assert all(entry["max_tokens"] == row["runtime"]["max_output_tokens"]
                       and entry["model"] == row["runtime"]["model_id"]
                       and entry["tool_config_sha256"] == row["tool_config_sha256"]
                       for entry in events if entry["type"] == "request")
            assert {entry["model_request_id"] for entry in events} == {item["model_request_id"] for item in row["model_requests"]}
            assert {entry["configuration_version"] for entry in events} == {row["configuration_version"]}
            assert all(entry.get("private_contents_recorded", False) is False for entry in events)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                assert row["usage"][field] == sum(item["usage"][field] for item in row["model_requests"])
            assert row["status"] == "SUCCEEDED" and row["cost_total"] is None and row["price_version"] is None
        current = json.loads(db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='configuration' AND id='current'").fetchone()[0])
        assert current["version"] == "3" and current["max_tool_rounds"] == 6
    output = ROOT / "evidence/T09/w3-20261023/public-runtime-schema-binding.json"
    result = {"status": "PASS_ACTUAL_PUBLIC_RUNTIME_SCHEMA_AND_TRANSPORT", "reference": str(reference.relative_to(ROOT)),
              "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
              "schema_sha256": hashlib.sha256(schema_file.read_bytes()).hexdigest(),
              "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
              "transport_sha256": hashlib.sha256(transport_file.read_bytes()).hexdigest(),
              "runs": [{"run_id": row["run_id"], "configuration_version": row["configuration_version"],
                        "max_tool_rounds": row["runtime"]["max_tool_rounds"], "model_requests": len(row["model_requests"]),
                        "total_tokens": row["usage"]["total_tokens"]} for row in actual_records],
              "new_model_calls": False, "private_body_recorded": False, "cost_total": None,
              "full_A11_A16_accepted": False}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
