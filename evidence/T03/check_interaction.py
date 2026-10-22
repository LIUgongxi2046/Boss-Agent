import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


root = Path.cwd()
document = root / "docs/交互与页面规范.md"
content = document.read_text()
prd = (root / "docs/PRD.md").read_text()
markdown = MarkdownIt("commonmark").enable("table")

assert all(marker in content for marker in ["D17", "电脑桌面应用", "1024×768", "1280×800", "1440×1024", "200%", "系统麦克风权限", "IPC"])
assert "360、768、1280、1440" not in content


def require(condition, message):
    if not condition:
        raise ValueError(message)


def table_rows(source):
    rows = []
    current = None
    for token in markdown.parse(source):
        if token.type == "tr_open":
            current = []
        elif token.type == "inline" and current is not None:
            current.append(token.content)
        elif token.type == "tr_close":
            rows.append(current)
            current = None
    return rows


tokens = markdown.parse(content)
rows = table_rows(content)
source_tokens = markdown.parse(prd)
source_ids = {
    match.group(0)
    for token in source_tokens
    if token.type == "inline" and token.content.startswith("WF-")
    for match in [re.match(r"WF-(?:FR-[0-9]{2}|AD[0-9]{2})", token.content)]
    if match
}
expected_ids = {f"WF-FR-{index:02d}" for index in range(1, 33)} | {
    f"WF-AD{index:02d}" for index in range(1, 17)
}
require(source_ids == expected_ids, "PRD 来源分母必须为 32 个 FR 和 16 个 AD")
screen_rows = [row for row in rows if row[0] in source_ids]
screens = {row[0]: row for row in screen_rows}
require(len(screen_rows) == len(screens) == 48, "来源区域必须唯一且全部覆盖")
require(set(screens) == source_ids, "存在未覆盖来源线框")

operations = {
    row[0]: row
    for row in rows
    if re.fullmatch(r"O[0-9]{2} .+", row[0])
}
operation_ids = {key[:3] for key in operations}
require(operation_ids == {f"O{index:02d}" for index in range(1, 36)}, "操作目录不完整")
require(all(len(row) == 4 and all(row) for row in operations.values()), "操作需要输入授权、反馈与取消结果")
states = {row[0]: row for row in rows if re.fullmatch(r"S[0-9]{2} .+", row[0])}
require({key[:3] for key in states} == {f"S{index:02d}" for index in range(11)}, "通用状态矩阵不完整")
require(all(len(row) == 4 and all(row) for row in states.values()), "状态需要触发、恢复和可访问反馈")
pages = {row[0]: row for row in rows if re.fullmatch(r"[BM][0-9]{2}", row[0])}
overlays = {row[0]: row for row in rows if re.fullmatch(r"X[0-9]{2} .+", row[0])}
overlay_ids = {key[:3] for key in overlays}
require(overlay_ids == {f"X{index:02d}" for index in range(1, 7)}, "详情与系统区域不完整")
require(set(pages) == {f"B{index:02d}" for index in range(1, 7)} | {f"M{index:02d}" for index in range(1, 5)}, "两类入口目录不完整")
bindings = {row[0]: row for row in rows if re.fullmatch(r"[UA][0-9]{2}", row[0])}
require(set(bindings) == {f"U{index:02d}" for index in range(1, 7)} | {f"A{index:02d}" for index in range(1, 18)}, "复用绑定目录不完整")
require(all(row[-1] == "PENDING_T02" for row in bindings.values()), "没有 T02 证据不能声称实现绑定")
require(not (root / "docs/选型验证.md").exists(), "T02 证据已出现，需要重新核查绑定")

source_ac = set(re.findall(r"\bAC-[0-9]{2}-[SE]\b", prd))
require(len(source_ac) == 64, "PRD 验收分母变化")
seen_ac = set()
used_operations = set()
field_checks = []
source_lines = prd.splitlines()
for source_id, row in screens.items():
    require(len(row) == 6 and all(row), f"区域映射字段缺少：{source_id}")
    refs = set(re.findall(r"\bO[0-9]{2}\b", row[3]))
    require(bool(refs) and refs <= operation_ids, f"操作引用无效：{source_id}")
    used_operations.update(refs)
    page_refs = set(re.findall(r"\b[BMUX][0-9]{2}\b", row[1]))
    require(bool(page_refs), f"页面及绑定缺少：{source_id}")
    for ref in page_refs:
        require(ref in pages or ref in bindings or ref in overlay_ids, f"未知页面绑定：{source_id} {ref}")
    ac = set(re.findall(r"\bAC-[0-9]{2}-[SE]\b", row[-1]))
    require(ac <= source_ac, f"验收引用不在 PRD 中：{source_id}")
    seen_ac.update(ac)
    if source_id.startswith("WF-FR-"):
        number = int(source_id[-2:])
        require({f"AC-{number:02d}-S", f"AC-{number:02d}-E"} <= ac, f"正常及异常 AC 缺少：{source_id}")
        heading = next(
            token for index, token in enumerate(source_tokens[:-1])
            if token.type == "heading_open" and source_tokens[index + 1].content == f"8.{number}.1 页面元素与规则"
        )
        end = next(token.map[0] for token in source_tokens if token.type == "heading_open" and token.map[0] > heading.map[0])
        elements = table_rows("\n".join(source_lines[heading.map[0]:end]))[1:]
        row_text = " ".join(row)
        missing = [element[0] for element in elements if not all(part in row_text for part in element[0].split("/"))]
        field_checks.append({"source_id": source_id, "missing_element_labels": missing})
    else:
        require({"AC-26-S", "AC-26-E"} <= ac, f"管理区域通用 AC 缺少：{source_id}")
require(seen_ac == source_ac, "64 项验收引用不完整")
require(used_operations == operation_ids, f"来源区域操作引用需要补充：{sorted(operation_ids - used_operations)}")

for token in tokens:
    for child in token.children or []:
        if child.type == "link_open":
            url = urlsplit(child.attrGet("href"))
            require(not url.scheme, "当前规范只引用本地输入和产物")
            target = (document.parent / unquote(url.path)).resolve(strict=True)
            require(target.is_file(), f"引用文件不存在：{target}")

for marker in ["J01", "J02", "J03", "J04", "J05", "E01", "E02", "E03", "E04", "E05", "E06", "RECONCILING", "COMPLETED_CONFIRMED", "RESULT_SUBMITTED", "肉禽", "蛋禽", "奶畜", "肉用牛羊", "aria-busy", "aria-describedby", "200%", "T08", "T18", "T19", "T20", "BLOCKED", "NOT_RUN", "INFERRED", "UNKNOWN"]:
    require(marker in content, f"关键设计条件缺少：{marker}")
require("已有有效授权直接执行" in content or "已明确且有效直接执行" in content, "既有授权执行条件缺少")
require("无批准或确认完成按钮" in screens["WF-AD14"][4], "后台确认边界缺少")
require("本人内容修改仅在 B06" in screens["WF-AD12"][4], "记忆维护边界缺少")
require("无声" in screens["WF-FR-27"][4] or "无声" in content, "真实语音异常缺少")
require("不完整总额 null" in screens["WF-FR-30"][4], "未知费用规则缺少")
require("观察过期" in screens["WF-FR-20"][4], "农业时间状态缺少")
require(not any(chr(codepoint) in content for codepoint in [0x6808, 0x843D, 0x6B7B, 0x62C6, 0x504F]), "文档包含禁止用字")

# 清单由实际 Markdown 映射导出，仅用于检查文字产物引用。
audit_root = root / ".planning-checks/t03-ui-audit"
audit_root.mkdir(exist_ok=True)
(audit_root / "ui-audit.md").write_text("# T03 文字产物检查\n\n来源为 docs/交互与页面规范.md；48 个来源区域均为文字定义，交互和视觉为 NOT_RUN。\n")
with (audit_root / "screen-design-map.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=["source_id", "screen_id", "name", "source_type", "status", "artifact_path", "requirement_refs", "required_states"])
    writer.writeheader()
    for source_id, row in screens.items():
        writer.writerow({"source_id": source_id, "screen_id": source_id, "name": row[1], "source_type": "EXPLICIT", "status": "CREATED", "artifact_path": str(document), "requirement_refs": row[-1], "required_states": ";".join(sorted(key[:3] for key in states))})
audit_python = "/Users/liuhaoxian/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
audit_command = [audit_python, "/Users/liuhaoxian/.agents/skills/haonan-s003-2-ui/scripts/audit_ui_delivery.py", str(audit_root), "--mode", "audit", "--source-root", str(root)]
audit = subprocess.run(audit_command, check=True, text=True, capture_output=True)
audit_result = json.loads(audit.stdout)
require(audit_result["screens"] == 48 and audit_result["assets"] == 0, "文字产物数量与范围不一致")
require(audit_result["interaction_verified"] is False and audit_result["visual_verified"] is False, "不能将文字引用检查登记为功能或视觉通过")

result = {
    "capability": "DESIGN", "kind": "STATIC", "source_screens": 48,
    "mapped_screens": len(screens), "missing_screens": sorted(source_ids - screens.keys()),
    "fr_count": 32, "ac_count": len(seen_ac), "admin_count": 16,
    "boss_entries": 6, "operation_count": len(operations), "state_count": len(states),
    "pending_t02_bindings": len(bindings), "full_acceptance": "BLOCKED",
    "field_label_review": field_checks, "ui_structure_audit": audit_result,
    "interaction": "NOT_RUN", "visual": "NOT_RUN",
}
print(json.dumps(result, ensure_ascii=False, indent=2))
require(not any(item["missing_element_labels"] for item in field_checks), "逐项元素名称检查需要处理")
