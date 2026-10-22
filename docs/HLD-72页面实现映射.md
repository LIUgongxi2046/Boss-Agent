# Boss-Agent v6 桌面 72 页实现映射（T04 架构基线）

> 版本：1.0.0 · 日期：2026-10-22 · 状态：**架构映射固定，功能未开发**

**权威结构化映射**：[`specs/hld-72-page-map.json`](../specs/hld-72-page-map.json)。架构约束见 [`docs/HLD.md`](HLD.md)，验收规则见 PRD V1.2.0 与《交互与页面规范》V1.2.0。本表由设计包 `meta/页面配置.json` 与 `v6-状态关联.json` 一一核对生成。

## 1. 范围及解释

- 72 个 HTML：F 32 / N 12 / D 9 / A 16 / V19 3。每一行都绑定真实设计文件、逻辑路由、拟实现 React 组件、上游复用锚点、语义读写、服务端角色、需求标识及实施验收任务。
- 561 个独立状态关联 = 51（F/A/V）× 11（S00—S10）；N/D 共 21 页无逐页 S00—S10 提示词，继承 `COMMON_STATE_INHERITANCE`、桌面 SYS 和 E01—E06 异常状态。
- 路由 `/app/...` 是 T04 **拟定逻辑路由契约**，不是已存在的 nanobot 路由。T08 在不改变原生 WebUI API 约定的前提下确定 SPA/desktop 的实际承载方式。
- 组件路径为 T10/T08 后续开发建议目标，**仓库当前不存在该 React 产品源码**；每页的 `semantic_read_contracts` / `semantic_command_contracts` 也**不是已经可调用的 HTTP endpoint**；`client_only_intents` 是前端本地选择、草稿提醒及筛选，不生成后端接口。
- `SHELL/THREAD/SETTINGS/...` 是可核验的上游源码锚点（见 JSON `upstream_reuse_anchors` 和 T02 source-map）；共享 UI、React 与 SDK 本身不代表农业、会议、BI、审批已经开发。
- 老板写入必须服务端进行当前授权、版本和幂等校验；维护后台不能代老板决定；示例模拟业务不产生真实外部发送或生产业务影响。
- 页面未开发状态固定为 `ARCHITECTURE_MAPPED_NOT_BUILT`。测试责任：老板 T18，维护 T19，语音 T20，集成/安全 T24，安装交接 T25。

## 2. 全量页面映射

表中 `读取` 与 `写入` 为语义契约名缩写（完整列表见 JSON），`—` 表示无业务写操作；`角色` B=老板、M=维护、A=未认证、S=已认证共用异常/状态；`设计状态` 11=存在 S00—S10，0=仅公共状态。

### F 组（32 页）

| 页面/设计源 | 逻辑路由 | React 目标组件 | 上游复用 | 读取 → 写入（语义域） | 角色 | 来源需求 | 落地任务 | 设计状态 |
|---|---|---|---|---|:---:|---|---|---:|
| [F01 今日工作](../Boss-Agent-Desktop-Complete-v6/pages/F01-今日工作.html) | `/app/boss/F01` | `TodayWorkspacePage` | `SHELL`、`THREAD` | today.read<br>tasks.read<br>calendar.read → today.reorder<br>conversation.start | B | WF-FR-01、WF-FR-11、WF-FR-06 | T18/T24 | 11 |
| [F02 经营提醒](../Boss-Agent-Desktop-Complete-v6/pages/F02-经营提醒.html) | `/app/boss/F02` | `BusinessAlertDetailPage` | `SHELL`、`AUTOMATION`、`SOURCE` | alerts.read<br>alert_rules.read<br>evidence.read → alerts.ack<br>alerts.defer<br>alerts.close<br>assignment.prepare | B | WF-FR-02、WF-FR-06、WF-FR-28 | T18/T24 | 11 |
| [F03 经营查询与追问](../Boss-Agent-Desktop-Complete-v6/pages/F03-经营查询与追问.html) | `/app/boss/F03` | `MetricExplorerPage` | `SHELL`、`TOOLRUN`、`SOURCE` | metrics.query<br>evidence.read<br>metric_definitions.read → conversation.followup | B | WF-FR-03 | T18/T24 | 11 |
| [F04 会前材料](../Boss-Agent-Desktop-Complete-v6/pages/F04-会前材料.html) | `/app/boss/F04` | `MeetingPreparationPage` | `SHELL`、`SOURCE`、`ATTACHMENT` | meetings.read<br>commitments.read<br>materials.read → meeting_brief.prepare<br>message_draft.save | B | WF-FR-04、WF-FR-06 | T18/T24 | 11 |
| [F05 纪要核查](../Boss-Agent-Desktop-Complete-v6/pages/F05-纪要核查.html) | `/app/boss/F05` | `MeetingMinutesReviewPage` | `SHELL`、`SOURCE`、`ATTACHMENT` | minutes.read<br>materials.read<br>meeting_decisions.read → minutes.save<br>assignment.prepare | B | WF-FR-05、WF-FR-06、WF-FR-28 | T18/T24 | 11 |
| [F06 交办详情](../Boss-Agent-Desktop-Complete-v6/pages/F06-交办详情.html) | `/app/boss/F06` | `AssignmentDetailPage` | `SHELL`、`CHATLIST`、`TOOLRUN` | assignments.read<br>feedback.read<br>authorizations.read → assignments.create<br>assignments.send<br>assignments.defer<br>assignments.complete<br>assignments.cancel | B | WF-FR-06、WF-FR-28 | T18/T24 | 11 |
| [F07 申请审阅](../Boss-Agent-Desktop-Complete-v6/pages/F07-申请审阅.html) | `/app/boss/F07` | `ApprovalReviewPage` | `SHELL`、`SOURCE`、`ATTACHMENT` | applications.read<br>application_versions.read<br>evidence.read → approval.decide | B | WF-FR-07、WF-FR-28 | T18/T24 | 11 |
| [F08 消息编辑](../Boss-Agent-Desktop-Complete-v6/pages/F08-消息编辑.html) | `/app/boss/F08` | `MessageComposePage` | `SHELL`、`COMPOSER`、`ATTACHMENT` | message_drafts.read<br>contacts.resolve<br>message_history.read → message_drafts.save<br>messages.send | B | WF-FR-08、WF-FR-28 | T18/T24 | 11 |
| [F09 专题研究](../Boss-Agent-Desktop-Complete-v6/pages/F09-专题研究.html) | `/app/boss/F09` | `StrategicResearchPage` | `SHELL`、`SOURCE`、`COMPOSER` | knowledge.search<br>evidence.read<br>research_topics.read → research.run<br>message_drafts.save | B | WF-FR-09 | T18/T24 | 11 |
| [F10 人员会面](../Boss-Agent-Desktop-Complete-v6/pages/F10-人员会面.html) | `/app/boss/F10` | `PersonnelMeetingPage` | `SHELL`、`SOURCE`、`CHATLIST` | contacts.read<br>commitments.read<br>meetings.read → meeting_brief.prepare<br>meeting_schedule.propose | B | WF-FR-10 | T18/T24 | 11 |
| [F11 行程安排](../Boss-Agent-Desktop-Complete-v6/pages/F11-行程安排.html) | `/app/boss/F11` | `TravelPlanPage` | `SHELL`、`CHATLIST` | travel.read<br>calendar.read<br>conflicts.read → travel.propose<br>travel.confirm | B | WF-FR-11、WF-FR-28 | T18/T24 | 11 |
| [F12 本人私人安排](../Boss-Agent-Desktop-Complete-v6/pages/F12-本人私人安排.html) | `/app/boss/F12` | `PrivateSchedulePage` | `SHELL`、`SETTINGS` | private_calendar.read<br>sharing_scope.read<br>calendar_conflicts.read → private_calendar.save<br>private_calendar.share<br>private_calendar.revoke | B | WF-FR-12、WF-FR-28 | T18/T24 | 11 |
| [F13 个人记忆](../Boss-Agent-Desktop-Complete-v6/pages/F13-个人记忆.html) | `/app/boss/F13` | `PersonalMemoryPage` | `SHELL`、`SETTINGS` | owner_memory.read<br>adoption_records.read<br>decision_history.read → owner_memory.confirm<br>owner_memory.update<br>owner_memory.delete | B | WF-FR-13、WF-FR-28 | T18/T24 | 11 |
| [F14 原料与饲料](../Boss-Agent-Desktop-Complete-v6/pages/F14-原料与饲料.html) | `/app/boss/F14` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.feed_costs.read<br>agri.raw_materials.read<br>evidence.read → assignment.prepare | B | WF-FR-14 | T18/T24 | 11 |
| [F15 水产季节](../Boss-Agent-Desktop-Complete-v6/pages/F15-水产季节.html) | `/app/boss/F15` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.aquaculture_season.read<br>agri.customer_coverage.read<br>evidence.read → assignment.prepare<br>review.schedule | B | WF-FR-15 | T18/T24 | 11 |
| [F16 苗种批次](../Boss-Agent-Desktop-Complete-v6/pages/F16-苗种批次.html) | `/app/boss/F16` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.seed_batch_trace.read<br>agri.trace_relations.read<br>evidence.read → assignment.prepare | B | WF-FR-16 | T18/T24 | 11 |
| [F17 动保与技服](../Boss-Agent-Desktop-Complete-v6/pages/F17-动保与技服.html) | `/app/boss/F17` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.vet_service_cases.read<br>agri.professional_review.read<br>evidence.read → assignment.prepare<br>review.schedule | B | WF-FR-17 | T18/T24 | 11 |
| [F18 生猪合作](../Boss-Agent-Desktop-Complete-v6/pages/F18-生猪合作.html) | `/app/boss/F18` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.pig_partnership.read<br>agri.settlement.read<br>evidence.read → assignment.prepare<br>review.schedule | B | WF-FR-18 | T18/T24 | 11 |
| [F19 禽类与反刍](../Boss-Agent-Desktop-Complete-v6/pages/F19-禽类与反刍.html) | `/app/boss/F19` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.animal_use_metrics.read<br>agri.coverage.read<br>evidence.read → conversation.followup<br>assignment.prepare | B | WF-FR-19 | T18/T24 | 11 |
| [F20 公司水产养殖](../Boss-Agent-Desktop-Complete-v6/pages/F20-公司水产养殖.html) | `/app/boss/F20` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.company_farm_units.read<br>agri.event_history.read<br>evidence.read → assignment.prepare | B | WF-FR-20 | T18/T24 | 11 |
| [F21 食品与品质](../Boss-Agent-Desktop-Complete-v6/pages/F21-食品与品质.html) | `/app/boss/F21` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.food_quality_trace.read<br>agri.batch_relations.read<br>evidence.read → assignment.prepare | B | WF-FR-21 | T18/T24 | 11 |
| [F22 海外业务](../Boss-Agent-Desktop-Complete-v6/pages/F22-海外业务.html) | `/app/boss/F22` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.overseas_operations.read<br>agri.fx_evidence.read<br>evidence.read → meeting_schedule.propose<br>assignment.prepare | B | WF-FR-22 | T18/T24 | 11 |
| [F23 研发应用](../Boss-Agent-Desktop-Complete-v6/pages/F23-研发应用.html) | `/app/boss/F23` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.research_projects.read<br>agri.evaluation_revisions.read<br>evidence.read → review.schedule<br>assignment.prepare | B | WF-FR-23 | T18/T24 | 11 |
| [F24 运行详情](../Boss-Agent-Desktop-Complete-v6/pages/F24-运行详情.html) | `/app/boss/F24` | `OwnerRunDetailPage` | `SHELL`、`THREAD`、`TOOLRUN` | owner_runs.read<br>run_business_outcomes.read → runs.cancel_pending<br>runs.reconcile | B | WF-FR-24、WF-FR-29 | T18/T24 | 11 |
| [F25 模拟中心](../Boss-Agent-Desktop-Complete-v6/pages/F25-模拟中心.html) | `/app/maintain/F25` | `SimulationWorkspacePage` | `SETTINGS`、`APPS`、`AUTOMATION` | datasets.read<br>simulation_events.read<br>simulation_spaces.read → simulation.execute<br>simulation.reset<br>simulation.inject | M | WF-FR-25、WF-FR-26 | T19/T24 | 11 |
| [F26 应用入口与本人设置](../Boss-Agent-Desktop-Complete-v6/pages/F26-应用入口与本人设置.html) | `/app/boss/F26` | `OwnerPreferencesPage` | `SHELL`、`SETTINGS` | owner_profile.read<br>owner_navigation.read<br>owner_settings.read → owner_settings.save<br>auth.logout | B | WF-FR-26、WF-FR-28 | T18/T24 | 11 |
| [F27 语音交办](../Boss-Agent-Desktop-Complete-v6/pages/F27-语音交办.html) | `/app/boss/F27` | `VoiceAssignmentPage` | `SHELL`、`COMPOSER`、`ATTACHMENT` | voice_recording_status.read<br>transcription_result.read → voice.record<br>voice.stop<br>voice.transcribe<br>voice.confirm_text<br>conversation.submit_text | B | WF-FR-27、WF-FR-08、WF-FR-28 | T18/T20/T24 | 11 |
| [F28 动作授权详情](../Boss-Agent-Desktop-Complete-v6/pages/F28-动作授权详情.html) | `/app/boss/F28` | `OwnerAuthorizationDetailPage` | `SHELL`、`SECURITY` | owner_authorizations.read<br>authorized_object.read → owner_authorizations.grant<br>owner_authorizations.revoke | B | WF-FR-28 | T18/T24 | 11 |
| [F29 任务异常详情](../Boss-Agent-Desktop-Complete-v6/pages/F29-任务异常详情.html) | `/app/boss/F29` | `RunFailureDetailPage` | `SHELL`、`THREAD`、`TOOLRUN` | owner_runs.read<br>operation_outcome.read → runs.reconcile<br>runs.cancel_pending | B | WF-FR-29、WF-FR-24 | T18/T24 | 11 |
| [F30 运行与用量详情](../Boss-Agent-Desktop-Complete-v6/pages/F30-运行与用量详情.html) | `/app/maintain/F30` | `MaintainerUsageDetailPage` | `SETTINGS`、`USAGE`、`TOKEN_CARD` | run_telemetry.read<br>usage.read<br>pricing_evidence.read → usage.recalculate | M | WF-FR-30、WF-FR-26 | T19/T24 | 11 |
| [F31 演示评测](../Boss-Agent-Desktop-Complete-v6/pages/F31-演示评测.html) | `/app/maintain/F31` | `EvaluationOverviewPage` | `SETTINGS`、`USAGE` | evaluations.read<br>assertions.read<br>evidence_index.read → evaluation.run<br>evaluation.reset | M | WF-FR-31、WF-FR-26 | T19/T24 | 11 |
| [F32 本地运行与交接](../Boss-Agent-Desktop-Complete-v6/pages/F32-本地运行与交接.html) | `/app/maintain/F32` | `LocalRuntimeHandoffPage` | `SETTINGS`、`RUNTIME_SETTINGS` | environment_health.read<br>build_manifest.read<br>delivery_evidence.read → maintenance.check_health | M | WF-FR-32、WF-FR-26 | T19/T25 | 11 |

### N 组（12 页）

| 页面/设计源 | 逻辑路由 | React 目标组件 | 上游复用 | 读取 → 写入（语义域） | 角色 | 来源需求 | 落地任务 | 设计状态 |
|---|---|---|---|---|:---:|---|---|---:|
| [N01 身份登录](../Boss-Agent-Desktop-Complete-v6/pages/N01-身份登录.html) | `/app/auth/N01` | `IdentityLoginPage` | `AUTH_CLIENT` | auth.challenge.read<br>auth.session.read → auth.login | A | WF-FR-26、WF-FR-28 | T18/T19/T24 | 0 |
| [N02 聊天交办](../Boss-Agent-Desktop-Complete-v6/pages/N02-聊天交办.html) | `/app/boss/N02` | `OwnerConversationPage` | `SHELL`、`THREAD`、`COMPOSER`、`MESSAGES`、`TOOLRUN` | sessions.read<br>threads.read<br>run_business_outcomes.read → conversation.submit<br>conversation.cancel_pending | B | WF-FR-08、WF-FR-24、WF-FR-27、WF-FR-28、WF-FR-29 | T18/T24 | 0 |
| [N03 经营关注](../Boss-Agent-Desktop-Complete-v6/pages/N03-经营关注.html) | `/app/boss/N03` | `BusinessOverviewPage` | `SHELL`、`TOOLRUN`、`CHATLIST` | metrics.overview.read<br>alerts.read<br>agri.topic_index.read → metrics.query<br>conversation.start | B | WF-FR-02、WF-FR-03、WF-FR-14、WF-FR-15、WF-FR-16、WF-FR-17、WF-FR-18、WF-FR-19、WF-FR-20、WF-FR-21、WF-FR-22、WF-FR-23 | T18/T24 | 0 |
| [N04 会议与资料](../Boss-Agent-Desktop-Complete-v6/pages/N04-会议与资料.html) | `/app/boss/N04` | `MeetingsAndMaterialsPage` | `SHELL`、`SOURCE`、`ATTACHMENT` | meetings.list<br>materials.list<br>meeting_decisions.read → meeting_brief.prepare<br>meeting_minutes.prepare | B | WF-FR-04、WF-FR-05、WF-FR-07、WF-FR-09、WF-FR-10 | T18/T24 | 0 |
| [N05 任务与承诺](../Boss-Agent-Desktop-Complete-v6/pages/N05-任务与承诺.html) | `/app/boss/N05` | `AssignmentsAndCommitmentsPage` | `SHELL`、`CHATLIST`、`TOOLRUN` | assignments.list<br>commitments.list<br>feedback.read → assignment.prepare<br>assignment.followup | B | WF-FR-06、WF-FR-28 | T18/T24 | 0 |
| [N06 通知中心](../Boss-Agent-Desktop-Complete-v6/pages/N06-通知中心.html) | `/app/boss/N06` | `OwnerNotificationCenterPage` | `SHELL`、`AUTOMATION` | notifications.list<br>notifications.unread_count → notifications.ack<br>notifications.defer<br>notifications.close | B | WF-FR-02、WF-FR-26 | T18/T24 | 0 |
| [N07 本人目标与关注要求](../Boss-Agent-Desktop-Complete-v6/pages/N07-本人目标与关注要求.html) | `/app/boss/N07` | `OwnerGoalsPage` | `SHELL`、`SETTINGS` | owner_goals.read<br>owner_preferences.read → owner_goals.save | B | WF-FR-01、WF-FR-13、WF-FR-26 | T18/T24 | 0 |
| [N08 通知要求与可见范围](../Boss-Agent-Desktop-Complete-v6/pages/N08-通知要求与可见范围.html) | `/app/boss/N08` | `NotificationAndVisibilityPage` | `SHELL`、`AUTOMATION`、`SETTINGS` | notification_preferences.read<br>sharing_scope.read → notification_preferences.save | B | WF-FR-02、WF-FR-12、WF-FR-26 | T18/T24 | 0 |
| [N09 本人计划](../Boss-Agent-Desktop-Complete-v6/pages/N09-本人计划.html) | `/app/boss/N09` | `OwnerPlansPage` | `SHELL`、`AUTOMATION` | owner_plans.read<br>calendar.read<br>scheduled_events.read → owner_plans.save<br>owner_plans.pause<br>owner_plans.cancel | B | WF-FR-01、WF-FR-02、WF-FR-11、WF-FR-26 | T18/T24 | 0 |
| [N10 本人授权](../Boss-Agent-Desktop-Complete-v6/pages/N10-本人授权.html) | `/app/boss/N10` | `OwnerAuthorizationsPage` | `SHELL`、`SECURITY` | owner_authorizations.list<br>authorization_history.read → owner_authorizations.revoke | B | WF-FR-28 | T18/T24 | 0 |
| [N11 历史决定](../Boss-Agent-Desktop-Complete-v6/pages/N11-历史决定.html) | `/app/boss/N11` | `OwnerDecisionHistoryPage` | `SHELL`、`SOURCE` | owner_decisions.list<br>decision_evidence.read → — | B | WF-FR-13、WF-FR-28 | T18/T24 | 0 |
| [N12 运行概况](../Boss-Agent-Desktop-Complete-v6/pages/N12-运行概况.html) | `/app/maintain/N12` | `MaintainerRunOverviewPage` | `SETTINGS`、`USAGE` | run_telemetry.overview<br>service_health.read → —（本地筛选） | M | WF-FR-26、WF-FR-30 | T19/T24 | 0 |

### D 组（9 页）

| 页面/设计源 | 逻辑路由 | React 目标组件 | 上游复用 | 读取 → 写入（语义域） | 角色 | 来源需求 | 落地任务 | 设计状态 |
|---|---|---|---|---|:---:|---|---|---:|
| [D01 来源原文与支持关系](../Boss-Agent-Desktop-Complete-v6/pages/D01-来源原文与支持关系.html) | `/app/boss/D01` | `EvidenceSourceDrawer` | `SHELL`、`SOURCE` | evidence.source.read<br>evidence.support_relations.read → — | B | WF-FR-03、WF-FR-09 | T18/T24 | 0 |
| [D02 当前动作必要决定](../Boss-Agent-Desktop-Complete-v6/pages/D02-当前动作必要决定.html) | `/app/boss/D02` | `RequiredDecisionDialog` | `SHELL`、`SECURITY` | owner_authorizations.read<br>action_proposal.read → owner_decision.submit | B | WF-FR-28 | T18/T24 | 0 |
| [D03 执行结果核查](../Boss-Agent-Desktop-Complete-v6/pages/D03-执行结果核查.html) | `/app/boss/D03` | `ExecutionOutcomeDrawer` | `SHELL`、`TOOLRUN` | operation_outcome.read<br>run_business_outcomes.read → runs.reconcile | B | WF-FR-24、WF-FR-29 | T18/T24 | 0 |
| [D04 选择负责人](../Boss-Agent-Desktop-Complete-v6/pages/D04-选择负责人.html) | `/app/boss/D04` | `OwnerSelectorDialog` | `SHELL`、`CHATLIST` | contacts.resolve<br>contact_roles.read → —（本地选人） | B | WF-FR-06、WF-FR-08 | T18/T24 | 0 |
| [D05 选择时间与时区](../Boss-Agent-Desktop-Complete-v6/pages/D05-选择时间与时区.html) | `/app/boss/D05` | `DateTimezoneDialog` | `SHELL`、`AUTOMATION` | timezone_rules.read<br>conflicts.read → —（本地选时区） | B | WF-FR-02、WF-FR-06、WF-FR-11 | T18/T24 | 0 |
| [D06 未保存修改提醒](../Boss-Agent-Desktop-Complete-v6/pages/D06-未保存修改提醒.html) | `/app/shared/D06` | `UnsavedChangesDialog` | `SHELL`、`SETTINGS` | draft_state.local → —（本地未保存提醒） | S | WF-FR-05、WF-FR-08、WF-FR-26 | T18/T19 | 0 |
| [D07 访问权限限制](../Boss-Agent-Desktop-Complete-v6/pages/D07-访问权限限制.html) | `/app/shared/D07` | `AccessDeniedPage` | `SETTINGS`、`SECURITY` | access_denial.safe_context → — | S | WF-FR-26、WF-FR-28 | T18/T19/T24 | 0 |
| [D08 登录状态已过期](../Boss-Agent-Desktop-Complete-v6/pages/D08-登录状态已过期.html) | `/app/auth/D08` | `SessionExpiredPage` | `AUTH_CLIENT` | auth.session.read → auth.reauthenticate | A | WF-FR-26、WF-FR-28 | T18/T19/T24 | 0 |
| [D09 历史通知只读详情](../Boss-Agent-Desktop-Complete-v6/pages/D09-历史通知只读详情.html) | `/app/boss/D09` | `HistoricalNotificationDetailPage` | `SHELL`、`AUTOMATION` | notifications.history.read<br>source_version.read → — | B | WF-FR-02、WF-FR-25、WF-FR-26 | T18/T24 | 0 |

### A 组（16 页）

| 页面/设计源 | 逻辑路由 | React 目标组件 | 上游复用 | 读取 → 写入（语义域） | 角色 | 来源需求 | 落地任务 | 设计状态 |
|---|---|---|---|---|:---:|---|---|---:|
| [A01 档案与访问](../Boss-Agent-Desktop-Complete-v6/pages/A01-档案与访问.html) | `/app/maintain/A01` | `MaintainerAccessPage` | `SETTINGS`、`SETTINGS_VIEW`、`SECURITY`、`RUNTIME_SETTINGS` | maintenance.access.read<br>owner_profile.metadata.read → maintenance.access.save<br>maintenance.access.validate<br>maintenance.access.activate | M | WF-FR-26、WF-FR-28、WF-AD01 | T19/T24 | 11 |
| [A02 接口目录](../Boss-Agent-Desktop-Complete-v6/pages/A02-接口目录.html) | `/app/maintain/A02` | `SimulationInterfaceCatalogPage` | `SETTINGS`、`APPS` | simulation.interfaces.read<br>simulation.calls.read → simulation.invoke<br>simulation.test | M | WF-FR-25、WF-FR-26、WF-AD02 | T19/T24 | 11 |
| [A03 数据集](../Boss-Agent-Desktop-Complete-v6/pages/A03-数据集.html) | `/app/maintain/A03` | `SimulationDatasetPage` | `SETTINGS`、`APPS` | simulation.datasets.read<br>simulation.lineage.read → simulation.datasets.generate<br>simulation.reset | M | WF-FR-25、WF-FR-26、WF-AD03 | T19/T24 | 11 |
| [A04 场景与事件](../Boss-Agent-Desktop-Complete-v6/pages/A04-场景与事件.html) | `/app/maintain/A04` | `SimulationScenarioEventsPage` | `SETTINGS`、`AUTOMATION` | simulation.events.read<br>simulation.clock.read → simulation.events.inject<br>simulation.clock.advance | M | WF-FR-25、WF-FR-26、WF-AD04 | T19/T24 | 11 |
| [A05 Prompt版本](../Boss-Agent-Desktop-Complete-v6/pages/A05-Prompt版本.html) | `/app/maintain/A05` | `PromptVersionPage` | `SETTINGS`、`SKILLS` | prompt_versions.read<br>config_adoption.read → prompt_versions.save<br>prompt_versions.validate<br>prompt_versions.activate | M | WF-FR-24、WF-FR-26、WF-FR-30、WF-AD05 | T19/T24 | 11 |
| [A06 SOP与Skills](../Boss-Agent-Desktop-Complete-v6/pages/A06-SOP与Skills.html) | `/app/maintain/A06` | `SopSkillsPage` | `SETTINGS`、`SKILLS` | sop_versions.read<br>skills_catalog.read → sop.save<br>sop.validate<br>sop.activate | M | WF-FR-24、WF-FR-26、WF-AD06 | T19/T24 | 11 |
| [A07 Knowledge Base](../Boss-Agent-Desktop-Complete-v6/pages/A07-Knowledge Base.html) | `/app/maintain/A07` | `KnowledgeManagementPage` | `SETTINGS`、`SOURCE`、`ATTACHMENT` | knowledge_sources.list<br>knowledge_index.status → knowledge.ingest<br>knowledge.verify<br>knowledge.withdraw | M | WF-FR-09、WF-FR-26、WF-AD07 | T19/T24 | 11 |
| [A08 模型连接](../Boss-Agent-Desktop-Complete-v6/pages/A08-模型连接.html) | `/app/maintain/A08` | `DeepSeekProviderPage` | `SETTINGS`、`MODELS`、`PROVIDER`、`RUNTIME_SETTINGS` | model_config.read<br>provider_status.read → model_config.save<br>model_config.validate<br>model_config.activate | M | WF-FR-24、WF-FR-26、WF-FR-30、WF-AD08 | T19/T24 | 11 |
| [A09 Tools与连接](../Boss-Agent-Desktop-Complete-v6/pages/A09-Tools与连接.html) | `/app/maintain/A09` | `ToolsConnectionPage` | `SETTINGS`、`APPS` | tools_catalog.read<br>connection_health.read → tools.save<br>tools.validate<br>tools.activate | M | WF-FR-24、WF-FR-26、WF-FR-28、WF-AD09 | T19/T24 | 11 |
| [A10 指标与规则](../Boss-Agent-Desktop-Complete-v6/pages/A10-指标与规则.html) | `/app/maintain/A10` | `MetricsRulesPage` | `SETTINGS`、`AUTOMATION` | metric_definitions.read<br>alert_rules.read → metric_definitions.save<br>alert_rules.save<br>configuration.activate | M | WF-FR-02、WF-FR-03、WF-FR-26、WF-AD10 | T19/T24 | 11 |
| [A11 关联对象](../Boss-Agent-Desktop-Complete-v6/pages/A11-关联对象.html) | `/app/maintain/A11` | `SimulationRelationshipsPage` | `SETTINGS`、`APPS` | simulation.relationships.read<br>contacts.metadata.read → simulation.relationships.save<br>simulation.feedback.inject | M | WF-FR-25、WF-FR-26、WF-FR-28、WF-AD11 | T19/T24 | 11 |
| [A12 记忆技术维护](../Boss-Agent-Desktop-Complete-v6/pages/A12-记忆技术维护.html) | `/app/maintain/A12` | `MemoryTechnicalMaintenancePage` | `SETTINGS`、`RUNTIME_SETTINGS` | owner_memory.metadata.read<br>memory_index.status → memory_index.verify<br>memory_index.repair | M | WF-FR-13、WF-FR-26、WF-AD12 | T19/T24 | 11 |
| [A13 调度计划](../Boss-Agent-Desktop-Complete-v6/pages/A13-调度计划.html) | `/app/maintain/A13` | `SchedulerManagementPage` | `SETTINGS`、`AUTOMATION` | scheduler.jobs.read<br>scheduler_execution.read → scheduler.jobs.save<br>scheduler.jobs.pause<br>scheduler.jobs.cancel | M | WF-FR-02、WF-FR-24、WF-FR-26、WF-AD13 | T19/T24 | 11 |
| [A14 动作授权记录](../Boss-Agent-Desktop-Complete-v6/pages/A14-动作授权记录.html) | `/app/maintain/A14` | `AuthorizationAuditPage` | `SETTINGS`、`SECURITY` | owner_authorizations.metadata.read<br>authorization_audit.read → — | M | WF-FR-26、WF-FR-28、WF-AD14 | T19/T24 | 11 |
| [A15 运行记录](../Boss-Agent-Desktop-Complete-v6/pages/A15-运行记录.html) | `/app/maintain/A15` | `RunLogsPage` | `SETTINGS`、`USAGE`、`TOKEN_CARD` | run_telemetry.read<br>usage.read<br>errors.read → — | M | WF-FR-26、WF-FR-30、WF-AD15 | T19/T24 | 11 |
| [A16 评测管理](../Boss-Agent-Desktop-Complete-v6/pages/A16-评测管理.html) | `/app/maintain/A16` | `EvaluationManagementPage` | `SETTINGS`、`USAGE` | evaluation_cases.read<br>evaluation_results.read → evaluation.run<br>evaluation.reset | M | WF-FR-26、WF-FR-31、WF-AD16 | T19/T24 | 11 |

### V 组（3 页）

| 页面/设计源 | 逻辑路由 | React 目标组件 | 上游复用 | 读取 → 写入（语义域） | 角色 | 来源需求 | 落地任务 | 设计状态 |
|---|---|---|---|---|:---:|---|---|---:|
| [V19-BEEF 禽类与反刍](../Boss-Agent-Desktop-Complete-v6/pages/V19-BEEF-禽类与反刍.html) | `/app/boss/V19-BEEF` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.animal_use_metrics.beef.read<br>evidence.read → conversation.followup<br>assignment.prepare | B | WF-FR-19 | T18/T24 | 11 |
| [V19-EGG 禽类与反刍](../Boss-Agent-Desktop-Complete-v6/pages/V19-EGG-禽类与反刍.html) | `/app/boss/V19-EGG` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.animal_use_metrics.egg.read<br>evidence.read → conversation.followup<br>assignment.prepare | B | WF-FR-19 | T18/T24 | 11 |
| [V19-MILK 禽类与反刍](../Boss-Agent-Desktop-Complete-v6/pages/V19-MILK-禽类与反刍.html) | `/app/boss/V19-MILK` | `AgriScenarioPage` | `SHELL`、`TOOLRUN`、`SOURCE` | agri.animal_use_metrics.milk.read<br>evidence.read → conversation.followup<br>assignment.prepare | B | WF-FR-19 | T18/T24 | 11 |

## 3. 一致性与责任关口

| 检查 | 设计基线 | T04 映射 | 解释 |
|---|---:|---:|---|
| 唯一页面 ID | 72 | 72 | 目录文件名、配置名、页面 ID 均一对一 |
| F/N/D/A/V 分类 | 32/12/9/16/3 | 32/12/9/16/3 | V19 为 FR-19 场景变体，非新增 FR |
| 独立 S00—S10 状态 | 561 | 561 | 全部 561 保留原始状态索引，不宣称有 561 张独立截图 |
| 公共状态继承页 | 21 | 21 | N01—N12、D01—D09 不能伪造单页状态索引 |
| 老板 / 维护 / 未认证路由 | 依源设计及 PRD | 每页均明确 `role_gate` | 真实权限只由服务端控制，不能信任前端路径 |
| 开发达成 | 无正式产品 UI 证明 | 0 个标记为已实现 | 后续 T08/T18—T20 以真实 DOM + API + 状态重读证明 |

**设计基线冻结范围**：逻辑路由、页面 ID、组件及复用锚点、来源 FR/AD、语义读写范围、身份与任务责任；T05—T08 可细化字段、状态机、HTTP operationId、事件与源码位置，不得静默减少 72 页或删减 PRD 的 32 FR、16 AD。任何偏离须记录 ADR、更新此映射版本、PRD 关联、验收及用户决定。

**特别说明**：`F19` 的默认 BROILER（肉禽）与 `V19-EGG/MILK/BEEF` 各独立的用途查询入口采用同一 `AgriScenarioPage` 模板；切换场景后重新查询，不能混用单位、产出指标或数据范围。

## 4. 下游明确的绑定工作

1. **T05/T06**：把语义读写契约转为字段、实体状态、`openapi.yaml` 的 `operationId`、错误码、请求/响应与授权，标出 5 个验证工具操作的实际服务升级路径；未实现的接口不得贴已通过标签。
2. **T07**：对 Agent 工具和 SOP 建立同一审批、安全与幂等边界；专业资料必须由可撤销的有效来源提供。
3. **T08**：把拟定组件/逻辑路由落到具体 React 文件、真实上游页面和 API/WS 事件映射，产生规定的 `specs/page-service-map.json`；确认从详情、弹窗、文件和运行记录返回后恢复选中对象、滚动、焦点、日期与筛选。
4. **T18—T20**：以同页 1x/2x 原图在三个窗口与 200% 缩放条件下对比；对每个可写动作检查未授权、重复提交、冲突、未知状态与重读。
5. **T24/T25**：仅在真实集成、异常、平台权限和正式安装运行获得证据后宣称功能通过；不把设计图、静态状态入口或 T02 可行性当作正式产品验收。
