import argparse
import json
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="核查实际 Agent 运行与回答引用")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--chat-id", required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.directory / "business.sqlite") as db:
        record = db.execute("SELECT body FROM objects WHERE kind='runtime_run' AND json_extract(body,'$.chat_id')=? ORDER BY rowid DESC LIMIT 1", (args.chat_id,)).fetchone()
    if record is None:
        raise ValueError("当前会话没有实际运行记录")
    row = json.loads(record[0])
    assert row["status"] == "SUCCEEDED", row["status"]
    assert row.get("external_model_invoked") is True
    assert row["model_requests"] and all(item["http_status"] == 200 for item in row["model_requests"])
    assert row["model_requests"][-1]["finish_reasons"] == ["stop"]
    assert row["tool_results"] and not row.get("tool_errors")
    assert len(row["model_requests"]) <= row["runtime"]["max_tool_rounds"]
    streams = row["stream_observations"]
    assert streams and sum(item["characters"] for item in streams) > 0
    assert all(item["incoming_sha256"] == item["delivered_sha256"] for item in streams)
    final_round = len(row["model_requests"]) == row["runtime"]["max_tool_rounds"]
    print(json.dumps({"run_id": row["run_id"], "chat_id": args.chat_id, "status": row["status"],
                      "model": row["runtime"]["model_id"], "model_requests": len(row["model_requests"]),
                      "configuration_version": row["configuration_version"], "model_connection": row["model_connection"],
                      "timeout_seconds": row["runtime"]["timeout"], "started_at": row["started_at"], "finished_at": row["finished_at"],
                      "stream_characters": sum(item["characters"] for item in streams),
                      "received_chunks": sum(item["chunks"] for item in streams), "delivery_batches": sum(item["delivery_batches"] for item in streams),
                      "stream_text_verified": True,
                      "tools": [item["tool_id"] for item in row["tool_results"]], "external_model_invoked": True,
                      "model_round_budget": row["runtime"]["max_tool_rounds"], "final_round_used": final_round}, ensure_ascii=False))


if __name__ == "__main__":
    main()
