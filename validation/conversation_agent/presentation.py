from business import require
from conversation_agent.queries import METRICS
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo


METRIC_NAMES = {value: key for key, value in reversed(list(METRICS.items()))}
PERIOD_NAMES = {"CURRENT": "查询期间", "BASE": "比较期间", "CHANGE": "期间变化"}


def morning_brief(view, contacts=()):
    names = {item["contact_id"]: item["name"] for item in contacts}
    names["boss-1"] = "本人"
    clock = datetime.fromisoformat(view["business_clock"])
    zone = ZoneInfo(view["timezone"])
    categories = {"DECIDE": "需要决定", "COORDINATE": "需要协调", "INFORM": "需要知晓"}
    suggestions = {"DECIDE": "核对申请和依据，选择同意、驳回或交给秘书核查。",
                   "COORDINATE": "明确下一步、负责人和反馈时间；需要时交给秘书跟进。",
                   "INFORM": "了解相关情况，如需采取行动，请明确负责人和期限。"}

    def deadline(item):
        value = item["due_at"] or item["starts_at"]
        return datetime.fromisoformat(value) if value else None

    def priority(item):
        due = deadline(item)
        return (0 if due and due < clock else 1 if item["important"] else 2,
                due.timestamp() if due else float("inf"), item["item_id"])

    items = sorted(view["items"], key=priority)
    counts = {key: sum(item["category"] == key for item in items) for key in categories}
    lines = ["按 " + view["date"] + " 的当前资料，" + "、".join(categories[key] + " " + str(counts[key]) + " 项" for key in categories) + "。",
             "处理顺序依据已过期限、重要标记和最近期限；当前资料未确认的业务影响不作推断。"]
    if not items:
        return lines + ["当前没有需要处理的事项。"]
    for item in items:
        due = deadline(item)
        local_due = due.astimezone(zone) if due else None
        timing = "尚未约定期限" if local_due is None else f"{local_due.month:02d}月{local_due.day:02d}日 {local_due.hour:02d}:{local_due.minute:02d}"
        urgency = "已过期限，请优先核查进展" if due and due < clock else "已标记重要，请优先关注" if item["important"] else "按最近约定期限安排" if due else "先确认处理期限"
        coordinator = item["coordinator_id"]
        owner = names.get(coordinator, "当前负责人") if coordinator else "负责人待确认"
        action = "由本人完成承诺，并确认相关结果。" if item["kind"] == "self_commitment" else suggestions[item["category"]]
        lines.extend(["### " + item["title"],
                      "**" + categories[item["category"]] + "** · " + owner + " · " + timing,
                      "关注原因：" + item["reason"] + "。" + urgency + "。",
                      "建议处理：" + action])
    lines.append("以上处理建议尚未执行。可以在今日工作中选择事项，确认同意、驳回、交给秘书或让 Boss Agent 继续分析。")
    return lines


def excerpt(value):
    require(isinstance(value, str), "当前可读内容需要正式文字")
    return value[:1600] + ("\n完整内容请通过正式详情读取。" if len(value) > 1600 else "")


def sources(items):
    return ["来源：" + item["source_id"] + "，版本 " + item["version"]
        + ("，作者 " + item["author_contact_id"] if item.get("author_contact_id") else "")
        + ("，发布时间 " + item["published_at"] if item.get("published_at") else "") for item in items]


def query_text(data):
    scope = data["context_snapshot"]
    lines = ["查询编号：" + data["query_id"], "查询期间：" + scope["period_start"] + " 至 " + scope["period_end"]
        + "；比较期间：" + scope["comparison_start"] + " 至 " + scope["comparison_end"],
        "当前范围：区域 " + ", ".join(scope.get("region_ids", [scope["region_id"]]))
        + "；产品 " + ", ".join(scope["product_ids"]) + "；口径 " + scope["business_basis"]]
    for value in data["values"]:
        lines.append(PERIOD_NAMES[value["period_scope"]] + " · " + METRIC_NAMES[value["metric_id"]] + "："
            + (value["value"] + " " + value["unit"] if value["value"] is not None else "当前资料无法确定"))
    lines.extend(sources(data["sources"]))
    lines.append("比较状态：" + data["comparison"]["state"])
    if data["comparison"]["reasons"]:
        lines.append("比较限制：" + "、".join(data["comparison"]["reasons"]))
    if data["missing_fields"]:
        lines.append("资料缺口：" + "、".join(data["missing_fields"]))
    lines.extend(data["unexplained_causes"])
    return lines


def object_text(kind, data):
    if kind == "query":
        return query_text(data)
    if kind in {"message", "message_draft"}:
        lines = ["消息对象：" + str(data.get("message_id") or data["draft_id"]) + "；收件人 " + data["recipient_id"],
            "当前状态：" + str(data.get("send_state") or data.get("status") or data.get("message_status"))]
        if data.get("body") is not None:
            lines.append(excerpt(data["body"]))
        lines.extend(sources(data.get("attachment_refs", [])))
        return lines
    if kind == "task":
        states = {"OPEN": "待决定", "WAITING_FEEDBACK": "等待反馈", "IN_PROGRESS": "执行中", "WAITING_MATERIAL": "等待材料", "RESULT_SUBMITTED": "待验收", "COMPLETED_CONFIRMED": "已完成", "CANCELED": "已取消"}
        advice = {"OPEN": "核对交办内容，确认后发送给负责人。", "WAITING_FEEDBACK": "请负责人反馈当前进展和预计完成时间。", "IN_PROGRESS": "关注约定期限，请负责人提交阶段进展。", "WAITING_MATERIAL": "请负责人补充所需材料后继续处理。", "RESULT_SUBMITTED": "查看提交结果和相关材料，再确认完成情况。", "COMPLETED_CONFIRMED": "任务已经确认完成，可以查看相关结果。", "CANCELED": "任务已经取消，已有记录继续保留。"}
        due = datetime.fromisoformat(data["due_at"]).astimezone(ZoneInfo(data["timezone"]))
        return ["### " + data["purpose"], "当前进展：" + states[data["status"]],
            "约定期限：" + due.strftime("%Y-%m-%d %H:%M"),
            "已收到反馈：" + str(len(data["feedback_ids"])) + " 条。",
            "建议：" + advice[data["status"]], "可以返回交办页面核对材料并确认具体处理操作。"]
    require(kind == "morning_list", "当前产物种类没有正式文字呈现方式")
    return ["晨间清单当前顺序版本：" + data["current_order"]["version"],
        "事项编号：" + "、".join(data["current_order"]["item_ids"])]


def result_text(name, data):
    if name == "bossDashboardRead":
        return morning_brief(data["today"], data["contacts"])
    if name == "bossTasksRead":
        lines = ["当前任务 " + str(len(data["tasks"])) + " 项。"]
        for task in sorted(data["tasks"], key=lambda row: row["due_at"]):
            lines.extend(object_text("task", task))
        return lines
    if name == "businessOverviewRead":
        scope = data["applied_scope"]
        lines = ["查询期间：" + scope["period_start"] + " 至 " + scope["period_end"]]
        topics = [data["topic"]] if "topic" in data else data["topics"]
        if "topic_reference" in data and data["topic_reference"]["use"]:
            lines.append("业务类型：" + {"BROILER": "肉禽", "EGG": "蛋禽", "MILK": "奶畜", "BEEF": "肉用牛羊"}[data["topic_reference"]["use"]])
        for topic in topics:
            lines.append("### " + topic["title"])
            for metric in topic["metrics"]:
                change = metric["change_percent"]
                comparison = "；尚无上月比较数据" if change is None else "；较上月" + ("增加 " if Decimal(change) >= 0 else "减少 ") + str(abs(Decimal(change))) + "%"
                lines.append(metric["label"] + "：" + metric["value"] + " " + metric["unit"] + comparison)
            if topic["metrics"]:
                lines.append("建议核查变化较大的指标，结合采购、销售或生产记录确认原因，再确定负责人和处理期限。当前数值可以说明变化，原因仍需相关材料支持。")
            else:
                lines.append("当前期间没有可用的专题指标，请补充相应业务材料后继续分析。")
        if "metrics" in data:
            lines.append("### 水产饲料外销")
            lines.extend(METRIC_NAMES[row["metric_id"]] + "：" + (row["value"] + " " + row["unit"] if row["value"] is not None else "当前资料无法确定") for row in data["metrics"])
        return lines
    if name == "query_metrics":
        return query_text(data)
    if name == "bossEvidenceRead":
        return sources([data]) + ["原文节选：" + excerpt(data["content"])]
    if name == "conversationRead":
        if "kind" in data:
            return object_text(data["kind"], data["data"])
        if "attachments" in data:
            lines = ["当前保存附件：" + str(len(data["attachments"])) + " 项。"]
            for item in data["attachments"]:
                lines.append("附件：" + (item["original_name"] or item["stored_name"] or item["attachment_id"])
                    + "；类型 " + (item["mime_type"] or "未知") + "；状态 " + item["processing_state"]
                    + "；大小 " + (str(item["size_bytes"]) + " bytes" if item["size_bytes"] is not None else "未知")
                    + "；编号 " + item["attachment_id"])
            lines.append("已保存元信息；业务正文处理与正式来源资格需要相应有效依据。")
            return lines
        if "runs" in data:
            return ["当前会话运行：" + str(len(data["runs"])) + " 项。"] + ["运行 " + item["run_id"]
                + "；状态 " + item["status"] + "；工具步骤 " + str(len(item["tool_steps"])) for item in data["runs"]]
        require(data.get("projection") == "conversation-messages", "当前会话投影没有正式文字呈现方式")
        lines = ["本人消息历史：草稿 " + str(len(data["drafts"])) + " 项，已发送 " + str(len(data["sent_messages"])) + " 项，回复 " + str(len(data["replies"])) + " 项。"]
        lines.extend("联系人：" + item["name"] + "；编号 " + item["contact_id"] + "；组织 " + item["organization"]
            + "；职责 " + item["responsibility"] for item in data["contacts"])
        for kind, items in (("message_draft", data["drafts"]), ("message", data["sent_messages"])):
            for item in items:
                lines.extend(object_text(kind, item))
        for item in data["replies"]:
            lines.append("回复 " + item["reply_id"] + "，对应消息 " + item["reply_to"])
            if item["text"] is not None:
                lines.append(excerpt(item["text"]))
        return lines
    if name == "bossSectorRead":
        lines = [data["page_id"] + " · " + data["title"] + "；读取时间：" + data["read_at"]]
        for metric in data["metrics"]:
            lines.append(metric["label"] + "：" + (str(metric["value"]) + " " + metric["unit"]
                         if metric["value"] is not None else "当前资料无法确定"))
        lines.append("明细：" + str(len(data["records"])) + " 条；来源：" + str(len(data["sources"])) + " 项。")
        lines.extend("资料缺口：" + value for value in data["missing_fields"])
        return lines
    titles = {"bossDashboardRead": "当前概览", "bossTasksRead": "当前任务", "bossMeetingsRead": "当前会议", "bossWorkspaceRead": "当前工作事项"}
    require(name in titles, "当前工具没有正式文字呈现方式")
    lines = [titles[name] + ("：" + data["projection"] if "projection" in data else "。")]
    for field, value in data.items():
        if isinstance(value, list):
            lines.append(field + "：" + str(len(value)) + " 项。")
            for item in value:
                if isinstance(item, str):
                    lines.append(excerpt(item))
                elif isinstance(item, dict):
                    visible = [key + "=" + str(item[key]) for key in ("task_id", "meeting_id", "notification_id", "event_id", "title", "status", "version", "starts_at", "due_at") if isinstance(item.get(key), (str, int))]
                    if visible:
                        lines.append("；".join(visible))
    return lines


def render_conversation(calls, outputs, required_inputs):
    lines = ["以下内容依据当前保存的模拟资料。"]
    for (name, _), output in zip(calls, outputs, strict=True):
        lines.extend(result_text(name, output))
    lines.extend("待补充：" + value for value in required_inputs)
    return "\n\n".join(lines)
