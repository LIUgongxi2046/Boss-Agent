# T18 增量：F10 人员会面、F11 行程安排及 F04 关联复核

> 时间：2026-10-23（北京时间）
> 范围：PRD FR-10、FR-11 与 F04 会前材料；Desktop v6 F10/F11 原设计和既有 F04 UI。
> 基线：交接文档所述 `a83e627`；变更在 `main`，源码和测试以该分支最新 SHA 为准。
> 状态：**业务功能开发与 CI 协议回归已有检查；T18/A18 整体验收未通过，目标 Mac 实机和视觉像素验收 NOT_RUN。**

## 实际完成的功能

### F10 人员会面（FR-10、AC-10-S/E）

- BOSS 独立模块 `app/webui/BossPeopleMeeting.tsx`，保留 v6 左右栏、联系人/职责/目的筛选、历史交办、待回答问题、来源与依据、底部本人决定区。
- `validation/boss_people.py` 实现 `boss.people.prepare` / `boss.people.attach` / `boss.people.detach`。所有写入使用 `BossCommandAPI` 同一 `BEGIN IMMEDIATE`、角色判断、幂等键、CAS 版本和最小审计路径。
- 按 **contact_id** 而非显示姓名匹配；有效职责绑定当前模拟业务时钟；使用可追溯历史任务、当前交办、已保存模拟反馈；只引用当前 BOSS 有权访问且明确指定版本的材料原文。不推断私人个性、背景或已完成状态。
- 会议选择仅允许已获准的固定 `meeting-1`；老板单独确认后，把会面材料关联到已有**模拟会议议题**，可明确取消并记录原因。不修改参会人员名单、不自动创建联系人账号、不发消息或真实日历邀请。
- 被撤销/换版的来源不可继续授权加入；历史已保存材料仅保留 ID/版本等元信息，隐藏失效原文。任务/反馈变化会使已保存核查版本失效。
- F04 `compile_brief` 的 `people_meeting_impacts` 展示实际关联议题；F04 历史材料在已确认议题变化后标记 `NEEDS_REVIEW`，保持旧版本审计记录。

### F11 行程安排（FR-11、AC-11-S/E）

- 独立 `app/webui/BossTravelView.tsx`，保留 v6 工作台、表单、左右栏、状态和本人确认弹窗。
- `validation/boss_travel.py` 实现 `boss.travel.review` / `boss.travel.confirm` / `boss.travel.cancel`，草稿核查与本人确认拆分；支持修改待核查稿、保留已确认旧版直到新版本确认，版本并发拒绝、重复回执和取消审计。
- 必须给出 IANA 时区及本地明确 UTC 偏移；拒绝不存在的 DST 时刻、时区偏移不符、倒序或超长行程。已发生的事实来自模拟业务时钟，不自动猜测交通时间。
- 基于现有会议**已知开始时间**、私人日历 busy 时段、任务到期、其他已确认行程及缓冲时段作冲突预检。会议结束时间未知时必须承认不确定性。缺少交通依据、预订和天气资料时明确保留缺口。
- 确认事务中重新核对联系人、有效来源及版本、任务期限、私人日程、关联会议和模拟时间等依赖，要求本人明确勾选冲突及缺少交通依据。任何依赖变化需重新核查。
- F04 `travel_impacts` 显示确已确认且影响已知会议的行程；改动触发会前材料重新核查。**不进行真实订票、天气查询、外部日历改期、消息发送或伪造交通凭证**。

## 接口、代码和数据边界

| 页面 | 读接口 | 写动作 | 权限 |
|---|---|---|---|
| F10 | `GET /api/boss/ui/workspace/people`、`GET /api/boss/ui/operation-status` | `boss.people.prepare`、`boss.people.attach`、`boss.people.detach` | BOSS |
| F11 | `GET /api/boss/ui/workspace/travel`、`GET /api/boss/ui/operation-status` | `boss.travel.review`、`boss.travel.confirm`、`boss.travel.cancel` | BOSS |
| F04 | 原 `GET /api/boss/ui/workspace/briefing` | 继续使用原本人保存动作 | BOSS |

- 新对象种类：`person_brief`、`person_brief_revision`、`travel_plan`、`travel_revision`，均在原 `ControlStore` 的 `objects`/ `audit`/ `idempotency` 表中，不修改固定原始模拟快照。
- 入口：`app/webui/BossDesktop.tsx`；构建复制：`scripts/prepare_boss_webui.py`；服务：`validation/boss_command_api.py`、`validation/boss_workspace_api.py`。
- 未增加模拟经营事实、客户项目数据或真实密钥；维护端只能读取原技术权限范围，不能读取 F10/F11 的 BOSS-only 业务工作区或代本人执行。
- `specs/page-service-map.json` 中 F10/F11 改为独立功能组件，仍保持 `actual_e2e_verified=false`、`visual_pixel_verified=false`；所有 72 页正式视觉/实机结果仍不可宣称通过。

## 自动化回归范围与复现

```bash
python -m pytest -q app/tests/test_boss_people.py app/tests/test_boss_travel.py app/tests/test_boss_meeting_brief.py app/tests/test_v6_contract.py
python scripts/prepare_boss_webui.py --build
```

CI 在 `.github/workflows/boss-agent-desktop.yml` 已将新模块及用例纳入受控测试、密钥扫描和固定上游 React/TypeScript 生产构建。详细进度以 [GitHub Actions](https://github.com/LIUgongxi2046/Boss-Agent/actions) 及所对应提交 SHA 为准；编译及模拟 SQLite 回归**不能代替目标 Mac 浏览器交互或真实 Electron 设备验收**。

F10 回归重点：同名不同 ID、失效职责、来源撤销及历史文本遮盖、任务变化、草稿准备、显式议题加入/解除、原始授权和幂等、角色隔离、F04 材料失效。

F11 回归重点：跨时区、明确夏令时双义偏移、无效时间、会议未知结束时间、私人忙碌及任务期限冲突、其他已确认行程、交通依据撤销、CAS、确认/撤销、角色与私人文本隔离、F04 失效。

## 未完成与后续顺序（先功能再数据）

1. **整体验收仍然缺失**：目标 Intel Mac / macOS Electron 实际启动、DeepSeek 真实会话、72 页视图逐页 561 状态操作和 E01—E06 全覆盖、原始 v6 逐页像素对比、断网及设备重启恢复、打包签名和应用分发。
2. **真实连接未接入**：F10 真实会议参会者更新、个人/企业日历、外部联系人回执；F11 天气、交通、票务/住宿预订、日历改期。这些不能用现有模拟 SQLite 确认结果冒充。
3. **现有固定模拟域限制**：现时只含一个获准业务会议、有限联系人和资料，F10/F11 版本化动作已能验证，但多会议、多联系人、多出行场景、跨机构真实同步仍待按 PRD 扩展模型与接口契约。
4. 下一步继续功能优先，补全其余部分页面的授权操作、来源失效联动、跨页回读与异常恢复。后续再扩大农业多业务模拟明细和对照报表，不在此阶段填造 KPI。
