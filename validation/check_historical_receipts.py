import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path("/Users/liuhaoxian/Downloads/我的/AI项目/Boss-Agent").resolve()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_file(item):
    path = Path(item["path"]).resolve()
    if not path.is_relative_to(ORIGINAL) and not path.is_relative_to(ROOT):
        return {"path": str(path), "state": "OUTSIDE_PROJECT_SCOPE"}
    if not path.is_file():
        return {"path": str(path), "state": "MISSING"}
    actual = digest(path)
    return {"path": str(path), "state": "MATCH" if actual == item["sha256"] else "CONTENT_CHANGED",
            "expected_sha256": item["sha256"], "actual_sha256": actual}


def main():
    ledger_path = ROOT / "delivery-ledger.json"
    ledger = json.loads(ledger_path.read_text())
    environment = (ROOT / ledger["baseline"]["environment_ref"]).resolve()
    records = []
    for reference in ledger["evidence"]:
        path = ROOT / reference["receipt_path"]
        receipt = json.loads(path.read_text())
        captured = receipt.get("schema_version") == 1 and receipt.get("captured_by") == "haonan-s000-capture-check/v1"
        item = {"evidence_id": reference["id"], "receipt_path": reference["receipt_path"],
                "receipt_hash_matches": digest(path) == reference["receipt_sha256"],
                "capture_format": captured,
                "baseline_matches": reference["baseline_id"] == ledger["baseline"]["id"]}
        if captured:
            item["environment_path_bound"] = any(Path(value["path"]).resolve() == environment for value in receipt["inputs"])
            item["input_files"] = [inspect_file(value) for value in receipt["inputs"]]
            item["artifact_files"] = [inspect_file(value) for value in receipt["artifacts"]]
        records.append(item)
    report = {"status": "HISTORICAL_RECEIPT_INVENTORY_ONLY", "ledger_sha256": digest(ledger_path),
              "baseline_id": ledger["baseline"]["id"], "current_environment_path": str(environment),
              "records": records, "historical_acceptances_changed": False,
              "new_model_calls": False, "delivery_validation_passed": False}
    output = ROOT / "evidence/T10/w3-ledger-20261023/historical-receipts.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "receipts": len(records),
                      "capture_format_receipts": sum(item["capture_format"] for item in records),
                      "environment_path_bound": sum(item.get("environment_path_bound", False) for item in records),
                      "file_checks": {state: sum(value["state"] == state for item in records
                                                for key in ("input_files", "artifact_files") for value in item.get(key, []))
                                      for state in ("MATCH", "CONTENT_CHANGED", "MISSING", "OUTSIDE_PROJECT_SCOPE")},
                      "report": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
