# T18/T19 · F08 消息与 FR12 私人日程实施记录

> 2026-10-22 · 状态：**可编译、SQLite 事务和权限测试覆盖的开发切片**。T18/T19 仍 IN_PROGRESS，PRD 最终与 Mac 视觉验收均未通过。

## 原始需求与设计基准

严格对照 [PRD](../PRD.md) FR-08、FR-12 以及 Desktop v6 原始页面
\`Boss-Agent-Desktop-Complete-v6/pages/F08-消息编辑.html\`、
\`Boss-Agent-Desktop-Complete-v6/pages/F12-本人私人安排.html\`。
沿用 Desktop v6 蓝绿白、Logo、大鹏、204px 侧栏、64px 顶栏、146/122px Hero、278px 右侧栏、44px 控件和信息卡片语言。**尚未完成 Mac 实际屏幕的逐页像素对照**，不声称视觉合格。

## F08 消息编辑真实业务

代码路径：

- \`validation/boss_message_calendar.py\`：\`boss.message.draft.save\`、\`boss.message.send\`、\`boss.simulation.message.reply\`。
- \`validation/boss_command_api.py\`：经过原有 RoleChannel/BOSS 或 MAINTAINER 身份校验、同一 SQLite 事务、CAS/内容摘要、幂等及脱敏审计。
- \`validation/boss_workspace_api.py\`：BOSS-only \`/api/boss/ui/workspace/outbox\` 查询当前草稿、实际本机模拟发送及关联回复；MAINTAINER-only \`/api/boss/ui/workspace/message-admin\` 只显示消息 ID、收件人 ID、模拟状态，不暴露正文、附件或个人记忆。
- \`app/webui/BossCommunicationCalendar.tsx\`：F08 草稿表单、稳定联系人 ID、组织职责消歧、附件来源/版本、关联任务、模拟发件箱和回复时间线。
- \`app/webui/MaintainerMessageReply.tsx\`：A04 模拟联系人署名回复；若已绑定并独立发送的 F06 任务处于 WAITING_FEEDBACK 或 IN_PROGRESS，真实增加一条 PROGRESS 反馈。不能标记结果提交或替老板确认完成。

流程：输入文字 → 选择唯一联系人与附件引用 → 本人核对并保存版本化 DRAFT → 再次单独核对当前版本和内容摘要 → 服务端持久保存 SENT_SIMULATED 消息 → 维护端可显式注入已标记的合成回复 → 老板回读回复及相关任务状态。**真实外部发送、收件人登录、投递/送达证明均未接入；SENT_SIMULATED 不等于 DELIVERED。** 断网不确定时保留同一请求编号重试，不能因请求失败而用新 ID 盲目再发。附件撤销/换版本和草稿编辑令旧确认失效。

## FR12 私人安排与忙碌分享

本机模拟日历固定 PRIVATE/BOSS_ONLY，用户可以编辑时间、标题、地点、正文和版本，并在有会议时段信息不足时明确确认冲突风险。只有老板可取得私人正文与本人授权记录。维护端没有个人日程正文、地点及原始消息/附件的 API。

对外授权仅存 \`busy\`、\`starts_at\`、\`ends_at\`、\`timezone\`，接收对象使用获准联系人稳定 ID；分享用途进入授权摘要而不泄露私人内容。保存日程新版本自动撤销此前活跃忙碌分享，老板也可逐项撤销和删除日程。删除阻止未来读取私人正文，但**不宣称历史数据库或备份已安全擦除**；任何真实外部日历服务、共享邀请投递与撤回回执仍未完成。

## 自动化回归

\`app/tests/test_boss_message_calendar.py\` 覆盖同名联系人稳定 ID、保存/编辑 CAS、附件撤销、内容篡改、模拟发送幂等、署名回复与任务 PROGRESS、私人正文隔离、忙碌字段白名单、分享撤销、删除和工作会议冲突未知状态。

\`app/tests/test_v6_communication_calendar_ui.py\` 检查页面映射、独立组件、上游 authenticated mutation、无原文注入、共享白名单、原始视觉 Token。每次 GitHub Actions 都包含固定 nanobot + React TypeScript/Vite 构建、Python 合成业务测试；实际执行回执需以对应 commit 的 Actions 为准。

## 尚未完成并保留 PRD 原项

FR08 的真实外部服务连接、消息投递回执、完整多附件/联系人关系、不确定回执恢复及 E01—E06；FR12 的真实外部共享/撤回、冲突数据库、私人多日程、备份擦除；全部 72 页的系统级状态与原设计像素级对照、Mac Intel 实机认证/语音/模型、签名分发安装等仍不构成本批次已验收工作。
