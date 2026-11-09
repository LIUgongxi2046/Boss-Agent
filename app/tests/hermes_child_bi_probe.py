import json
import sys

from hermes_tool_registration import registered_bi_tools
from hermes_transport_client import HermesTransportClient
from tools.registry import registry


configuration = json.loads(sys.stdin.readline())
client = HermesTransportClient(configuration["endpoint"], configuration["capability"], configuration["run_id"])
try:
    with registered_bi_tools(client, client.bi_definitions()):
        result = json.loads(registry.dispatch("query_metrics", configuration["query"]))
        if not result.get("query_id") or not result.get("sources"):
            raise ValueError("子运行经营查询未返回有效结果")
        evidence = {"query_id": result["query_id"], "source_ids": [item["source_id"] for item in result["sources"]], "detail_refs": result["detail_refs"]}
        proof = json.loads(registry.dispatch("read_evidence", evidence))
        if not proof.get("original_records"):
            raise ValueError("子运行经营依据不可核查")
        print(json.dumps({"query_id": result["query_id"], "metric_ids": result["context_snapshot"]["metric_ids"], "records": len(proof["original_records"])}), flush=True)
        if sys.stdin.readline() != "\n":
            raise ValueError("父目标变化检查信号无效")
        response = client.client.post("/internal/v1/tools/bi", json={"protocol_version": 1, "call_id": "child-after-parent-change",
                                      "tool_name": "query_metrics", "arguments": configuration["query"]})
        if response.status_code not in configuration["expected_statuses"]:
            raise ValueError("父运行授权变化后子运行查询未被拒绝")
        print(json.dumps({"status": response.status_code}), flush=True)
finally:
    client.close()
