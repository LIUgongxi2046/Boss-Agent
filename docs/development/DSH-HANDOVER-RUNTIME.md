# DSH 运行管理窗口交接

## 任务

任务 ID：`UPGRADE-2-RUNTIME`，覆盖 U2-02、U2-04、U2-06、U2-08。

接手目的：继续运行管理、成果、计划调度和迁移恢复的局部实施与验证，不切换到完整产品运行，不替代主执行者完成公共认证、正式集成或用户验收。

## 必读

接手后必须完整读取：

1. [AGENTS.md](../../AGENTS.md)
2. [开发接手与执行规范](../开发接手与执行规范.md)
3. [唯一状态](../../specs/feature-delivery.json)
4. [执行主记录](UPGRADE-2-EXECUTION.md)
5. [U2-02](U2-02.md)、[U2-04](U2-04.md)、[U2-06](U2-06.md)、[U2-08](U2-08.md)
6. [PRD2.0](../PRD2.0.md)、[HLD2.0](../HLD2.0.md)、[升级详细设计](../升级2.0详细设计.md)

`specs/feature-delivery.json` 的顶层活动任务为 `UPGRADE-2-EXECUTION`，当前阶段为 `UPGRADE_2_CORE_IMPLEMENTATION_IN_PROGRESS`；V7/MENU-N03 位于保留的嵌套产品范围。U2 各项实施与验证细节采用对应工单和执行主记录。

## 源码与工作区

```text
工作目录: /Users/liuhaoxian/Downloads/我的/AI项目/Boss-Agent
分支: main
HEAD: 72d9ed63937ffca5adc525a694d0d27a13297c2c
未提交变更: 415 项
```

U2 相关未提交变更主要涉及：

- `validation/agent_run_*.py`
- `validation/hermes_budget_gateway.py`
- `validation/hermes_run_recovery.py`
- `validation/hermes_source_invalidation.py`
- `validation/agent_artifact_*.py`
- `validation/agent_schedule_*.py`
- `validation/hermes_schedule_adapter.py`
- `validation/agent_simulation_recovery.py`
- 相关迁移、测试和工单记录

这些变更没有形成对应提交。接手者必须重新读取当前文件，不能把旧制品、旧摘要或旧测试数量当作当前源码证据。

## 本地验证与证据

### U2-02 运行管理

已完成局部验证：

- 运行存储、租约、取消、运行关系和事件重读。
- 父子运行共享预算、累计快照、缺失根运行、祖先循环和额度用尽。
- 终态业务回执只读测试覆盖缺失意图和无业务回执行，核查前后运行状态、租约、事件和回执数量不变。
- 终态行动草稿的本人身份路径已停止，`TERMINAL_ACTION_DRAFT_INSPECTION=NOT_RUN`。
- 最近预算边界检查：`app/tests/test_agent_run_usage_events.py` 与 `app/tests/test_hermes_budget_gateway.py`，结果 `16 passed in 33.79s`。
- 终态业务回执与运行草稿相关合法检查：`27 passed in 99.81s`。

证据位置：

```text
app/tests/test_agent_run_usage_events.py
app/tests/test_hermes_budget_gateway.py
app/tests/test_agent_run_result.py
app/tests/test_agent_action_draft_completion.py
docs/development/U2-02.md 第29、30节
```

产品公开用量、恢复和完成重新核查入口仍返回 `503`。

### U2-04 成果

已完成局部验证：

- 五种文件格式生成、解析和内容重读。
- 成果版本、来源、文件预算、撤销和发布记录核查。
- 会议简报逐段审计已进入内部成果服务和完成检查。
- 既有安装与成果目标迁移检查为 `12 passed`；成果组合检查曾报告 `81 passed`。

证据位置：

```text
docs/development/U2-04.md
app/tests/test_agent_artifact_goal_migration.py
app/tests/test_agent_simulation_migration_install.py
app/tests/test_agent_artifact_brief_audit.py
```

公开成果读取、逐段缺口展示、本人认证后的生成和导出未验证。

### U2-06 计划与调度

已完成局部验证：

- `HermesScheduleAdapter` 的技术时间、配置版本和候选去重检查。
- 发生门禁、抑制回执和重复派发检查。
- 发生门禁与调度适配器联合检查 `23 passed in 40.86s`。
- 抑制回执单独检查 `3 passed in 12.88s`。

证据位置：

```text
docs/development/U2-06.md
app/tests/test_agent_schedule_occurrence_gate.py
app/tests/test_hermes_schedule_adapter.py
app/tests/test_agent_schedule_receipts.py
```

`dispatch_scheduled_event` 仍由 `require_plan` 拒绝，产品调度适配器没有接入抑制回执读取；正式定时任务关闭。

### U2-08 迁移与恢复

已完成局部验证：

- 独立模拟数据库迁移、重复安装和中断恢复。
- 快照、隐私差异、成果撤销和来源历史预检。
- 恢复组合检查 `47 passed in 43.09s`。
- 隐私结果、来源历史和恢复预检联合检查 `19 passed in 14.63s`。
- 恢复日志、隐私差异和来源历史检查 `17 passed in 18.41s`。

证据位置：

```text
docs/development/U2-08.md
app/tests/test_agent_recovery_artifacts.py
app/tests/test_agent_recovery_privacy_delta.py
app/tests/test_agent_recovery_preflight.py
app/tests/test_agent_recovery_deletion_evidence.py
app/tests/test_agent_simulation_recovery.py
```

正式恢复仍被设计禁止，`restore` 在缺少真实本人身份服务和可信删除历史时拒绝执行。

## 未完成验收

```text
AUTHENTICATED_BOSS_FLOW=NOT_RUN
PUBLIC_RUN_API=NOT_RUN
PUBLIC_BUDGET_USAGE_API=NOT_RUN
PUBLIC_ARTIFACT_READ_AND_EXPORT=NOT_RUN
PUBLIC_COMPLETION_RECHECK=NOT_RUN
TERMINAL_ACTION_DRAFT_INSPECTION=NOT_RUN
REAL_HERMES_RUN=NOT_RUN
COMPLETE_PROCESS_GROUP_EXIT=NOT_RUN
FORMAL_SCHEDULE_DISPATCH=NOT_RUN
FORMAL_RECOVERY_AND_INSTANCE_SWITCH=NOT_RUN
FRONTEND_REBUILD=NOT_RUN
FULL_PRODUCT_RUN=NOT_RUN
VISUAL_ACCEPTANCE=NOT_RUN
USER_ACCEPTANCE=PENDING
```

U2-02、U2-04、U2-06、U2-08 均不能登记完整产品交付。

## 接口状态

| 接口 | 当前状态 | 限制 |
|---|---|---|
| 运行创建、读取、输入、取消和事件重放 | 内部实现及局部 HTTP 检查 | 真实本人认证和会话订阅未验收 |
| 用量快照读取 | 内部事务读取 | 公开 `GET /api/v2/runs/{run_id}/usage` 返回 503 |
| 运行恢复 | 内部恢复服务及路由检查 | 路由返回 503；完整进程组退出未证明 |
| 完成核查及重新核查 | 内部只读核查 | 公开重新核查返回 503；非空简报或草稿保守标记过期 |
| 成果生成与重读 | 内部成果服务 | 公开读取、导出和页面展示未验收 |
| 计划候选与发生门禁 | 技术候选 | 正式派发未接入，`require_plan` 继续拒绝 |
| 迁移预检 | 独立模拟数据库 | 正式数据库迁移和实例切换未执行 |
| 恢复预检与恢复 | 内部只读预检 | 正式恢复被删除历史完整性和本人授权条件阻止 |

## 前置依赖

- U2-01：固定 Hermes 版本、Python 3.14 独立环境、完整进程隔离和进程组退出证明。
- U2-03：Hermes 工具适配、方法选择、业务回执和运行请求链路。
- U2-05：记忆、来源撤销传播和会话上下文。
- U2-04/U2-06/U2-08 之间：成果目标版本、运行租约、计划发生记录和迁移恢复顺序。
- 公共认证、公开 API、Schema 和最终集成由主执行者协调。

## 允许目录

允许修改：

```text
validation/agent_run_*.py
validation/hermes_budget_gateway.py
validation/hermes_run_recovery.py
validation/hermes_source_invalidation.py
validation/agent_artifact_*.py
validation/agent_schedule_*.py
validation/hermes_schedule_adapter.py
validation/agent_simulation_recovery.py
validation/migrations/upgrade2_*.sql
app/tests/test_agent_run_*.py
app/tests/test_hermes_*.py
app/tests/test_agent_artifact_*.py
app/tests/test_agent_schedule_*.py
app/tests/test_agent_recovery_*.py
docs/development/U2-02.md
docs/development/U2-04.md
docs/development/U2-06.md
docs/development/U2-08.md
.work/upgrade2-u2-02/
.work/upgrade2-u2-04/
.work/upgrade2-u2-06/
.work/upgrade2-u2-08/
```

禁止修改：

- `specs/feature-delivery.json`
- 公共认证、公开 API 路由和共享 Schema
- `validation/application.py`、`validation/hermes_product.py` 等公共装配入口
- Hermes 固定源码和锁定依赖
- 前端准备脚本、设计资源和用户实例
- 用户资料、凭据、账号数据库和运行数据库

共享文件需要主执行者交接后才能修改。

## 主记录

执行主记录：

```text
docs/development/UPGRADE-2-EXECUTION.md
```

任务工单：

```text
docs/development/U2-02.md
docs/development/U2-04.md
docs/development/U2-06.md
docs/development/U2-08.md
```

本交接文件：

```text
docs/development/DSH-HANDOVER-RUNTIME.md
```

## 下一步完成条件

接手后按依赖顺序继续：

1. 重新核对当前源码、未提交变更、对应工单和测试入口。
2. 在不构造本人身份、不读取用户资料的前提下，继续 U2-02 运行事务、预算谱系、终态只读核查的合法内部测试。
3. 继续 U2-04 成果内容、来源撤销和文件重读检查；公开导出等待认证入口。
4. 继续 U2-06 计划发生、抑制回执和调度适配器检查；正式派发等待 U2-03 和公共入口。
5. 继续 U2-08 迁移预检、恢复阻断和独立模拟数据库检查；正式恢复等待可信删除历史和本人授权。
6. 只有真实本人认证、完整进程组退出、正式 API、前端重建和完整运行均通过后，才更新主记录和用户验收状态。

正式门禁保持关闭。
