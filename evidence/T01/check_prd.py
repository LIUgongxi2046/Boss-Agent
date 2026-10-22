import hashlib
import json
import platform
import re
import subprocess
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt
from referencing import Registry, Resource


root = Path.cwd()
markdown = MarkdownIt("commonmark").enable("table")
prd_path = root / "docs/PRD.md"
prd = prd_path.read_text()
plan = (root / "docs/Boss-Agent项目计划.md").read_text()
requirements_source = (root / "docs/Boss-Agent需求输入.md").read_text()
value = json.loads((root / "specs/value-validation.json").read_text())
probe = json.loads((root / "specs/selection-probe.json").read_text())


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def rows(content):
    result = []
    current = None
    for token in markdown.parse(content):
        if token.type == "tr_open":
            current = []
        elif token.type == "inline" and current is not None:
            current.append(token.content)
        elif token.type == "tr_close":
            result.append(current)
            current = None
    return result


def ids(text, prefix, digits=2):
    return set(re.findall(rf"\b{prefix}[0-9]{{{digits}}}\b", text))


def indexed(items, key):
    mapping = {item[key]: item for item in items}
    require(len(mapping) == len(items), f"重复 identifier：{key}")
    return mapping


# 以原始计划和价值定义确定分母，核查逐功能内容及引用。
source_rows = {row[0]: row for row in rows(plan) if re.fullmatch(r"R[0-9]{2}", row[0])}
mapping_rows = [row for row in rows(prd) if re.fullmatch(r"R[0-9]{2}", row[0])]
mapping = indexed([{"rid": row[0], "cells": row} for row in mapping_rows], "rid")
require(set(source_rows) == set(mapping) == {f"R{i:02d}" for i in range(1, 33)}, "原始承诺覆盖不完整")
hypotheses = indexed(value["hypotheses"], "hypothesis_id")
goals = indexed(value["goals"], "goal_id")
metrics = indexed(value["metrics"], "metric_id")
tokens = markdown.parse(prd)
headings = []
for index, token in enumerate(tokens):
    if token.type == "heading_open":
        headings.append((token.tag, tokens[index + 1].content, token.map[0]))
top = [title for tag, title, line in headings if tag == "h2"]
numbered_headings = [match.group(1) for tag, title, line in headings if (match := re.match(r"([0-9]+(?:\.[0-9]+)*)[. ]", title))]
require(len(numbered_headings) == len(set(numbered_headings)), "章节编号必须唯一")
require(len(top) == 13, "必须具备完整 13 节")
require([int(title.split(".")[0]) for title in top] == list(range(1, 14)), "顶层章节编号不完整")
functions = [(title, line) for tag, title, line in headings if tag == "h3" and re.match(r"8\.[0-9]+ FR-", title)]
require(len(functions) == 32, "逐功能定义数量不完整")
lines = prd.splitlines()
all_ac = set()
for index, (title, start) in enumerate(functions, 1):
    rid, fid, bid, hid = f"R{index:02d}", f"FR-{index:02d}", f"BR-{index:02d}", f"H{index:02d}"
    end = next(line for tag, heading, line in headings if line > start and tag in {"h2", "h3"})
    section = "\n".join(lines[start:end])
    require(title.startswith(f"8.{index} {fid} "), f"功能顺序：{rid}")
    row = mapping[rid]["cells"]
    require(len(row) == 8 and fid in row[1], f"映射字段：{rid}")
    hypothesis = hypotheses[hid]
    require(hid in row[4] and hypothesis["goal_id"] in row[3], f"目标与假设：{rid}")
    require(ids(row[3], "G") <= set(goals), f"未知目标：{rid}")
    require(ids(row[5], "M") == set(hypothesis["metric_ids"]), f"指标继承：{rid}")
    require(set(hypothesis["requirement_ids"]) == {rid}, f"价值需求对应：{rid}")
    for label in [rid, bid, "用户故事", "输入与资料", "结果与结束", "异常", "E01—E06", "页面元素与规则", "BDD 验收"]:
        require(label in section, f"{rid} 缺少 {label}")
    require("本人授权" in section or "本人参与与授权" in section, f"授权定义：{rid}")
    require("需求 " in section and "来源：" in section, f"具体来源：{rid}")
    for suffix in ["S", "E"]:
        aid = f"AC-{index:02d}-{suffix}"
        ac_lines = [line for line in section.splitlines() if line.startswith(f"- {aid}：")]
        require(len(ac_lines) == 1, f"验收定义唯一：{aid}")
        require(all(word in ac_lines[0] for word in ["Given", "When", "Then"]), f"验收动作不完整：{aid}")
        all_ac.add(aid)
    section_rows = rows(section)
    require(any(row == ["元素", "控件", "来源/规则", "必填", "默认"] for row in section_rows), f"元素字段缺少：{rid}")
    require(len(section_rows) >= 10, f"规则或元素内容不足：{rid}")
    require(f"WF-{fid}" in section, f"功能线框缺少：{fid}")
    diagrams = [token for token in markdown.parse(section) if token.type == "fence" and token.info == "mermaid"]
    require(len(diagrams) == 1, f"每个功能需要一个线框：{fid}")
    require("subgraph W[" in diagrams[0].content and "状态：" in diagrams[0].content, f"线框容器或状态缺少：{fid}")

require(ids(prd, "H") == set(hypotheses), "全部假设引用不完整")
require(set(metrics) <= ids(prd, "M"), "指标引用不完整")
for hid in [f"H{i}" for i in range(33, 38)]:
    row = next(row for row in rows(prd) if row[0] == hid)
    require(hypotheses[hid]["goal_id"] == row[1], f"跨需求目标：{hid}")
for count, prefix in [(14, "SI"), (16, "AD")]:
    listed = [row[0] for row in rows(prd) if re.fullmatch(rf"{prefix}[0-9]{{2}}", row[0])]
    require(len(listed) == count and set(listed) == {f"{prefix}{i:02d}" for i in range(1, count + 1)}, f"能力全集：{prefix}")
for marker in ["R19", "肉禽", "蛋禽", "奶畜", "肉用牛羊", "RESULT_SUBMITTED", "COMPLETED_CONFIRMED", "SUPPLEMENT_REQUESTED", "NEEDS_REVIEW", "SNOOZED", "PROFESSIONALLY_CONFIRMED", "INSUFFICIENT_EVIDENCE", "TH-D05", "D07", "D08", "D11", "T02", "T03"]:
    require(marker in prd, f"业务边界或状态缺少：{marker}")
require(len([token for token in tokens if token.type == "fence" and token.info == "mermaid"]) == 52, "四项流程与 48 项线框定义不完整")
for number in range(1, 17):
    heading = f"WF-AD{number:02d} "
    locations = [(title, line) for tag, title, line in headings if tag == "h4" and title.startswith(heading)]
    require(len(locations) == 1, f"管理线框唯一：{heading}")
    start = locations[0][1]
    end = next(line for tag, title, line in headings if line > start)
    diagrams = [token for token in markdown.parse("\n".join(lines[start:end])) if token.type == "fence" and token.info == "mermaid"]
    require(len(diagrams) == 1 and "操作：" in diagrams[0].content and "状态：" in diagrams[0].content, f"管理操作与状态：{heading}")
for marker in ["10.3 六类组件", "10.4 两端", "12.7 需要用户决定", "13.3 原始需求", "Q01", "Q02", "Q03", "D16"]:
    require(marker in prd, f"本次审查要求缺少：{marker}")
syntax = subprocess.run(["node", "evidence/T01/check_mermaid.mjs"], check=True, capture_output=True, text=True)
syntax_result = json.loads(syntax.stdout)
require(syntax_result["parsed_diagrams"] == 52 and syntax_result["rendered"] is False, "Mermaid 语法检查结果")

# 校验实际方法文件及 Schema 引用，不制造业务运行样本。
require(probe["capability"] == "DESIGN" and probe["receiving_task"] == "T02", "验证定义范围")
require(not {"results", "runtime_results", "observed_values", "evidence_ids"} & probe.keys(), "方法文件不能回填运行结果")
for key, authoritative in [("goal_ids", goals), ("hypothesis_ids", hypotheses), ("metric_ids", metrics)]:
    require(set(probe["traceability"][key]) <= set(authoritative), f"方法引用未知：{key}")
require(set(probe["traceability"]["requirement_ids"]) <= set(source_rows), "方法引用未知需求")
require(set(probe["traceability"]["protocol_ids"]) <= {item["protocol_id"] for item in value["protocols"]}, "协议引用")
require(set(probe["traceability"]["threshold_ids"]) <= {item["threshold_id"] for item in value["thresholds"]}, "阈值引用")
schema = probe["io_schema"]
Draft202012Validator.check_schema(schema)
resource = Resource.from_contents(schema)
registry = Registry().with_resource(schema["$id"], resource)
resolver = registry.resolver(schema["$id"])


def check_references(node):
    if isinstance(node, dict):
        if "$ref" in node:
            resolver.lookup(node["$ref"])
        for item in node.values():
            check_references(item)
    elif isinstance(node, list):
        for item in node:
            check_references(item)


check_references(schema)
operations = indexed(probe["operations"], "operation_id")
require(set(operations) == {"query_metrics", "read_evidence", "create_assignment", "send_assignment", "read_assignment"}, "共同任务动作全集")
for operation in operations.values():
    for key in ["input_schema", "output_schema", "error_schema"]:
        target = resolver.lookup(operation[key]).contents
        require(target["type"] == "object" and target["required"], f"输入输出定义：{operation['operation_id']}")
        require(set(target["required"]) <= set(target["properties"]), "Schema 必需字段缺少定义")
assertions = indexed(probe["assertions"], "assertion_id")
steps = indexed(probe["steps"], "step_id")
require(len(assertions) == 37 and len(steps) == 15, "方法步骤及断言数量")
referenced = set()
for step in steps.values():
    require(step["inputs"] and step["outputs"] and step["action"], step["step_id"])
    require(set(step["assertion_ids"]) <= set(assertions), step["step_id"])
    referenced.update(step["assertion_ids"])
require(referenced == set(assertions), "存在未分配步骤的断言")
for assertion in assertions.values():
    require(assertion["method"] and assertion["expected"], assertion["assertion_id"])
    require(set(assertion["prd_ac_ids"]) <= all_ac, f"方法 AC 引用：{assertion['assertion_id']}")
categories = {item["category"] for item in assertions.values()}
require({"restart", "memory", "memory_deletion", "scheduler_owner", "scheduler_controls", "permissions", "authentication", "partial_execution", "reset", "real_model", "configuration"} <= categories, "运行机制断言缺少")
require({"open_source_user_app", "open_source_admin_app", "agent_components"} <= categories, "开源两端与六类组件断言缺少")
require({"desktop_lifecycle", "desktop_permissions"} <= categories, "桌面生命周期与权限断言缺少")
desktop = probe["desktop_definition"]
require(desktop["decision_ref"] == "D17" and desktop["product_form"] == "DESKTOP_APPLICATION", "桌面平台与决定不一致")
require(set(desktop["required_surfaces"]) == {"USER_APP", "ADMIN_APP"}, "桌面两类入口范围")
require({"os", "os_version", "architecture", "desktop_host", "installer_format", "installer_checksum"} <= set(desktop["target_environment_fields"]), "桌面环境字段不完整")
require(set(desktop["window_checks"]) == {"1024x768", "1280x800", "1440x1024", "200% zoom"}, "桌面窗口检查条件")
reuse = probe["open_source_reuse_definition"]
require(set(reuse["required_surfaces"]) == {"RUNTIME", "USER_APP", "ADMIN_APP"}, "开源复用范围")
require(reuse["decision_ref"] == "D16", "复用授权来源")
require(set(reuse["agent_components"]) == {"Prompt", "Workflow/SOP", "Knowledge Base", "LLM/DSLM", "Tools", "Evaluation"}, "六类组件定义")
require({"upstream_repository", "tag_or_commit", "license_file", "source_path", "page_or_api_entry", "reuse_mode", "extension_path", "state_owner", "verification_method"} <= set(reuse["required_mapping_fields"]), "两端复用证据字段")
roles = indexed(probe["initial_materials"]["identity_roles"], "role")
require(roles["BOSS"]["agent_count"] == 1 and roles["CONTACT"]["product_account"] is False and roles["CONTACT"]["agent_count"] == 0, "联系人范围")
fixture = probe["initial_materials"]["numeric_fixture_specification"]
base, current = fixture["base_period"], fixture["current_period"]
gp0 = Decimal(base["revenue_cny"]) - Decimal(base["cost_cny"])
gp1 = Decimal(current["revenue_cny"]) - Decimal(current["cost_cny"])
expected = {
    "quantity_growth_percent": (Decimal(current["quantity_tonnes"]) / Decimal(base["quantity_tonnes"]) - 1) * 100,
    "revenue_growth_percent": (Decimal(current["revenue_cny"]) / Decimal(base["revenue_cny"]) - 1) * 100,
    "gross_profit_change_percent": (gp1 / gp0 - 1) * 100,
    "gross_margin_change_percentage_points": (gp1 / Decimal(current["revenue_cny"]) - gp0 / Decimal(base["revenue_cny"])) * 100,
    "gross_profit_per_tonne_change_percent": ((gp1 / Decimal(current["quantity_tonnes"])) / (gp0 / Decimal(base["quantity_tonnes"])) - 1) * 100,
}
require(all(Decimal(fixture["evaluator_only_expected"][key]) == amount for key, amount in expected.items()), "验证方法中的预期数学关系错误")
require("10,000" in requirements_source and "4,416" in requirements_source, "预期数据来源不匹配")
require(all(value is None for item in value["thresholds"] if item["threshold_id"] == "TH-D05" for value in item["values"].values()), "未知阈值已改变")
require(hypotheses["H35"]["status"] == "INSUFFICIENT_EVIDENCE", "真实采用证据状态")

local_links = 0
external_links = set()
for filename in ["docs/PRD.md", "docs/README.md", "docs/项目决策记录.md", "specs/selection-probe.json"]:
    path = root / filename
    content = path.read_text()
    require(not re.search(r"[\u6808\u843d\u6b7b\u62c6\u504f]|\u5951\u7ea6|不是.*而是|而不是", content), f"语言规则：{filename}")
    if path.suffix != ".md":
        continue
    for token in markdown.parse(content):
        for child in token.children or []:
            if child.type == "link_open":
                address = child.attrGet("href")
                url = urlsplit(address)
                if url.scheme:
                    external_links.add(address)
                else:
                    require((path.parent / unquote(url.path)).resolve().is_file(), f"本地引用缺少：{address}")
                    local_links += 1
require(external_links == {"https://claude.com/product/cowork", "https://learn.microsoft.com/en-us/microsoft-365/copilot/researcher-agent", "https://www.anthropic.com/research/building-effective-agents", "https://www.anthropic.com/research/demystifying-evals-for-ai-agents"}, "外部来源与实际研究集合不一致")
require(hashlib.sha256(requirements_source.encode()).hexdigest() == "854e6e6d49397874d6ed22583b249d753a3caa84135ad20922fab970af1e11e4", "需求输入版本变化，需要重新审阅")
print(json.dumps({
    "check_id": "K01", "kind": "STATIC", "capability": "DESIGN",
    "scope": "完整需求映射、规则、BDD、方法 Schema、引用及语义审阅依据；未执行产品业务",
    "requirements": len(mapping), "functional_requirements": len(functions),
    "bdd_acceptance_definitions": len(all_ac), "secretary_tasks": 13,
    "agriculture_topics": 10, "shared_capabilities": 9, "goal_ids": list(goals),
    "hypotheses": len(hypotheses), "metrics": len(metrics),
    "simulation_interfaces": 14, "management_capabilities": 16,
    "functional_wireframes": 32, "management_wireframes": 16,
    "mermaid_syntax": syntax_result,
    "probe_steps": len(steps), "probe_assertions": len(assertions),
    "probe_schema_definitions": len(schema["$defs"]), "local_links_checked": local_links,
    "external_sources": sorted(external_links),
    "semantic_review": "docs/PRD.md 第 13.2 节",
    "business_execution": "NOT_RUN", "visual": "NOT_RUN",
    "python": platform.python_version(), "markdown_it_py": version("markdown-it-py"),
    "jsonschema": version("jsonschema"),
}, ensure_ascii=False, indent=2))
