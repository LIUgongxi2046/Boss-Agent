from datetime import datetime
from decimal import Decimal
from math import ceil


def insight(identifier, target, title, finding, impact, action, evidence, priority="attention"):
    return {"id": identifier, "target_id": target, "title": title, "finding": finding,
            "impact": impact, "action": action, "evidence": evidence, "priority": priority,
            "basis": "CURRENT_RECORD_RULE", "action_executed": False}


def metric_direction(label):
    if label in {"入库成本", "领用成本", "交付缺口"}:
        return "lower"
    if label in {"订单", "回款范围"}:
        return "higher"
    return "neutral"


def business_insights(topics):
    findings = []
    for topic in topics:
        candidates = []
        for metric in topic.get("metrics", []):
            if metric["change_percent"] is None:
                continue
            change = Decimal(metric["change_percent"])
            direction = metric_direction(metric["label"])
            adverse = direction == "lower" and change > 0 or direction == "higher" and change < 0
            if abs(change) < 10 or not adverse:
                continue
            unit = metric["unit"].replace("CNY", "元")
            evidence = [f"{metric['period']}：{metric['value']} {unit}", f"比较期间：{metric['previous_value']} {unit}", "触发条件：不利方向变化达到 10%；达到 25% 时优先关注。"]
            cost = "成本" in metric["label"]
            impacts = {"订单": "订单减少可能影响后续收入与生产安排，需要核查取消、延期及业务结构变化。",
                       "回款范围": "回款减少可能影响资金安排，需要结合应收账款、约定回款日和实际收款核查。",
                       "交付缺口": "待补交付量增加可能影响客户履约，需要核查订单期限、产能与供货安排。"}
            actions = {"订单": "核查主要客户订单的取消、延期与新增情况，确认需要协调的客户和生产安排。",
                       "回款范围": "核查到期应收、逾期金额和收款计划，明确财务与业务负责人各自的跟进事项。",
                       "交付缺口": "核查待交付订单、承诺日期和可用产能，形成负责人及补交时间清单。"}
            candidates.append((abs(change), insight(topic["page_id"] + ":" + metric["label"], topic["page_id"],
                topic["title"] + " · " + metric["label"] + ("上升" if change > 0 else "下降"),
                f"较上一报告期{'增加' if change > 0 else '减少'} {abs(change)}%。",
                "相同售价与销量下，成本上升会压缩毛利；具体金额需要核查采购数量与产品结构。" if cost else
                impacts[metric["label"]],
                "核查采购单价、领用数量和产品结构，确认价格变化与用量变化各自的影响。" if cost else
                actions[metric["label"]],
                evidence, "urgent" if abs(change) >= 25 else "attention")))
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            findings.append(candidates[0][1])
    return sorted(findings, key=lambda item: item["priority"] != "urgent")


def task_insights(tasks, clock, contacts, commitments=()):
    current = datetime.fromisoformat(clock)
    names = {item["contact_id"]: item["name"] for item in contacts}
    findings = []
    items = [(task, task["task_id"], False) for task in tasks]
    items += [(task, task["commitment_id"], True) for task in commitments]
    for task, identifier, personal in items:
        if task["status"] in {"CANCELED", "COMPLETED_CONFIRMED", "COMPLETED"}:
            continue
        due = datetime.fromisoformat(task["due_at"]) if task.get("due_at") else None
        hours = (due - current).total_seconds() / 3600 if due else None
        owner = "本人" if personal else names.get(task.get("coordinator_id"), "负责人待指定")
        evidence = ["负责人：" + owner]
        if due:
            evidence.append(f"约定期限：{due.month}月{due.day}日 {due.hour:02d}:{due.minute:02d}")
        if task["status"] == "RESULT_SUBMITTED":
            finding, impact, action, priority = "负责人已提交处理结果，等待本人验收。", "完成状态需要验收结果支持。", "查看交付内容与相关材料，确认完成或明确需要补充的内容。", "attention"
        elif hours is not None and hours < 0:
            finding, impact, action, priority = f"已经超过约定期限 {max(1, int(-hours))} 小时。", "约定时间已过，相关安排可能受到影响；具体影响需要负责人说明。", "请负责人说明进展、阻碍与新的完成时间，再决定是否协调资源。", "urgent"
        elif hours is not None and hours <= 48:
            finding, impact, action, priority = f"距离约定期限约 {max(1, ceil(hours))} 小时。", "需要提前确认能否按期完成。", "确认剩余工作、交付内容和反馈时间；存在阻碍时明确需要的支持。", "attention"
        elif not personal and not task.get("coordinator_id"):
            finding, impact, action, priority = "当前没有指定负责人。", "后续进度缺少明确责任人。", "指定负责人并约定反馈时间。", "attention"
        elif not due:
            finding, impact, action, priority = "当前没有约定完成期限。", "无法判断事项是否及时完成。", "明确完成日期与验收要求。", "attention"
        else:
            continue
        item = insight(identifier, identifier, task["purpose"], finding, impact, action, evidence, priority)
        item["target_kind"] = "self_commitment" if personal else "task"
        findings.append(item)
    return sorted(findings, key=lambda item: item["priority"] != "urgent")


def meeting_insights(records, clock):
    current = datetime.fromisoformat(clock)
    findings = []
    for record in records:
        if record["material_state"] in {"WITHDRAWN", "EXPIRED", "CANCELED", "APPROVED_RECORDED", "REJECTED_RECORDED"} or record["meeting_state"] == "CANCELED":
            continue
        due = datetime.fromisoformat(record["at"]) if record["at"] else None
        evidence = [record["summary"]] if record["summary"] else []
        if due:
            evidence.append(f"安排时间：{due.month}月{due.day}日 {due.hour:02d}:{due.minute:02d}")
        if record["kind"] == "approval" and record["material_state"] in {"PENDING_DECISION", "WAITING_MATERIAL"}:
            finding, impact, action = "申请尚待本人决定。", "申请的后续安排需要明确处理意见。", "核查申请目的、金额与材料，决定同意、驳回或补充材料。"
        elif record["material_gaps"]:
            finding, impact, action = "当前材料尚不齐备。", "讨论和决定可能缺少必要依据。", "联系材料负责人补充内容，确认资料适用范围后继续处理。"
        elif record["kind"] == "meeting" and record["meeting_state"] == "HELD" and record["minute_state"] != "CONFIRMED":
            finding, impact, action = "会议已举行，纪要尚未确认。", "会议决定和交办事项需要确认依据。", "核查会议结论，明确每项决定、负责人和完成时间。"
        elif record["kind"] in {"meeting", "people"} and due and 0 <= (due-current).total_seconds() <= 48*3600:
            finding, impact, action = "这项安排将在未来两天内进行。", "提前明确议题有助于集中处理需要本人决定的事项。", "整理关键问题、可选方案与需要本人决定的内容。"
        else:
            continue
        item = insight(record["kind"] + ":" + record["id"], record["id"], record["title"], finding, impact, action, evidence)
        item["target_kind"] = record["kind"]
        findings.append(item)
    return findings
