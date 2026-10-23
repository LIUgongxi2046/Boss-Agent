---
name: boss-sop12
description: 根据本人明确范围处理私人安排与忙碌分享，保持正文访问限制。
metadata:
  boss: {sop_id: SOP12, version: 0.1.0, requirement_id: FR-12}
---

## 触发与输入

本人处理私人日历。输入包括本人私人内容、当前安排版本、时间及IANA时区、忙碌窗口和明确分享范围。

## 步骤与工具引用

1. 使用 bossWorkspaceRead 的 calendar 投影读取本人当前安排；使用 bossCalendarSharePreview 核查获准忙碌分享范围与收件人。
2. 保存使用 boss.calendar.save；分享使用 boss.calendar.share；撤销分享使用 boss.calendar.share.revoke；删除使用 boss.calendar.delete。各项操作分别等待当前本人明确决定。
3. 操作后重新读取当前安排与分享状态，说明保留范围及尚未验证的历史副本清理。

工具引用：[bossWorkspaceRead](tool:bossWorkspaceRead)、[bossCalendarSharePreview](tool:bossCalendarSharePreview)、[boss.calendar.save](tool:boss.calendar.save)、[boss.calendar.share](tool:boss.calendar.share)、[boss.calendar.share.revoke](tool:boss.calendar.share.revoke)、[boss.calendar.delete](tool:boss.calendar.delete)。

## 授权

维护身份和联系人不能读取私人正文。分享只包含本人获准的忙碌信息，方法不得扩大收件范围；版本变化后重新确认，工具缺少时停止相关步骤。

## 输出与结束条件

输出当前安排版本、时间、本人可见内容及获准分享状态。实际保存、分享、撤销或删除取得正式结果后结束；未执行时明确等待本人决定。
