---
name: boss-sop07
description: 整理当前申请材料和资料缺口，核查本人审批决定对应的版本。
metadata:
  boss: {sop_id: SOP07, version: 0.1.0, requirement_id: FR-07}
---

## 触发与输入

本人查看待审材料。输入包括申请编号、当前版本、获准材料、审批范围及本人决定。

## 步骤与工具引用

1. 使用 bossWorkspaceRead 的 approvals 投影读取当前申请，使用 bossEvidenceRead 核查来源与材料版本。
2. 分别表达申请事实、风险、缺口、建议与需本人决定的问题；资料不足时保留待补充状态。
3. 本人明确决定当前版本后使用 boss.approval.decide 保存结果，重新读取正式状态和采用的版本。

工具引用：[bossWorkspaceRead](tool:bossWorkspaceRead)、[bossEvidenceRead](tool:bossEvidenceRead)、[boss.approval.decide](tool:boss.approval.decide)。

## 授权

模型建议、方法启用和历史同类决定均不能替代当前审批授权。不得执行资金交易、专业放行或未注册工具；版本改变后重新取得本人决定。

## 输出与结束条件

输出当前材料版本、出处、缺口、待决定问题与实际决定回执。当前决定已经保存并查询，或者明确等待本人决定时结束。
