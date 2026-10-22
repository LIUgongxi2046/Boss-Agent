# T18 · F05 已确认纪要 → F06 独立交办业务闭环（开发切片）

**日期：2026-10-22。状态：部分功能代码已提交；T18/A18、完整 PRD 和 macOS 视觉验收仍未通过。**

## 依据与约束

严格依据 `docs/PRD.md` FR-05、FR-06、FR-08、FR-28 以及
`Boss-Agent-Desktop-Complete-v6/pages/F05-纪要核查.html` 与
`F06-交办详情.html`。使用已确认的 Desktop v6 Logo、大鹏场景图、
蓝绿白色板、原有双栏和卡片/表单控件，不另建降级 UI。

选择数据集仍是 `ui-check`，`meeting-1`、`meeting-minutes`、
`finance-note` 和 `coordinator-1` 均来自既有已批准模拟资料。
**本轮不扩充或伪造新的农业业务数据。**

## 实际业务链

1. F05 对每条原文保存 `OPINION`、`SUGGESTION`、`DECISION` 或 `ASSIGNMENT_DRAFT`，本人明确确认整个纪要，形成 `CONFIRMED` 和固定版本。**仅确认纪要并不自动建任务。**
2. 本人进入“逐项交办”，选择已确认且仍有效的 `ASSIGNMENT_DRAFT`，核对交办目的/产物、唯一负责人 ID、截止时间/时区、证据要求和原始纪要来源。界面弹出分项确认。不是 `ASSIGNMENT_DRAFT`、纪要尚未确认、版本过期或文档撤销，一律拒绝创建。
3. `boss.minutes.assignment.create` 是 BOSS-only 命令，复用原有 `BossCommandAPI._create`、`Store.create_assignment`，在同一个 `BEGIN IMMEDIATE` 事务中保存任务、授权、纪要-条目版本关联、幂等回执和脱敏审计。每个**已确认纪要版本 + 条目**最多创建一个任务。同一请求重复/并发回放只有一个真实任务；不同请求无法重复创建同一版本条目的任务。已确认的新纪要版本可以独立授权新任务，但旧任务和旧关联保持历史可读。
4. F05 的 `GET /api/boss/ui/workspace/minutes` 通过实际任务回读关联任务 ID、状态、版本、模拟发送计数及来源版本。任务表和纪要保持独立持久化；**不会修改已确认的纪要正文**。F06 的 `GET /api/boss/ui/tasks` 返回该任务的 `origin_minute_id`、`origin_minute_version`、`origin_entry_id`、`origin_source_id` 和 `origin_source_version`，便于双向回查。
5. 新任务固定为 `OPEN`，没有自动外部发送。老板必须在 F06 **再一次明确确认** `boss.assignment.send`；此后 F05 才显示 `WAITING_FEEDBACK / SENT_SIMULATED`。真实外部送达仍未实现。后续模拟进展、延期和完成仍遵守原 FR-06。
6. F06 任务详情按实际任务 ID 同时读取原始 F06 交办发件和 F08 后续模拟消息。各条消息的 `SENT_SIMULATED`、`NOT_VERIFIED` 和模拟回复状态分别保存、分别展示，老板可以进入 F08 核对原消息与回复。真实外部投递依然没有成功凭证；模拟回复可以进入任务 PROGRESS，但不会绕过老板完成确认。
7. 网络超时或结果不确定时可查 `GET /api/boss/ui/operation-status` 的**原幂等请求 ID**，命中只返回获准的任务/纪要版本和状态，不返回会议正文。未命中不能当作未执行而换编号盲目创建。

## 失效源的读取边界

经单独授权的源原文撤销、access_scope 变化或版本更新后，
`minutes` 读取端保留历史纪要类型、条目 ID、状态和来源版本，
但会把原正文、原引用锚点清空，设置 `source_reference_state=NEEDS_REVIEW`；
实际存储的历史纪要继续供权限受控的审计，当前页面不能用失效正文建交办。
新任务建立前也会在**同一事务**复核纪要原始来源和业务财务来源。

## 代码和可复现测试

- 服务端：`validation/boss_meeting_approval.py`、
  `validation/boss_command_api.py`、
  `validation/boss_workspace_api.py`、
  `validation/boss_page_api.py`、
  `validation/boss_recovery_api.py`。
- UI：`app/webui/BossMinutesAssignmentActions.tsx`、
  `app/webui/BossMeetingApproval.tsx`、
  `app/webui/BossAssignmentFlow.tsx`、
  `app/webui/BossDesktop.tsx`，仍通过原固定 nanobot 版本的
  `scripts/prepare_boss_webui.py` 合入。
- SQLite 集成用例：`app/tests/test_boss_minutes_assignment_chain.py`，
  覆盖未确认纪要、意见不能派单、维护越权、确认后唯一任务、F05/F06双向回读、
  独立发送、并发幂等、撤销会议来源和财务来源、失效正文不泄漏、
  纪要版本更新后的旧任务保留、原文不进入单独链接或审计。
- v6 映射回归：`app/tests/test_v6_minutes_approval_ui.py`。

在目标 macOS Intel 应用真正运行后，需分别检查：

```bash
node scripts/visual_qa.cjs --role BOSS --pages F05,F06,N05,F08
python3 scripts/visual_diff.py --role boss
```

**这些 Mac 运行/真实 DeepSeek/浏览器点击/像素级差异及真实外部投递尚未有成功回执。**
不能把 GitHub CI 构建通过或部分业务联通理解为整套 PRD 已经交付。
原始 72 页中的绝大多数仍只完成不同程度的业务实现；T18/T24 等正式验收保留待办。
