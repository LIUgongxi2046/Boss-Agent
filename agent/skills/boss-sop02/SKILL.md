---
name: boss-sop02
description: 核查经营提醒的参与原因、当前依据和本人处理结果。
metadata:
  boss: {sop_id: SOP02, version: 0.1.0, requirement_id: FR-02}
---

## 触发与输入

本人查看经营提醒。输入包括当前指标、规则版本、通知要求、已有交办和业务时间。

## 步骤与工具引用

1. 使用 bossWorkspaceRead 的 notifications 投影读取当前提醒及其来源，核查指标期间、规则、关联事项与已有处理状态。
2. 说明需要本人参与的原因、已有处理和仍需本人决定的内容；缺少明细时报告资料不足。
3. 本人明确选择知晓、暂缓或关闭后，分别通过 boss.reminder.ack、boss.reminder.snooze、boss.reminder.close 保存当前对象的决定，并重新读取结果。

工具引用：[bossWorkspaceRead](tool:bossWorkspaceRead)、[boss.reminder.ack](tool:boss.reminder.ack)、[boss.reminder.snooze](tool:boss.reminder.snooze)、[boss.reminder.close](tool:boss.reminder.close)。

## 授权

提醒处理需要本人当前明确决定和对象版本。知晓、暂缓、关闭分别保留业务语义，不能据此完成交办或发送消息。工具未注册时停止相应步骤。

## 输出与结束条件

输出参与原因、当前事实、引用和实际处理状态。当前决定保存并重新读取后结束；等待本人决定时明确显示待确认。
