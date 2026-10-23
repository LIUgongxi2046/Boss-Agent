---
name: boss-sop11
description: 根据当前日历、参与人和时区核查出行接待冲突及变更影响。
metadata:
  boss: {sop_id: SOP11, version: 0.1.0, requirement_id: FR-11}
---

## 触发与输入

本人安排出行或接待。输入包括目的、参与人、时间范围、IANA时区、当前日历与关联事项版本。

## 步骤与工具引用

1. 使用 bossWorkspaceRead 的 travel 投影读取当前行程，使用 bossCalendarConflictRead 核查时间冲突及所涉及事项的当前版本。
2. 通过 boss.travel.review 保存当前核查，展示冲突、交通或准备资料缺口及变更影响，不猜测未知时间。
3. 本人明确决定当前内容后使用 boss.travel.confirm；取消使用 boss.travel.cancel，随后重新读取日历、行程和准备材料的状态。

工具引用：[bossCalendarConflictRead](tool:bossCalendarConflictRead)、[bossWorkspaceRead](tool:bossWorkspaceRead)、[boss.travel.review](tool:boss.travel.review)、[boss.travel.confirm](tool:boss.travel.confirm)、[boss.travel.cancel](tool:boss.travel.cancel)。

## 授权

审阅结果不能产生行程确认、取消、日历分享或通知发送授权。日历变化后重新核查冲突和本人决定；工具未注册时停止相应步骤。

## 输出与结束条件

输出当前期间、时区、冲突、变更影响、准备清单与正式状态。当前请求取得结果或者明确待确认事项后结束。
