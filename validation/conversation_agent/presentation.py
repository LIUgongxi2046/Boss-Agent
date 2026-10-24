from business import require
from conversation_agent.queries import METRICS


METRIC_NAMES = {value: key for key, value in reversed(list(METRICS.items()))}
PERIOD_NAMES = {"CURRENT": "查询期间", "BASE": "比较期间", "CHANGE": "期间变化"}


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
        return ["任务编号：" + data["task_id"] + "；版本 " + data["version"] + "；状态 " + data["status"]]
    require(kind == "morning_list", "当前产物种类没有正式文字呈现方式")
    return ["晨间清单当前顺序版本：" + data["current_order"]["version"],
        "事项编号：" + "、".join(data["current_order"]["item_ids"])]


def result_text(name, data):
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
    lines = ["数据类型：SIMULATED；运行与附件元信息来自当前正式记录。"]
    for (name, _), output in zip(calls, outputs, strict=True):
        lines.extend(result_text(name, output))
    lines.extend("待补充：" + value for value in required_inputs)
    return "\n\n".join(lines)
