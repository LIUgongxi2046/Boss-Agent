import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
directory = Path(__file__).parent
price_path = directory / "deepseek-price-20261023.json"
price = json.loads(price_path.read_text())
assert price["model"] == "deepseek-flash" and price["currency"] == "CNY"
files = sorted(directory.glob("deepseek-*/http-requests.json"))
files.extend(ROOT / "evidence" / "T15" / "w2-20261023" / name for name in (
    "before-sample-deletion.json", "after-sample-deletion.json",
))
rows = []
observed_response_ids = set()
for path in files:
    events = json.loads(path.read_text())
    observed = {}
    for event in events:
        if event["type"] == "stream_metadata" and event.get("usage") is not None:
            assert event["model"] == price["model"]
            observed[event["response_id"]] = event["usage"]
    request_count = sum(event["type"] == "request" for event in events)
    assert request_count == len(observed)
    tokens = {name: 0 for name in price["off_peak"]}
    for response_id, usage in observed.items():
        assert response_id not in observed_response_ids
        observed_response_ids.add(response_id)
        for name in tokens:
            assert type(usage[name]) is int and usage[name] >= 0
            tokens[name] += usage[name]
        assert usage["prompt_cache_hit_tokens"] + usage["prompt_cache_miss_tokens"] == usage["prompt_tokens"]
        assert usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"]
    costs = {
        period: str(sum(Decimal(tokens[name]) * Decimal(rates[name]) for name in tokens)
                    / Decimal(price["unit_tokens"]))
        for period, rates in (("minimum_cny", price["off_peak"]), ("maximum_cny", price["peak"]))
    }
    rows.append({
        "source": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "request_count": request_count, "tokens": tokens, "current_price_estimate": costs,
    })
report = {
    "status": "PASS_OBSERVED_USAGE_CALCULATION_ONLY", "currency": price["currency"],
    "price_version": price["price_version"], "price_source": price["source_url"],
    "price_sha256": hashlib.sha256(price_path.read_bytes()).hexdigest(),
    "scope": "四次五工具多轮任务和两次获准样本记忆请求",
    "request_count": sum(row["request_count"] for row in rows), "rows": rows,
    "observed_scope_estimate_cny": {
        name: str(sum(Decimal(row["current_price_estimate"][name]) for row in rows))
        for name in ("minimum_cny", "maximum_cny")
    },
    "all_attempts_total_cost": None, "billing_statement_verified": False,
    "coverage": "PARTIAL_OBSERVED_USAGE_ONLY",
    "missing_coverage": ["取消、超时及其他异常请求的完整usage", "其他检查请求", "账单及当次实际计费时段"],
}
output = directory / "w2-20261023-observed-cost.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({key: report[key] for key in (
    "status", "request_count", "observed_scope_estimate_cny", "all_attempts_total_cost", "coverage",
)}, ensure_ascii=False))
