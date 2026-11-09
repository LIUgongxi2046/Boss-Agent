import argparse
import json
import os
import sys
from pathlib import Path

from hermes_transport_client import HermesTransportClient
from hermes_tool_names import PRODUCT_TOOL_NAMES

_ENGINE_HOME = Path("/dev/shm/boss-engine-home")
if _ENGINE_HOME.parent.is_dir():
    _ENGINE_HOME.mkdir(mode=0o700, exist_ok=True)
    os.environ["HOME"] = str(_ENGINE_HOME)
    os.environ["HERMES_HOME"] = str(_ENGINE_HOME / ".hermes")


def diagnostic(stage):
    path = Path("/mnt/engine-diagnostic.log")
    if not path.parent.is_dir():
        return
    with path.open("a", encoding="utf-8") as target:
        target.write(stage + "\n")
        target.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine_dir", type=Path)
    parser.add_argument("--max-rounds", type=int, required=True)
    parser.add_argument("--max-seconds", type=int, required=True)
    args = parser.parse_args()
    diagnostic("args-ok")
    if not args.engine_dir.is_absolute() or not args.engine_dir.is_dir() or args.max_rounds <= 0 or args.max_seconds <= 0:
        raise ValueError("引擎目录或运行预算无效")
    sys.path.insert(0, str(args.engine_dir))
    from run_agent import AIAgent
    from model_tools import get_tool_definitions
    from hermes_tool_registration import registered_product_tools
    diagnostic("imports-ok")

    raw = sys.stdin.buffer.read(4097)
    sys.stdin.close()
    if len(raw) > 4096:
        raise ValueError("启动信息过长")
    bootstrap = json.loads(raw)
    diagnostic("bootstrap-ok")
    required_bootstrap = {"endpoint", "capability", "provider_capability", "run_id", "engine_commit"}
    if not isinstance(bootstrap, dict) or set(bootstrap) not in (required_bootstrap, required_bootstrap | {"technical_check"}):
        raise ValueError("启动信息无效")
    provider_capability = bootstrap["provider_capability"]
    if bootstrap["engine_commit"] != "903230b1e23e0c496b28e5d2e8c4f2639cd506b6" or not isinstance(provider_capability, str) or len(provider_capability) < 32 or not provider_capability.isascii() or provider_capability == bootstrap["capability"]:
        raise ValueError("引擎版本或模型凭据无效")
    client = HermesTransportClient(bootstrap["endpoint"], bootstrap["capability"], bootstrap["run_id"])
    diagnostic("client-ok")
    try:
        diagnostic("input-context-start")
        request = client.input_context()
        diagnostic("input-context-ok")
        if request["run_id"] != bootstrap["run_id"]:
            raise ValueError("运行请求编号不匹配")
        diagnostic("run-started-start")
        client.emit("engine-start", "RUN_STARTED", {"engine_commit": bootstrap["engine_commit"]})
        diagnostic("run-started-ok")
        completed = False
        failure_code = "ENGINE_ENTRY_UNAVAILABLE"
        try:
            if request["requirements"]["state"] != "CONFIRMED":
                client.wait_for_requirements(request["goal_revision"])
                completed = True
                return
            diagnostic("prepare-inputs-start")
            client.prepare_inputs()
            diagnostic("prepare-inputs-ok")
            bi_definitions = client.bi_definitions()
            with registered_product_tools(client, bi_definitions=bi_definitions):
                if "technical_check" in bootstrap:
                    from tools.registry import registry
                    check = bootstrap["technical_check"]
                    fields = {"query", "path", "content", "hold_seconds"}
                    if not isinstance(check, dict) or not fields <= set(check) <= fields | {"wait_question", "record_result"} or not isinstance(check["query"], dict) or not isinstance(check["path"], str) or not isinstance(check["content"], str) or type(check["hold_seconds"]) is not int or not 0 <= check["hold_seconds"] <= min(90, args.max_seconds) or "wait_question" in check and (not isinstance(check["wait_question"], str) or not check["wait_question"].strip() or len(check["wait_question"]) > 2000) or "record_result" in check and type(check["record_result"]) is not bool:
                        raise ValueError("技术检查输入无效")
                    denied_query = {**check["query"], "question": check["query"]["question"] + " 范围变化"}
                    denied = json.loads(registry.dispatch("query_metrics", denied_query))
                    if not isinstance(denied, dict) or "403" not in str(denied.get("error", "")):
                        raise ValueError("经营查询越界拒绝检查失败")
                    query = json.loads(registry.dispatch("query_metrics", check["query"]))
                    if isinstance(query, dict) and "429" in str(query.get("error", "")):
                        failure_code = "TECHNICAL_BI_BUDGET_EXHAUSTED"
                    if not isinstance(query, dict) or not query.get("query_id") or not isinstance(query.get("sources"), list) or not query["sources"]:
                        raise ValueError("经营查询技术检查失败")
                    evidence = {"query_id": query["query_id"], "source_ids": [item["source_id"] for item in query["sources"]], "detail_refs": query["detail_refs"]}
                    proof = json.loads(registry.dispatch("read_evidence", evidence))
                    if not isinstance(proof, dict) or not proof.get("original_records"):
                        raise ValueError("经营依据技术检查失败")
                    written = json.loads(registry.dispatch("workspace_write_file", {"path": check["path"], "content": check["content"]}))
                    if not isinstance(written, dict) or written.get("error") or written.get("success") is False:
                        detail = written.get("error", "") if isinstance(written, dict) else ""
                        for marker, code in (("Permission denied", "TECHNICAL_FILE_PERMISSION"), ("Read-only file system", "TECHNICAL_FILE_READ_ONLY"), ("Operation not permitted", "TECHNICAL_FILE_OPERATION"), ("No such file or directory", "TECHNICAL_FILE_MISSING"), ("No space left on device", "TECHNICAL_FILE_CAPACITY"), ("No module named", "TECHNICAL_FILE_DEPENDENCY")):
                            if isinstance(detail, str) and marker in detail:
                                failure_code = code
                                break
                        else:
                            terms = ("terminal", "environment", "failed", "write", "read", "shell", "command", "python", "thread", "start", "quota", "space", "timeout", "unsupported", "denied", "blocked", "invalid", "directory", "file", "exists", "missing")
                            found = [term.upper() for term in terms if isinstance(detail, str) and term in detail.lower()]
                            failure_code = "TECHNICAL_FILE_" + ("_".join(found) if found else "OTHER")
                        raise ValueError("工作区写入技术检查失败")
                    read = json.loads(registry.dispatch("workspace_read_file", {"path": check["path"]}))
                    if not isinstance(read, dict) or read.get("error") or read.get("success") is False or check["content"] not in read.get("content", ""):
                        raise ValueError("工作区读取技术检查失败")
                    if "wait_question" in check:
                        waiting = json.loads(registry.dispatch("request_additional_input", {"question": check["wait_question"]}))
                        if not isinstance(waiting, dict) or waiting.get("status") != "WAITING_INPUT" or client.waiting_state != "WAITING_INPUT":
                            raise ValueError("等待输入技术检查失败")
                        completed = True
                        return
                    exhausted = json.loads(registry.dispatch("query_metrics", check["query"]))
                    if not isinstance(exhausted, dict) or "429" not in str(exhausted.get("error", "")):
                        raise ValueError("根工具预算拒绝检查失败")
                    if check.get("record_result") is True:
                        citations = [{"source_id": item["source_id"], "locator": "version " + str(item["version"])} for item in query["sources"]]
                        values = query.get("values")
                        source_ids = [item["source_id"] for item in query["sources"]]
                        semantic = {"goal_revision": request["goal_revision"], "query_id": query["query_id"], "values": values, "source_ids": source_ids, "evidence_records": len(proof["original_records"])}
                        summary = json.dumps({"query_id": query["query_id"], "values": values, "sources": source_ids, "evidence_records": len(proof["original_records"]), "semantic_evidence": semantic}, ensure_ascii=False, sort_keys=True)
                        client.record_result("engine-technical-result:" + str(request["goal_revision"]), request["goal_revision"], summary, citations)
                        client.emit("engine-finished", "RUN_FINISHED", {"outcome": "ENGINE_COMPLETED"})
                    if check["hold_seconds"]:
                        import time
                        time.sleep(check["hold_seconds"])
                    completed = True
                    return
                agent = None
                failure_code = "ENGINE_AGENT_CONSTRUCTION"
                try:
                    agent = AIAgent(model="deepseek-flash", provider="deepseek", api_mode="chat_completions",
                                    api_key=provider_capability, base_url=bootstrap["endpoint"],
                                    enabled_toolsets=["boss_domain"], max_iterations=args.max_rounds,
                                    run_budget_seconds=args.max_seconds, quiet_mode=True, skip_context_files=True,
                                    skip_memory=True, skip_background_review=True, cwd=str(Path.cwd()))
                except BaseException as error:
                    failure_code = "ENGINE_AGENT_CONSTRUCTION:" + type(error).__name__ + ":" + str(error)[:200].replace("\n", " ")
                    raise
                try:
                    failure_code = "ENGINE_MODEL_ENTRY_CHECK"
                    if agent.model != "deepseek-flash" or agent.base_url.rstrip("/") != bootstrap["endpoint"].rstrip("/") or agent.api_key != provider_capability or agent.max_iterations != args.max_rounds:
                        raise ValueError("引擎模型入口或运行预算不匹配")
                    failure_code = "ENGINE_TOOL_DEFINITIONS"
                    from tools.registry import registry as tool_registry
                    from agent_artifact_hermes import FORMAT_TOOL_NAME as ARTIFACT_BRIEF, TOOL_NAME as ARTIFACT_DOCX
                    artifact_names = {ARTIFACT_DOCX, ARTIFACT_BRIEF, "boss_runtime_meeting_brief"}
                    definitions = get_tool_definitions(enabled_toolsets=["boss_domain"], quiet_mode=True, skip_tool_search_assembly=True)
                    registered = {item["function"]["name"] for item in definitions}
                    available = {name for name in PRODUCT_TOOL_NAMES if tool_registry.get_entry(name) is not None}
                    if not available.issubset(registered) or not registered.issubset(PRODUCT_TOOL_NAMES | artifact_names):
                        raise ValueError("引擎工具集合不可核查")
                    if agent.valid_tool_names not in (registered, {"tool_search", "tool_describe", "tool_call"}):
                        raise ValueError("引擎工具注册集合不可核查")
                    failure_code = "ENGINE_MODEL_AUTHORIZATION"
                    client.authorize_model_execution()
                    failure_code = "ENGINE_PREPARE_TURN"
                    turn = client.prepare_turn()
                    client.waiting_interrupt = lambda: agent.interrupt("boss waiting for user", tool_reason="boss waiting for user")
                    failure_code = "ENGINE_CONVERSATION"
                    result = agent.run_conversation(turn["prompt"], task_id=request["run_id"])
                    failure_code = "ENGINE_RESULT"
                    if client.waiting_state is not None:
                        if not isinstance(result, dict) or result.get("completed") is not False or result.get("failed") is not False or result.get("interrupted") is not True or result.get("interrupt_message") != "boss waiting for user":
                            raise ValueError("引擎等待退出结果不可核查")
                        completed = True
                        return
                    if not isinstance(result, dict) or result.get("completed") is not True or result.get("failed") is not False or result.get("interrupted") is not False or not isinstance(result.get("final_response"), str) or not result["final_response"].strip():
                        raise ValueError("引擎结果未完成或不可保存")
                    client.record_result("engine-result:" + str(turn["goal_revision"]), turn["goal_revision"], result["final_response"], [])
                    client.emit("engine-finished", "RUN_FINISHED", {"outcome": "ENGINE_COMPLETED"})
                    completed = True
                finally:
                    if agent is not None:
                        agent.close()
        finally:
            if not completed and client.waiting_state is None:
                client.emit("engine-entry-failed", "RUN_FAILED", {"error_code": failure_code})
    finally:
        client.close()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        import traceback
        diagnostic("failure\n" + traceback.format_exc())
        raise
