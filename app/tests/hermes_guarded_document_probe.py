import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from hermes_transport_client import HermesTransportClient


configuration = json.load(sys.stdin)
client = HermesTransportClient(configuration["endpoint"], configuration["capability"], configuration["run_id"])
try:
    client.emit("document-process-start", "RUN_STARTED", {"engine_commit": configuration["engine_commit"]})
    result = client.read_documents("document-process-read")
    if result != client.read_documents("document-process-read") or result != client.document_result("document-process-read"):
        raise ValueError("来源读取结果不一致")
    if {record["object_id"] for record in result["records"]} != {"finance-note"}:
        raise ValueError("来源读取范围不一致")
finally:
    client.close()
