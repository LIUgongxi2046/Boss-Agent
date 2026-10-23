# T18 · FR06 任务中心、本人承诺与跨页面消息草稿（开发切片）

> 2026-10-23。状态：**SQLite 业务实现/角色权限/跨页面 React 已提交；完整 PRD A18、Mac 实机及像素验收未通过**。本批次优先补功能，没有添加模拟经营数据。

## 已落实的业务边界

**N05 任务与承诺**沿用确认的 Desktop v6 模块结构，包括四页签（本人承诺、他人交办、等待反馈、待核查结果）、负责人/期限/状态/会议四个筛选条件、五列业务记录、分页和右侧核查详情。数据只来自当前 BOSS 身份有权读取的 `GET /api/boss/ui/tasks`。实际业务时钟由该接口返回 `business_clock`，逾期属性不得依赖运行电脑的日历时区，更不得将空记录填成零。

**本人承诺**拥有独立的 `self_commitment` SQLite 对象，不冒充员工交办。BOSS 单独确认以下四项原子动作：`boss.commitment.create`、`boss.commitment.extend`、`boss.commitment.complete`、`boss.commitment.cancel`。创建必须填写期限、重要程度和证据要求；完成必须提供当前有效的来源 ID 与版本；延期必须晚于既有期限；取消保留审计而撤销后续到期提醒。每次写入使用已有 BEGIN IMMEDIATE、角色权限、乐观版本、幂等回执和 15 分钟范围授权。无真实员工账号、消息发送或资金操作。

**个人任务提醒**保存为 `owner-due:{commitment_id}` 的模拟业务事件，来源和任务状态可以相互核对。规则与本机 CronService 共用模拟业务时钟。实际外部通知发送、收件人确认及运行恢复仍未证明。已完成任务的历史证据如被撤销，N05 标为 `NEEDS_REVIEW`，不将旧来源当作当前有效证据。

**F06 对员工交办催办**经独立本人授权，不复用创建/首次发送的授权。即使原任务已经进入 WAITING_FEEDBACK，后续催办也保留单独的对象版本和记录；不得改变现有期限、确认完成或生成真实外部送达回执。当前用户界面保持与 F08 通讯记录的任务关联核对。

**F04/F06 → F08**：老板经独立确认将缺失资料请求或催办保存为 DRAFT 后，React Desktop 只携带服务端**已持久化**的 draft_id 到 F08；自动定位当前草稿便于阅读和进一步编辑。跨页选择**不是发送**，不会自动切换身份、跳过正文/附件校验、使用 localStorage 记忆密钥或声称真正投递。如果原草稿 ID 不存在于 BOSS 有权发件箱，则明确报错并要求重新核对。

## 工程与验证

- `validation/boss_self_commitments.py`：本人承诺生命周期
- `validation/boss_command_api.py`：四项本人动作和独立催办经受控 WebSocket 写入
- `validation/boss_page_api.py`：N05 BOSS-only 当前任务、本人承诺、关联反馈和模拟到期事件
- `app/webui/BossTaskCenter.tsx`：四页签、五列、四类查询筛选、分页及右侧实用详情
- `app/webui/BossPersonalCommitments.tsx`：有权本人承诺与交互二次确认
- `app/webui/BossDesktop.tsx`、`BossMeetingBrief.tsx`、`BossAssignmentFlow.tsx`、`BossCommunicationCalendar.tsx`：原生 N05 路由、F04/F06→F08 草稿衔接
- `app/tests/test_boss_task_center.py`、`test_boss_self_commitments.py`：当前业务时钟、来源撤销、本人任务来源、完成证据、到期事件、旧版本/并发、角色和真实消息分离

当前仅有 **SQLite 级功能测试与 React 生产构建**作为工程证据，最终请以对应 commit 的 GitHub Actions 成功结论为准。业务动作全量 E01—E06、真实 DeepSeek 完整业务链路、macOS Intel Electron 打包/权限恢复、全部 72 页及适用的 561 个视觉状态逐项截图与像素评测、真实外部通道、整个 T18/A18 仍未完成。

## 目标 Mac 待执行视觉对照

项目已有 Playwright 本地 UI 截图和 Pillow 差异核查脚本。先在开发者电脑启动 `scripts/run_boss_local.sh`，确认所需权限，再执行：

```bash
node scripts/visual_qa.cjs --role BOSS --pages N05,F06,F08,F04,F05
python3 scripts/visual_diff.py --role boss
```

上述命令是**本机验收步骤，不是已通过的检查记录**。沿用 v6 原稿的 #005BAC/#5CA63B、Logo、大鹏、桌面 204/60px 侧栏、64px 顶栏、146/122px Hero 与 278px 右栏，不降级为泛用管理后台。
