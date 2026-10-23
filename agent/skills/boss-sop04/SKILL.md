---
name: boss-sop04
description: 核查当前会议版本、参与人、历史承诺与资料并准备会前材料。
metadata:
  boss: {sop_id: SOP04, version: 0.1.0, requirement_id: FR-04}
---

## 触发与输入

本人准备当前会议。输入包括会议编号及版本、参会人、历史承诺、获准来源、业务日期和材料范围。

## 步骤与工具引用

1. 使用 meetingArrangementRead、bossMeetingsRead 和 bossEvidenceRead 核查当前会议、参会人、资料版本及邀请状态。
2. 通过 boss.meeting.brief.prepare 准备有来源的材料，保留议题、事实、历史承诺、待决定问题与资料缺口。
3. 安排变化时重新读取。meetingDraftSave 保存待核查内容；meetingConfirm、meetingCancel、meetingHeld 分别需要当前本人明确操作，并重新读取结果。

工具引用：[bossMeetingsRead](tool:bossMeetingsRead)、[bossEvidenceRead](tool:bossEvidenceRead)、[meetingArrangementRead](tool:meetingArrangementRead)、[boss.meeting.brief.prepare](tool:boss.meeting.brief.prepare)、[meetingDraftSave](tool:meetingDraftSave)、[meetingConfirm](tool:meetingConfirm)、[meetingCancel](tool:meetingCancel)、[meetingHeld](tool:meetingHeld)。

## 授权

会前材料不能产生邀请发送、会议确认、取消或已举行授权。来源变化后停止采用旧材料，未注册工具时停止相应步骤。

## 输出与结束条件

输出当前会议版本、带出处的材料、冲突与资料缺口。材料与会议及来源版本一致后结束；等待本人决定时保留待确认状态。
