import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from hermes_transport_client import HermesTransportClient


configuration = json.loads(sys.stdin.readline())
client = HermesTransportClient(configuration["endpoint"], configuration["capability"], configuration["run_id"])
try:
    if len(sys.argv) > 1 and not (len(sys.argv) > 2 and sys.argv[2].isdigit()):
        sys.path.insert(0, sys.argv[1])
        from tools.registry import registry
        from hermes_tool_registration import registered_product_tools
        from agent_artifact_hermes import FORMAT_TOOL_NAME, TOOL_NAME
        names = ("read_bound_documents", "read_product_memory", "read_enabled_method")
        with registered_product_tools(client, bi_definitions=client.bi_definitions()):
            if any(registry.get_entry(name) is None for name in names):
                raise ValueError("业务资料工具未注册")
            if any(registry.get_entry(name) is None for name in (TOOL_NAME, FORMAT_TOOL_NAME)) or registry.get_definitions({TOOL_NAME, FORMAT_TOOL_NAME}, quiet=True):
                raise ValueError("成果工具关闭状态不可核查")
        if any(registry.get_entry(name) is not None for name in (*names, TOOL_NAME, FORMAT_TOOL_NAME)):
            raise ValueError("业务资料工具未注销")
    if "provider_capability" in configuration:
        response = httpx.post(configuration["endpoint"] + "/chat/completions", headers={"Authorization": "Bearer " + configuration["provider_capability"]}, json={}, trust_env=False)
        expected_status = int(sys.argv[2]) if len(sys.argv) > 2 else 400
        if response.status_code != expected_status:
            raise ValueError("模型网关请求检查失败")
    request = client.request()
    event = client.emit("independent-process-start", "RUN_STARTED", {"engine_commit": configuration["engine_commit"]})
    repeated = client.emit("independent-process-start", "RUN_STARTED", {"engine_commit": configuration["engine_commit"]})
    client.close()
    client = HermesTransportClient(configuration["endpoint"], configuration["capability"], configuration["run_id"])
    if client.request()["run_id"] != request["run_id"]:
        raise ValueError("重新连接后的运行身份不一致")
    print(json.dumps({"request": request, "event": event, "repeated": repeated, "pending": client.pending_input()}, ensure_ascii=False), flush=True)
    if len(sys.argv) > 2 and sys.argv[2] == "--bi-reselect":
        from hermes_tool_registration import registered_bi_tools
        from tools.registry import registry
        initial = json.loads(sys.stdin.readline())
        with registered_bi_tools(client, client.bi_definitions()):
            original = json.loads(registry.dispatch("query_metrics", initial))
            if not original.get("query_id"):
                raise ValueError("初始经营查询失败")
            print(json.dumps({"query": original}, ensure_ascii=False), flush=True)
            update = json.loads(sys.stdin.readline())
            client.acknowledge_input(update["input_seq"])
            evidence = {"query_id": original["query_id"], "source_ids": [item["source_id"] for item in original["sources"]], "detail_refs": original["detail_refs"]}
            old_evidence = client.client.post("/internal/v1/tools/bi", json={"protocol_version": 1, "call_id": "old-evidence", "tool_name": "read_evidence", "arguments": evidence})
            old_query = client.client.post("/internal/v1/tools/bi", json={"protocol_version": 1, "call_id": "old-query", "tool_name": "query_metrics", "arguments": initial})
            if old_evidence.status_code != 403 or old_query.status_code != 403:
                raise ValueError("旧目标经营授权未被拒绝")
            response = client.client.post("/internal/v1/tools/bi", json={"protocol_version": 1, "call_id": "new-query", "tool_name": "query_metrics", "arguments": update["query"]})
            if response.status_code != 200:
                raise ValueError("新目标经营查询响应无效：" + str(response.status_code) + " " + response.text)
            current = response.json()["result"]
            if not current.get("query_id") or current["query_id"] == original["query_id"]:
                raise ValueError("新目标经营查询失败")
            repeated = json.loads(registry.dispatch("query_metrics", update["query"]))
            if repeated.get("query_id") != current["query_id"]:
                raise ValueError("新目标查询重复请求不可核查")
            current_evidence = {"query_id": current["query_id"], "source_ids": [item["source_id"] for item in current["sources"]], "detail_refs": current["detail_refs"]}
            proof = json.loads(registry.dispatch("read_evidence", current_evidence))
            if not proof.get("original_records"):
                raise ValueError("新目标查询依据不可核查")
            print(json.dumps({"old_evidence_status": old_evidence.status_code, "old_query_status": old_query.status_code, "query": current, "evidence_verified": True}, ensure_ascii=False), flush=True)
            if sys.stdin.readline() != "method-disabled\n":
                raise ValueError("方法检查信号无效")
            disabled = client.client.post("/internal/v1/tools/bi", json={"protocol_version": 1, "call_id": "disabled-query", "tool_name": "query_metrics", "arguments": update["query"]})
            if disabled.status_code != 409:
                raise ValueError("停用方法后的查询未被拒绝")
            print(json.dumps({"disabled_status": disabled.status_code}), flush=True)
            if sys.stdin.readline() != "\n":
                raise ValueError("来源撤销检查信号无效")
            denied = client.client.post("/internal/v1/tools/bi", json={"protocol_version": 1, "call_id": "withdrawn-query", "tool_name": "query_metrics", "arguments": update["query"]})
            if denied.status_code not in (401, 403, 409):
                raise ValueError("来源撤销后的查询未被拒绝")
            print(json.dumps({"withdrawn_status": denied.status_code}), flush=True)
    elif len(sys.argv) > 2 and sys.argv[2] == "--observe-revocation":
        if sys.stdin.readline() != "\n":
            raise ValueError("撤销检查信号无效")
        response = httpx.get(configuration["endpoint"] + "/internal/v1/request", headers={"Authorization": "Bearer " + configuration["capability"]}, trust_env=False)
        if response.status_code not in (401, 403, 409):
            raise ValueError("撤销后运行读取仍然可用")
        print(json.dumps({"revoked_status": response.status_code}), flush=True)
    elif len(sys.argv) > 3 and sys.argv[3] == "--wait-for-cancel":
        time.sleep(30)
    elif len(sys.argv) > 1:
        time.sleep(1)
finally:
    client.close()
