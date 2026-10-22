# T18/T19 · 会后纪要、审批与模拟申请真实开发切片

> 日期：2026-10-22。实施状态：**部分代码已开发并通过源码/SQLite/CI 检查；A18、A19 和整套 PRD 验收仍未通过**。本页补充此前 T18.md/T19.md，保留已有 F06/A04 工作成果。

## 实际范围和高保真依据

实现依赖 `docs/PRD.md` 的 FR-04/FR-05/FR-07/FR-25/FR-26/FR-28，直接读取原始 `Boss-Agent-Desktop-Complete-v6/pages/F05-纪要核查.html`、`F07-申请审阅.html` 和 `A03-数据集.html` 的布局/交互定义；沿用 v6 固定 Logo、大鹏角色、#005BAC、#5CA63B 和 44px 可点击控制尺寸。依据原版设计 CSS 校正统一桌面 Shell 的 204px 侧边栏、64px 顶栏、146/122px Hero、20px Hero 圆角、278px 右侧信息区。1024px 桌面窗口切到 60px 图标栏；2560 等高 DPI 和 macOS 实际截图仍待检查。

### 新增真实工程文件

| 文件 | 实现 |
|---|---|
| `validation/boss_meeting_approval.py` | 会议纪要分类/保存/确认，模拟申请登记/补件升版/审批决定；原始来源有效性、金额 Decimal、申请人、对象和版本校验 |
| `validation/boss_command_api.py` | 通过现有已认证 nanobot WebSocket 操作白名单执行，BOSS/MAINTAINER 权限隔离，事务+幂等+原子授权审计 |
| `validation/boss_workspace_api.py` | BOSS-only `minutes`/`approvals` 和 MAINTAINER-only `approval-admin` 数据投影；N11 只读记录新增老板纪要确认/审批动作 |
| `validation/boss_page_api.py` | D01 原文允许读取随后创建、仍获准的模拟附件，并检查来源撤销和对象所属权 |
| `app/webui/BossMeetingApproval.tsx` | F05 四分类编辑、版本确认、原文片段选择；F07 当前附件/金额/币种/本人的三个独立决定；A03 明确模拟申请与补件入库 |
| `app/webui/BossDesktop.tsx` 和 `boss-v6.css` | 真实业务子页接入和 v6 外观结构修复；不使用 `iframe` 或把原始 HTML 误当可运行页面 |
| `scripts/visual_qa.cjs` | 在目标 Mac 真正启动后，检查 1440/1280/1024 视口的顶栏、侧栏、Hero 高度/圆角、Logo/大鹏加载情况，并保存当前运行界面截图用于后续像素对比 |
| `app/tests/test_boss_meeting_approval.py` | 真实 SQLite 版本、角色、来源撤销、幂等和完成链路测试 |
| `app/tests/test_v6_minutes_approval_ui.py` | 真实组件入口、原稿 Token、固定尺寸及安全声明的静态回归 |

## FR-05 会议纪要状态与授权

老板逐条选择 `OPINION` / `SUGGESTION` / `DECISION` / `ASSIGNMENT_DRAFT`，必须提供正文及**确实出现在当前未撤销原文中的来源片段**；保存后状态为 `DRAFT_REVIEW`，原有纪要版本保留为历史快照。老板再明确确认当前版本后才进入 `CONFIRMED`。前后步骤分别拥有业务回执，确认的授权记录只保存条目哈希和原文版本，不向维护者暴露原文。

**保存或确认纪要不自动创建任务、不发送草稿、不赋予其他联系人登录权限。** 需本人进一步明确负责人、期限、证据并在 F06 单独执行交办动作；缺材料、撤销文档或版本冲突时拒绝进一步操作。

## FR-07 审批与补件状态

初始没有虚构的“待审批项目”。A03 维护端必须显式建立 `SIMULATED` 申请及其附件，包括合法内部模拟申请人标识、明确的 CNY 金额、正文和来源版本。维护者不能代替老板审批。老板打开 F07 后才可选择同意、拒绝或请求补充（默认无选择），每个决定绑定 `application_id`、`expected_version`、`source_id/source_version`、金额、币种、本人意见和授权。

`APPROVE` 仅记录 `APPROVED_RECORDED` 的模拟审批状态，**不会发生资金交易或专业放行**。材料过期或撤销时不能批准。请求补充进入 `WAITING_MATERIAL`；A03 可持版本条件补充说明、附件及金额，将原申请和旧附件保留为历史版本，并把当前状态改为 `PENDING_DECISION`，等待老板重新审核。历史授权不能自动用于新的金额或附件。后续真实支付系统、审批流对接和多币种情况不在本次已实现范围。

## 验证与剩余阻塞

运行方式：

```bash
# GitHub Actions 已配置的项目域测试（CI 使用合成数据，无真实模型密钥）
python -m pytest -q app/tests/test_boss_meeting_approval.py app/tests/test_v6_minutes_approval_ui.py

# Mac 本地已启动研发应用后，需单独人工确认所呈现页面与源截图
node scripts/visual_qa.cjs --role BOSS --pages F05,F07
node scripts/visual_qa.cjs --role MAINTAINER --pages A03
python3 scripts/visual_diff.py --role boss
```

CI 自动测试包括源片段伪造阻断、重复请求、旧会议/来源版本、维护越权、申请金额更改、材料撤销、请求补充→补件升版→老板重审及独立资金处理标识。构建/测试结果以执行该代码 commit 的 Actions 记录为准，不能把单测 PASS 当作完整产品验收。

仍待：F04 完整生成会前材料、F08 非任务消息草稿/外部发送、FR12 私人安排真实授权分享、多组织/多币种审批场景、单独真实附件审核、全部农业业务来源、561 适用 UI 状态与逐页 Mac 高 DPI 像素对照、端到端 DeepSeek+Electron、完整 E01—E06、正式签名/公证安装包、全部 T05—T10 依赖验收。以上未执行项在页面或映射中仍为 `PARTIAL` 或 `NOT_RUN`，不应宣称完成。
