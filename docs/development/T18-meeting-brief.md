# T18 · FR-04 会前材料：功能优先开发记录

**日期：2026-10-22。状态：部分功能代码完成；A18、A24 和 v6 视觉验收尚未通过。**

本轮遵照 [PRD](../PRD.md) FR-04/FR-06/FR-08、原始 Desktop v6 [F04 会前材料](../../Boss-Agent-Desktop-Complete-v6/pages/F04-会前材料.html) 和高保真品牌色板，优先补全可执行业务流程。**不增加农业模拟数据，不利用 LLM 编造共识、会议结论、附件或经营原因。**

## 实际实现

| 文件 | 作用 |
|---|---|
| `validation/boss_meeting_brief.py` | 当前模拟会议与稳定联系人 ID、原资料/作者/版本、历史承诺、当前关联任务、事件和确定性财务指标的组合；按内容版本 CAS 保存会前快照、保留历史；来源撤销、联系人过期、事件或任务改变时自动标记 `NEEDS_REVIEW` |
| `validation/boss_command_api.py` | BOSS-only `boss.meeting.brief.prepare`，沿用已经认证的 nanobot WebSocket、BEGIN IMMEDIATE SQLite 事务、原请求幂等和不含私密正文的审计 |
| `validation/boss_workspace_api.py` | BOSS-only `GET /api/boss/ui/workspace/briefing`；不执行写入，实时对比已保存的来源版本与当前已批准数据；没有材料时返回空值或缺口 |
| `app/webui/BossMeetingBrief.tsx` | F04 v6 顶部四项业务筛选条、议题/历史承诺/待决定/材料缺口四标签、左主列与右侧信息区、有效原文入口、具体缺口、版本与已保存快照、明确生成按钮 |
| `app/webui/BossMeetingBrief.tsx` | 缺口明确且有有效参会联系人时，老板可确认调用现有 `boss.message.draft.save` 保存消息 DRAFT，再前往 F08 独立审阅/模拟发送；此处绝不产生 SENT |
| `app/tests/test_boss_meeting_brief.py` | 固定来源和数值复算、角色拒绝、并发版本/CAS、原文撤销、历史保留、新关联交办变化、联系人过期、FR-04→FR-08 草稿衔接、实际幂等回执重查 |
| `app/tests/test_v6_meeting_brief_ui.py` | 原 v6 设计页面映射、真实 TSX、原生 mutation、未自动发送等静态回归 |

### 关键功能边界

- 当前会议只来自获准选择数据 `meeting-1`，**不推断新增会议或陌生联系人**。原素材目录中的 `event-1` 是业务事件，不得伪装成新的会议附件。
- 收入、毛利、毛利率和吨数全部从现有固定 `region-1 / EXTERNAL_SALES` 记录按 `Decimal` 重新聚合，显示 BASE/CURRENT 期间、统计口径、原来源和明细 ID。材料撤销后指标改为不可用；**原因贡献仍未知**。
- `READY_FOR_REVIEW` 仅表示当前有可审阅的模拟材料，并不表示老板已审阅、会议已发生或交办已完成。撤销任一来源时保留已保存的旧快照并显示当前 `NEEDS_REVIEW`，下一次准备需本人单独确认。
- 申请与会议的关联未在当前源数据中证明，因此“待决定”页签不会把独立 F07 申请当作已确认的本次会议决定。准备期限没有真实来源时持续显示未知。
- “准备资料请求”只保存 F08 草稿，不代替老板发送。无实际外部消息投递或收件人账号。
- 真实 macOS 1440/1280/1024 截图及 200% 缩放、全部 561 状态的视觉检查仍待执行；CSS 继续复用 Desktop v6 已审定 #005BAC/#5CA63B、Logo、大鹏、卡片、页签、44px 表单控件，禁止降低视觉质量。

## 本地实测与待验收

```bash
# 当前测试会跑于GitHub Actions，真实 Mac 本机仍需执行。
python -m pytest -q app/tests/test_boss_meeting_brief.py app/tests/test_v6_meeting_brief_ui.py
node scripts/visual_qa.cjs --role BOSS --pages F04,F05,F06,F08
python3 scripts/visual_diff.py --role boss
```

下一步仍需：原始外部会议日历与最新企业资料接入、真实可编辑会议/准备期限、跨多会议版本管理、审批申请与会议信息的正式关系、完整外部资料催取/回执、Mac 权限/网络异常/E01—E06 测试、系统级 v6 截图逐页验收。当前既不扩充演示数据，也不擅自将 T18/A18 标为 PASS。
