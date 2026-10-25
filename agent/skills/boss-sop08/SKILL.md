---
name: boss-sop08
description: 核查稳定收件人、沟通草稿和当前授权，分别呈现发送记录与送达状态。
metadata:
  boss: {sop_id: SOP08, version: 0.1.0, requirement_id: FR-08}
---

## 触发与输入

本人准备沟通。输入包括稳定联系人、收件人编号、草稿内容与版本、获准资料以及本人发送决定。

## 步骤与工具引用

1. 使用 bossWorkspaceRead 的 organization 与 outbox 投影核查当前收件人、联系人关系及已有记录；同名人员需要稳定编号。
2. 使用 boss.message.draft.save 保存当前草稿，展示收件人、内容、来源及当前版本供本人核查。
3. 当前本人明确确认后通过 boss.message.send 执行发送，随后重新读取发送记录及独立送达状态。

工具引用：[bossWorkspaceRead](tool:bossWorkspaceRead)、[boss.message.draft.save](tool:boss.message.draft.save)、[boss.message.send](tool:boss.message.send)。

## 授权

更改收件人、正文或来源后重新确认。方法载入和保存草稿不能产生发送授权；模拟发件箱记录不能证明真实外部送达，工具未注册时停止。

## 输出与结束条件

输出当前草稿或实际发送回执、收件人编号、版本、送达状态及未知范围。结果未知时查询原请求，不能自动重复发送。
