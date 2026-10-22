import hashlib
import json
from datetime import datetime
from decimal import Decimal

from business import ROOT, now


def main():
    evidence = ROOT.parent / "evidence/T02"
    usage_rows, runs, unknown = [], [], []
    for transport_path in sorted(evidence.rglob("http-requests.json")):
        records = json.loads(transport_path.read_text())
        requests = [record for record in records if record["type"] == "request"]
        raw = {}
        for record in records:
            if record["type"] in {"response", "stream_metadata"} and record.get("response_id") and record.get("usage"):
                raw[record["response_id"]] = record
        rows = []
        if raw:
            for identifier, record in raw.items():
                usage = record["usage"]
                rows.append({"response_id": identifier, "input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"], "cache_read_tokens": usage.get("prompt_cache_hit_tokens"), "at": record["at"], "source": "official_sdk_response_usage"})
        else:
            events_path = transport_path.with_name("events.json")
            if events_path.exists():
                events = json.loads(events_path.read_text())
                for index, event in enumerate(events):
                    usage = event.get("usage")
                    if event.get("type") == "iteration" and usage and usage.get("source") == "reported":
                        rows.append({"response_id": None, "event_index": index, "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "cache_read_tokens": usage.get("cache_read_tokens"), "at": event["at"], "source": "upstream_hook_reported_usage"})
        unmatched = 0
        if len(rows) > len(requests):
            unmatched = len(rows)
            unknown.append({"path": str(transport_path.relative_to(evidence)), "reason": "Hook 用量记录数量超过保留的 transport 请求数量，不能建立逐请求关联；原始事件完整保留，本文件的用量不计入已关联费用小计。", "unmatched_usage_records": unmatched})
            rows = []
        for row in rows:
            row["evidence"] = str(transport_path.parent.relative_to(evidence))
            usage_rows.append(row)
        missing = len(requests) - len(rows)
        runs.append({"path": str(transport_path.relative_to(evidence)), "requests": len(requests), "known_usage_requests": len(rows), "unmatched_usage_records": unmatched, "missing_usage_requests": missing, "response_ids": sorted({record["response_id"] for record in records if record.get("response_id")})})
        if missing:
            unknown.append({"path": str(transport_path.relative_to(evidence)), "missing_usage_requests": missing})
    unique_ids = [row["response_id"] for row in usage_rows if row["response_id"] is not None]
    assert len(unique_ids) == len(set(unique_ids)), "同一服务响应用量重复计数"
    low, high = Decimal(0), Decimal(0)
    priced = 0
    for row in usage_rows:
        hit = row["cache_read_tokens"]
        if hit is None:
            continue
        assert 0 <= hit <= row["input_tokens"]
        miss = row["input_tokens"] - hit
        value = (Decimal(hit) * Decimal("0.003") + Decimal(miss) * Decimal("0.15") + Decimal(row["output_tokens"]) * Decimal("0.6")) / 1000000
        low += value
        high += value * 2
        priced += 1
    timings = []
    for path in sorted(evidence.glob("deepseek-*/events.json")):
        events = json.loads(path.read_text())
        starts = [event for event in events if event["type"] == "instruction"]
        ends = [event for event in events if event["type"] == "result"]
        if starts and ends:
            timings.append({"run": path.parent.name, "turns_started": len(starts), "turns_completed": len(ends), "elapsed_seconds": (datetime.fromisoformat(ends[-1]["at"]) - datetime.fromisoformat(starts[0]["at"])).total_seconds()})
    code = {}
    for path in sorted(ROOT.glob("*.py")):
        code[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in [ROOT / "uv.lock", ROOT / "pyproject.toml", ROOT / "connection.json", *sorted((ROOT / "desktop").glob("*.cjs")), *sorted((ROOT / "desktop").glob("*.mjs")), ROOT / "desktop/package.json", ROOT / "desktop/package-lock.json"]:
        code[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    summary = {"at": now(), "provider": "deepseek", "model_id": "deepseek-flash", "observed_api_type": "chat_completions", "pricing_date": "2026-10-22", "pricing_source": "https://api-docs.deepseek.com/quick_start/pricing/", "currency": "USD", "price_per_million": {"off_peak": {"cache_hit": "0.003", "cache_miss": "0.15", "output": "0.6"}, "peak": {"cache_hit": "0.006", "cache_miss": "0.3", "output": "1.2"}}, "requests_in_retained_transports": sum(run["requests"] for run in runs), "requests_with_retained_reported_usage": len(usage_rows), "priced_request_count": priced, "known_input_tokens": sum(row["input_tokens"] for row in usage_rows), "known_output_tokens": sum(row["output_tokens"] for row in usage_rows), "known_subset_estimate_range_usd": [str(low), str(high)], "actual_total_cost": None, "missing_usage": unknown, "historical_coverage_limit": "早期应用进程重启曾覆盖该实例部分 transport 和事件文件；日志及各次失败目录保留，但不能据此重建全部计费。取消和超时请求可能没有最终 usage。估算区间只覆盖当前保留且可计价的已报告用量，峰谷条件不确定时使用两种公开费率界限。", "budget_and_experience_acceptable": None, "threshold_source": "D05 数值尚未确定", "runs": runs, "workflow_timings": timings}
    (evidence / "usage-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (evidence / "usage-rows.json").write_text(json.dumps(usage_rows, ensure_ascii=False, indent=2))
    (evidence / "validation-code.json").write_text(json.dumps({"at": now(), "files": code}, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in summary.items() if key not in {"runs", "missing_usage", "workflow_timings"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
