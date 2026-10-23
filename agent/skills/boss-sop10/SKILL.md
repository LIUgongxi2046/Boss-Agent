---
name: boss-sop10
description: 根据联系人职责、会面目标、历史事实与承诺准备会面问题和依据。
metadata:
  boss: {sop_id: SOP10, version: 0.1.0, requirement_id: FR-10}
---

## 触发与输入

本人准备人员会面。输入包括联系人稳定编号、当前职责、会面目标、历史事实、承诺及关联会议。

## 步骤与工具引用

1. 使用 bossWorkspaceRead 的 people 投影及 bossMeetingsRead 核查当前人物关系、会议版本和获准历史资料。
2. 通过 boss.people.prepare 准备会面问题、事实依据、待确认承诺和资料缺口；不能根据同名推断身份。
3. 关联或解除会议分别使用 boss.people.attach、boss.people.detach，经当前本人明确操作后重新读取关系和会议准备状态。

工具引用：[bossWorkspaceRead](tool:bossWorkspaceRead)、[bossMeetingsRead](tool:bossMeetingsRead)、[boss.people.prepare](tool:boss.people.prepare)、[boss.people.attach](tool:boss.people.attach)、[boss.people.detach](tool:boss.people.detach)。

## 授权

只读取当前本人获准人物资料。方法不能推断私人信息、创建新人员身份或自动发出邀请；缺少工具时停止相关步骤。

## 输出与结束条件

输出联系人稳定编号、会面问题、来源与待确认事项。资料和关系版本一致、请求操作取得正式回执后结束。
