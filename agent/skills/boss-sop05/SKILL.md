---
name: boss-sop05
description: 根据获准会议记录整理纪要，并分别核查本人确认和行动项交办结果。
metadata:
  boss: {sop_id: SOP05, version: 0.1.0, requirement_id: FR-05}
---

## 触发与输入

本人整理会议纪要。输入包括获准会议记录、会议版本、发言分类、决定与行动项，不能把推断写成已确认决定。

## 步骤与工具引用

1. 使用 bossMeetingsRead 和 bossWorkspaceRead 的 minutes 投影核查会议、现有纪要及来源版本。
2. 分类整理事实、讨论、本人决定、负责人、期限和待确认内容，通过 boss.minutes.save 保存当前草稿。
3. 本人核查当前版本后，通过 boss.minutes.confirm 保存确认结果。各行动项分别取得当前授权，使用 boss.minutes.assignment.create 创建并重新读取对应交办。

工具引用：[bossMeetingsRead](tool:bossMeetingsRead)、[bossWorkspaceRead](tool:bossWorkspaceRead)、[boss.minutes.save](tool:boss.minutes.save)、[boss.minutes.confirm](tool:boss.minutes.confirm)、[boss.minutes.assignment.create](tool:boss.minutes.assignment.create)。

## 授权

纪要确认与每项交办授权分别核查，方法载入或历史确认均不能替代当前本人操作。来源或纪要版本变化后重新核查；工具未注册时停止相应步骤。

## 输出与结束条件

输出纪要版本、来源、当前确认状态与各行动项的实际交办编号和结果。全部请求分别取得正式结果或明确待确认状态后结束。
