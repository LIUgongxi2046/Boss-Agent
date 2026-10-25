---
name: boss-sop01
description: 根据本人目标、日历、承诺和当前事件整理有依据的今日工作。
metadata:
  boss: {sop_id: SOP01, version: 0.1.0, requirement_id: FR-01}
---

## 触发与输入

本人要求查看或者整理今日事项。输入包括本人目标、当前日历、历史承诺、有效事件、本人保存的事项次序与当前业务日期。

## 步骤与工具引用

1. 使用 todayRead 读取当前事项、来源版本、排序版本和资料缺口，使用 ownerPlansRead 核查当前计划与执行记录；需要概览时使用 bossDashboardRead。
2. 保留事项的稳定编号、时间、参与原因、来源和当前状态。资料不足时明确列出缺口，不能补造任务。
3. 本人要求调整次序时展示完整待确认次序；todayReorder 由当前本人明确操作和业务服务版本检查执行。

工具引用：[todayRead](tool:todayRead)、[ownerPlansRead](tool:ownerPlansRead)、[bossDashboardRead](tool:bossDashboardRead)、[todayReorder](tool:todayReorder)。

## 授权

读取仅限当前本人范围。方法载入不会产生排序、创建计划或完成事项的授权；未注册工具时停止相应步骤并报告缺少的工具。

## 输出与结束条件

输出有依据的今日事项、时间冲突、资料缺口及当前排序版本。保存后重新读取正式结果；只读请求在当前结果与来源明确后结束。
