# T18 · N07/N08/F26/N10 本人设置与通知实际采用

> 日期：2026-10-23（北京时间）。本轮按照 PRD FR-01/02/13/26/28、AC-01/02/13/28 与 Desktop v6 高保真页面规范接续开发。
>
> **状态**：增量功能代码及固定上游编译/SQLite 自动化测试范围可检查；T18 仍 IN_PROGRESS / A18 NOT_RUN。目标 Intel Mac 实机、正式 DeepSeek 行为和逐页像素验收尚未通过；不得把 CI 成功等同真实产品验收。

## 本次开发的业务交互

### N07：本人目标与关注要求

- 使用独立 React 业务页 `BossOwnerPreferences.tsx`，保留统一 Desktop v6 Shell、蓝绿白色系和大鹏 IP，表单有本人目标、关注主题、阅读要求、适用范围、有效期、当前版本、历史版本和采用状态。
- `boss.owner.goals.save` 创建或更新本人的 **DRAFT_NOT_EFFECTIVE**，保存时使用草稿版本 CAS、幂等和严格内容长度验证；不会立即改变 F01、F04、聊天上下文。
- `boss.owner.goals.confirm` 再校验草稿原文摘要、草稿/有效版本与有效期，老板单独授权确认 **CONFIRMED**。旧有效配置在新草稿保存时保持生效，不被静默覆盖。
- `BossPageAPI._dashboard` / F01 会根据适用范围显示当前确认目标与阅读要求；F04 将适用的目标版本和来源计入待复核状态；F10 人员会面引用当前适用范围的目标。初始演示资料不是本轮亲自确认目标，未确认时不能把合成偏好当成真实老板设置。
- 原生 nanobot `RuntimeContextBlock` 新增有效的 `OWNER_WORKSPACE` 本人设置内容；实际调用 provider 后留最小采用次数与版本。 `DAILY_BRIEF` 和 `MEETING_PREP` 严格限制到对应页面，不会不加区分注入通用聊天。上下文调用不代表 DeepSeek 已遵守要求。

### N08：通知要求与可见范围

- 独立 v6 页面支持 IANA 时区、免打扰整点区间、本人暂停通知、重要事件允许跳过本人免打扰、阅读格式、有效期；分享边界固定 `BOSS_ONLY` / `BUSY_ONLY`，对指定联系人共享仍由 F12 独立授权。
- `boss.owner.notice.save` 和 `boss.owner.notice.confirm` 与 N07 一样有 **草稿与本人确认分离**、CAS 版本、内容摘要、幂等回执和最小审计。
- 有效通知策略被现有 `ControlStore.dispatch_due_in_transaction` 直接读取；与 A13 的技术规则合并时只能**增加**本人静默/暂停限制，不能绕过技术暂停、取消、规则免打扰、去重及冷却。没有第二套 Cron 定时器。
- F02/N06 从同一 SQLite 展示当前本人策略版本和每个实际模拟事件的 `dispatch.state/reason/owner_notice_version`。 `DELIVERED` 是模拟事件数据库结果，**不是 macOS 系统通知或对真实人员的送达证明**。

### F26：本人设置入口

- `BossSettingsHub.tsx` 以 v6 卡片展示 N07/N08 的实时确认状态；直接进入 F13、N09、N10、N11、F12、F01 等已有页面。
- “退出当前会话”复用上游原生 `onLogout`；不另造 token 管理与员工账号。
- `BossDesktop` 追加 N07/N08 的未保存编辑保护，离开时复用原 D06 模态框，提示放弃当前编辑；保存失败保留同一个幂等请求编号并支持原回执查询。

### N10：本人授权撤销

- 在 `BossWorkspaceView.tsx` 的 N10 清单里增加“撤销此项未来授权”，要求先填写原因、选择目标授权、核查目标版本并再次本人确认。
- `boss.authorization.revoke` / `boss_owner_authorizations.py` 在同一原子 SQLite 事务中校验 BOSS、稳定授权 ID、本人归属/范围、版本、尚未撤销、尚在有效期；写入撤销元信息、单独撤销授权与幂等回执。
- 权限读取只返回当前本人的授权元信息和可撤销状态，不返回原授权隐私载荷；撤销原因不写入技术审计明文。
- 仅拦截对**旧授权的未来使用**；不会撤回已经发生的交办、发送、审批决定或外部消息，也不会删除原审计事件。授权扩权、第三方撤销和真实消息恢复不在本轮完成范围。

## 实际代码路径和测试

| 类别 | 实际文件 |
|---|---|
| 领域逻辑 | `validation/boss_owner_preferences.py`、`validation/boss_owner_authorizations.py`、`validation/controls.py` |
| 已认证服务 | `validation/boss_command_api.py`、`validation/boss_workspace_api.py`、`validation/boss_page_api.py`、`validation/application.py` |
| 原版 v6 UI 接入 | `app/webui/BossOwnerPreferences.tsx`、`BossSettingsHub.tsx`、`BossDesktop.tsx`、`BossWorkspaceView.tsx`、`BossMeetingBrief.tsx` |
| 构建与回归 | `scripts/prepare_boss_webui.py`、`.github/workflows/boss-agent-desktop.yml`、`app/tests/test_boss_owner_preferences.py`、`app/tests/test_boss_owner_authorizations.py`、`app/tests/test_v6_owner_preferences_ui.py` |
| 当前覆盖 | `specs/page-service-map.json`（N07/N08/F26/N10） |

测试重点：本人设置无草稿时不得假生效；保存与确认是不同的 SQLite 操作；角色与归属无权访问；两阶段 CAS/同一幂等回执、过期与重复、私人明文不进入日志、确认后 F01/F04 实际采用及通用 Runtime 范围隔离、技术 Cron 与本人通知策略“更严格的一方”生效、单独撤销后原业务决定仍保持。

本地复现（在已克隆仓库及锁定依赖就绪时）：

```bash
python -m pytest -q app/tests/test_boss_owner_preferences.py app/tests/test_boss_owner_authorizations.py app/tests/test_v6_owner_preferences_ui.py app/tests/test_v6_contract.py
python scripts/prepare_boss_webui.py --build
```

所有 CI 结果应以所引用 commit 的 [GitHub Actions](https://github.com/LIUgongxi2046/Boss-Agent/actions) 为准。严格区分 Python 静态/SQLite 回归、React 编译、Linux CI 运行以及目标 Mac 的实际 Electron/DeepSeek/像素视觉实测。

## 仍未完成

- **N09 本人计划**目前仍为只读引用；不应在老板端另起第二个 Cron 责任源。正式创建/变更/暂停/取消须与 A13 和 PRD 进一步打通。
- N07 的 DeepSeek 真实采用质量、长会话/中断恢复、范围语义等未在目标 Mac 验证；N08 的真实系统通知权限、休眠唤醒与外部投递未做实机验收。F01 事项自主排序、真正逐日汇总、F02 规则全场景与农业专业资料仍有缺口。
- 72 页 561 状态的可用性、屏幕缩放、字体、像素、Mac Intel 安装、真实模型和 E01—E06 综合验证仍没有完整通过证据。原始 v6 视觉基线没有改变，新增页面还需正式逐页比对。农业指标数据留待功能稳定后按 T21—T23 补充；本轮没有增加虚构 KPI。


## 最新验证回执（已核查）

截至本次功能代码提交 `4be661d3d0993ff33014bb2ff52204e49332adb2`，对应 [GitHub Actions 39891454896](https://github.com/LIUgongxi2046/Boss-Agent/actions/runs/39891454896) 的两项任务均为 **success**：Python 安全/领域/回归 **346 passed**，固定上游 nanobot React/TypeScript/Vite 生产构建通过。后续仓库提交仅补交接文档及交付台账，不能据此推导出新的目标 Mac Electron 或像素验收结果。
