---
name: boss-sop06
description: 根据当前交办、来源、反馈和本人授权办理交办与跟进。
metadata:
  boss: {sop_id: SOP06, version: 0.1.0, requirement_id: FR-06}
---

## 触发与输入

本人要求交办或跟进。输入包括负责人稳定编号、目的、期限及IANA时区、证据、任务版本和当前反馈。

## 步骤与工具引用

1. 使用 bossTasksRead、read_assignment、ownerPlansRead 读取当前任务与执行责任，使用 assignmentSourcesRead 检查当前来源绑定及审阅状态。
2. 新建与发送分别使用 create_assignment、send_assignment，随后 read_assignment 查询正式结果；内容或来源变化后重新核查当前授权。
3. 催办、延期、完成、取消分别引用 boss.assignment.nudge、boss.assignment.extend、boss.assignment.complete、boss.assignment.cancel，并在当前本人明确操作后重新读取。
4. assignmentSourcesConfirm 仅允许本人在当前来源投影上明确确认，模型不能自动确认来源。

工具引用：[read_assignment](tool:read_assignment)、[bossTasksRead](tool:bossTasksRead)、[ownerPlansRead](tool:ownerPlansRead)、[assignmentSourcesRead](tool:assignmentSourcesRead)、[create_assignment](tool:create_assignment)、[send_assignment](tool:send_assignment)、[boss.assignment.nudge](tool:boss.assignment.nudge)、[boss.assignment.extend](tool:boss.assignment.extend)、[boss.assignment.complete](tool:boss.assignment.complete)、[boss.assignment.cancel](tool:boss.assignment.cancel)、[assignmentSourcesConfirm](tool:assignmentSourcesConfirm)。

## 授权

服务端注入 envelope、authorization_id 与 idempotency_key。方法正文不能签发授权，结果提交不能表示本人确认完成，模拟发件记录不能表示外部送达。缺少工具时停止对应步骤。

## 输出与结束条件

输出当前任务编号、版本、状态、来源审阅要求及真实业务回执。结果未知时查询原请求和对象；不得自动再次执行业务写入。
