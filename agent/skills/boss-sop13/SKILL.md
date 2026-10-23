---
name: boss-sop13
description: 核查本人当前确认的记忆、历史决定与有效引用，说明修改删除后的采用范围。
metadata:
  boss: {sop_id: SOP13, version: 0.1.0, requirement_id: FR-13}
---

## 触发与输入

本人查看历史与记忆，或者明确要求确认、修改和删除记忆。输入包括本人当前要求、对象版本、确认权限、历史决定和有效引用。

## 步骤与工具引用

1. 使用 bossWorkspaceRead 的 memory、decisions、knowledge 投影读取当前本人获准内容，必要时使用 read_evidence 核查当前引用。
2. 将本人要求和模型推断分别呈现。通过 boss.memory.confirm 保存当前本人明确确认，删除通过 boss.memory.delete 执行；模型不得自动确认。
3. 操作后重新读取当前版本与确认状态，核查新会话和Runtime重启后的上下文选择。历史会话、初始来源、备份及物理擦除分别报告验证范围。

工具引用：[bossWorkspaceRead](tool:bossWorkspaceRead)、[read_evidence](tool:read_evidence)、[boss.memory.confirm](tool:boss.memory.confirm)、[boss.memory.delete](tool:boss.memory.delete)。

## 授权

只有本人能够确认或删除个人记忆，维护只读取技术元信息。方法文件、历史授权和已删除正文不能成为当前确认依据；工具缺少时停止相关步骤。

## 输出与结束条件

输出当前版本、当前确认状态、引用、后续采用条件及未验证的清理范围。保存结果与后续采用分别核查，不根据接口成功推断模型已经采用。
