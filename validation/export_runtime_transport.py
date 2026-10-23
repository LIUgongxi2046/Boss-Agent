import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from connection import RecordedProvider

ROOT = Path(__file__).resolve().parents[1]


def export():
    source = ROOT / "validation/.work/application/diagnostics/http-requests.json"
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    records = json.loads(source.read_text())
    assert isinstance(records, list) and records
    assert all(isinstance(record, dict) and isinstance(record["type"], str) for record in records)
    metadata = [RecordedProvider._sanitize_history(record) for record in records]
    assert all(record["private_contents_recorded"] is False for record in metadata)
    assert all(not {"messages", "content", "authorization", "api_key", "body"}.intersection(record) for record in metadata)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256
    result = {
        "status": "EXPORTED_PRODUCT_TRANSPORT_METADATA_ONLY",
        "at": datetime.now(timezone.utc).isoformat(), "source_sha256": source_sha256,
        "source": "validation/.work/application/diagnostics/http-requests.json",
        "record_count": len(metadata),
        "observed_requests": sum(record["type"] == "request" for record in metadata),
        "response_ids": sorted({record["response_id"] for record in metadata if record.get("response_id")}),
        "observed_http_error_records": sum(isinstance(record.get("status"), int) and record["status"] >= 400 for record in metadata),
        "records": metadata, "all_attempts_total_cost": None,
        "scope": "当前W3产品传输文件中的全部技术记录；其他独立Runtime任务分别引用原证据，完整费用覆盖尚未验证",
    }
    output = ROOT / "evidence/T09/w3-20261023/product-runtime-transport.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return {key: value for key, value in result.items() if key not in {"records", "response_ids"}}


if __name__ == "__main__":
    print(json.dumps(export(), ensure_ascii=False))
