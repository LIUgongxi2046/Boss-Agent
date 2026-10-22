import hashlib
import json
import platform
import re
from importlib.metadata import version
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt


root = Path.cwd()
value = json.loads((root / "specs/value-validation.json").read_text())
markdown = MarkdownIt("commonmark").enable("table")
plan = (root / "docs/Boss-Agent项目计划.md").read_text()
prd = plan
decisions = (root / "docs/项目决策记录.md").read_text()
review = plan


def indexed(items, key):
    result = {item[key]: item for item in items}
    assert len(result) == len(items), key
    return result


def table_rows(content):
    rows = []
    row = None
    for token in markdown.parse(content):
        if token.type == "tr_open":
            row = []
        elif token.type == "inline" and row is not None:
            row.append(token.content)
        elif token.type == "tr_close":
            rows.append(row)
            row = None
    return rows


text_field = {"type": "string", "minLength": 1}
ids_field = {"type": "array", "minItems": 1, "uniqueItems": True, "items": text_field}
hypothesis_properties = {
    key: text_field
    for key in [
        "hypothesis_id", "goal_id", "statement", "protocol_id",
        "sample_conditions", "success_condition",
    ]
}
hypothesis_properties.update({
    key: ids_field
    for key in [
        "requirement_ids", "source_refs", "metric_ids", "threshold_ids",
        "validation_tasks", "acceptance_ids",
    ]
})
hypothesis_properties.update({
    "source_type": {"enum": ["EXPLICIT", "INFERRED", "UNKNOWN"]},
    "confidence": {"enum": ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]},
    "status": {"enum": ["NOT_RUN", "INSUFFICIENT_EVIDENCE"]},
    "observed_values": {"type": "null"},
    "evidence_ids": {"type": "array", "maxItems": 0},
})
schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "goals", "hypotheses", "metrics", "sources", "protocols", "thresholds",
        "common_protocol", "resource_inputs", "handoffs", "review_conditions",
    ],
    "properties": {
        "hypotheses": {
            "type": "array", "minItems": 37, "maxItems": 37,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": list(hypothesis_properties),
                "properties": hypothesis_properties,
            },
        },
    },
}
Draft202012Validator.check_schema(schema)
Draft202012Validator(schema).validate(value)
goals = indexed(value["goals"], "goal_id")
hypotheses = indexed(value["hypotheses"], "hypothesis_id")
metrics = indexed(value["metrics"], "metric_id")
protocols = indexed(value["protocols"], "protocol_id")
thresholds = indexed(value["thresholds"], "threshold_id")
sources = indexed(value["sources"], "source_id")
handoffs = indexed(value["handoffs"], "handoff_id")
requirements = {f"R{number:02d}" for number in range(1, 33)}
assert set(goals) == {f"G{number:02d}" for number in range(1, 5)}
assert set(hypotheses) == {f"H{number:02d}" for number in range(1, 38)}
assert set(metrics) == {f"M{number:02d}" for number in range(1, 18)}
assert len(protocols) == 8 and len(thresholds) == 4 and len(handoffs) == 3
assert value["execution_mode"] == "ASSESS"
assert value["scope_mode"] == "HOLD SCOPE"
assert value["capability"] == "DESIGN"

# 使用 Markdown 解析结果核查计划与价值映射的完整集合。
plan_rows = {row[0]: row for row in table_rows(plan) if re.fullmatch(r"R\d{2}", row[0])}
mapping_rows = {
    row[0].split(" / ")[0]: row
    for row in table_rows(prd)
    if re.match(r"R\d{2} / H\d{2} /", row[0])
}
assert set(plan_rows) == requirements == set(mapping_rows)
assert len([row for row in table_rows(prd) if re.match(r"R\d{2} / H\d{2} /", row[0])]) == 32
task_ids = set(re.findall(r"^### (T\d{2})\s", plan, re.MULTILINE))
acceptance_ids = set(re.findall(r"\bA\d{2}[a-d]?\b", plan))
assert task_ids == {f"T{number:02d}" for number in range(27)}
assert {"A00", "A01", "A04", "A09", "A24", "A26"} <= acceptance_ids
for number in range(1, 33):
    rid, hid = f"R{number:02d}", f"H{number:02d}"
    item = hypotheses[hid]
    row = mapping_rows[rid]
    assert len(row) == 5 and all(cell.strip() for cell in row), rid
    assert hid in row[0] and item["goal_id"] in row[0], rid
    assert item["requirement_ids"] == [rid], rid
    assert "S01" in row[3] and "T" in row[4] and "A" in row[4], rid
    if number <= 13:
        assert item["protocol_id"] == "VP-SECRETARY", hid
    elif number <= 23:
        assert item["protocol_id"] == "VP-AGRICULTURE", hid

for item in hypotheses.values():
    assert item["goal_id"] in goals
    assert set(item["requirement_ids"]) <= requirements
    assert set(item["metric_ids"]) <= metrics.keys()
    assert item["protocol_id"] in protocols
    assert set(item["threshold_ids"]) <= thresholds.keys()
    assert set(item["validation_tasks"]) <= task_ids
    assert set(item["acceptance_ids"]) <= acceptance_ids
    assert all(ref.split(":")[0] in sources for ref in item["source_refs"])
    assert item["hypothesis_id"] in prd or int(item["hypothesis_id"][1:]) >= 33
    assert item["observed_values"] is None and not item["evidence_ids"]
    resolved = value["common_protocol"] | protocols[item["protocol_id"]]
    for field in [
        "sample_conditions", "environment_conditions", "human_baseline_method",
        "validation_period", "period_basis", "sample_size_rule", "success_condition",
        "stop_condition", "threshold_decision_source", "data_collection",
        "evidence_requirements", "reevaluation_conditions",
    ]:
        assert resolved[field], (item["hypothesis_id"], field)

for item in metrics.values():
    for field in ["name", "definition", "unit", "formula", "human_baseline_method", "collection", "limitations"]:
        assert isinstance(item[field], str) and item[field].strip(), (item["metric_id"], field)
    assert item["observed_value"] is None
for item in protocols.values():
    for field in ["sample_conditions", "environment_conditions", "validation_period", "period_basis", "success_condition", "stop_condition"]:
        assert item[field], (item["protocol_id"], field)
    assert set(item["validation_tasks"]) <= task_ids
    assert set(item["acceptance_ids"]) <= acceptance_ids
for item in goals.values():
    assert item["status"] == "CONFIRMED" and item["effect_status"] == "NOT_RUN"
assert all(number is None for number in thresholds["TH-D05"]["values"].values())
assert thresholds["TH-D06"]["status"] == "CONFIRMED_CONSTRAINT"
assert thresholds["TH-D06"]["values"]["delivery_window_days"] == 2
assert thresholds["TH-D06"]["values"]["deadline"] is None
assert thresholds["TH-D06"]["values"]["deployment_target"] == "LOCAL_COMPUTER"
assert all(number == 0 for number in thresholds["TH-QUALITY"]["values"].values())
assert hypotheses["H35"]["status"] == "INSUFFICIENT_EVIDENCE"
assert hypotheses["H35"]["protocol_id"] == "VP-USER"
assert value["common_protocol"]["observed_values"] is None
assert value["common_protocol"]["evidence_ids"] == []
assert "M01—M10" in value["common_protocol"]["task_metric_coverage"]
resources = value["resource_inputs"]
assert resources["estimated_total_person_days"] == [48, 74]
assert resources["estimated_total_person_hours"] == [288, 444]
assert resources["actual_cost"] is None and resources["budget"] is None
assert resources["delivery_window_days"] == 2
assert resources["deployment_target"] == "LOCAL_COMPUTER"
assert resources["product_form"] == "DESKTOP_APPLICATION"
assert resources["desktop_scope"]["decision_ref"] == "D17"
assert resources["desktop_scope"]["evidence_status"] == "NOT_RUN"
assert resources["existing_api_allowed"] is True and resources["offline_only"] is False
assert resources["feasibility_status"] == "NOT_RUN"
assert "两天" in decisions and "两天" in prd and "两天" in plan
assert "已有 GPT、DeepSeek 和语音 API" in decisions
assert len(resources["cost_formulas"]) == 9
assert {item["receiving_task"] for item in handoffs.values()} == {"T01", "T04", "T09"}
for item in handoffs.values():
    assert item["receiving_task"] in task_ids
    assert set(item["validation_tasks"]) <= task_ids
    assert set(item["acceptance_ids"]) <= acceptance_ids
    assert item["evidence_requirement"] and item["handoff_id"] in prd

for review_id in value["review_conditions"]["review_ids"]:
    assert review_id in prd
for number in range(1, 10):
    assert f"F{number:02d}" in prd
for section in ["### 11.1 ", "### 11.2 ", "### 11.3 ", "### 11.4 ", "### 11.5 ", "### 11.6 ", "### 11.7 ", "### 11.8 ", "### 11.9 ", "#### 11.9.1 ", "#### 11.9.2 ", "### 11.10 ", "### 11.11 ", "## 12. "]:
    assert section in prd, section
assert "[DONE_WITH_CONCERNS]" in prd
assert "TH-D05" in decisions and "M01—M17" in decisions
assert all(f"| D{number:02d} |" in decisions for number in range(1, 16))
assert "老板为唯一业务使用者" in decisions
assert "H35" in review and "STATIC" in review

# 读取全部本地链接，并检查新产物的措辞及未知值。
documents = [
    "docs/Boss-Agent项目计划.md", "docs/项目决策记录.md",
    "docs/README.md", "docs/计划环境记录.md",
]
link_count = 0
for name in documents:
    path = root / name
    content = path.read_text()
    assert not re.search("[\u6808\u843d\u6b7b\u62c6\u504f]|\u5951\u7ea6|不是.*而是|而不是", content), name
    for token in markdown.parse(content):
        for child in token.children or []:
            if child.type == "link_open":
                url = urlsplit(child.attrGet("href"))
                assert not url.scheme and not url.netloc, name
                assert (path.parent / unquote(url.path)).resolve().is_file(), (name, url.path)
                link_count += 1
source_hash = hashlib.sha256((root / "docs/Boss-Agent需求输入.md").read_bytes()).hexdigest()
assert source_hash == "854e6e6d49397874d6ed22583b249d753a3caa84135ad20922fab970af1e11e4"
print(json.dumps({
    "check_id": "K00", "scope": "战略设计及文档引用，业务效果未验证",
    "requirements": len(mapping_rows), "secretary_tasks": 13, "agriculture_topics": 10,
    "shared_capabilities": 9, "goals": len(goals), "hypotheses": len(hypotheses),
    "metrics": len(metrics), "protocols": len(protocols), "handoffs": len(handoffs),
    "review_dimensions": 5, "external_perspectives": 4,
    "observed_values_unknown": True, "requirement_source_sha256": source_hash,
    "local_links_checked": link_count, "python": platform.python_version(),
    "markdown_it_py": version("markdown-it-py"), "jsonschema": version("jsonschema"),
    "semantic_review": "docs/Boss-Agent项目计划.md 第 12 节",
}, ensure_ascii=False, indent=2))
