---
name: boss-sop03
description: 使用确定性经营查询与当前原文回答指标问题，保留计算口径和未知范围。
metadata:
  boss: {sop_id: SOP03, version: 0.1.0, requirement_id: FR-03}
---

## 触发与输入

本人询问经营指标及变化。输入包括区域、产品、比较期间、单位、币种与当前获准明细；缺少必要条件时请求本人补充。

## 步骤与工具引用

1. 调用 query_metrics，采用服务端当前范围与数据版本，保留 query_id、期间、口径、单位、币种和来源版本。
2. 使用同一 query_id 调用 read_evidence，核查当前有效原文、明细与查询结果；来源变化后重新查询，来源撤销或冲突时停止引用。
3. 使用工具返回的确定性计算结果。分别表达事实、解释和仍需核查的原因，原因贡献材料缺少时明确说明未知。

工具引用：[query_metrics](tool:query_metrics)、[read_evidence](tool:read_evidence)。

## 授权

仅查询当前本人获准资料。不得构造 envelope、authorization_id 或 idempotency_key；不得创建交办、发送消息或确认来源。工具未注册时明确终止相应步骤。

## 输出与结束条件

输出指标、可复算明细、计算口径、日期、来源与未知范围。查询与原文版本一致、问题得到有依据的回答后结束；来源拒绝时报告当前拒绝状态。
