# DSH 前端窗口交接记录

交接编号：DSH-HANDOVER-UI；日期：2026-11-01；任务：U2-07（含 U2-09 前端验收）；唯一状态任务：`UPGRADE-2-EXECUTION`；当前状态：IN_PROGRESS，未登记完整交付。

## 必读与授权

接手前必须完整读取 `AGENTS.md`、[开发接手与执行规范](../开发接手与执行规范.md)、`specs/feature-delivery.json`、[升级执行主记录](UPGRADE-2-EXECUTION.md)、[U2-07](U2-07.md)、[U2-09](U2-09.md)、[PRD2.0](../PRD2.0.md)、[HLD2.0](../HLD2.0.md)和[升级详细设计](../升级2.0详细设计.md)。本交接只记录当前事实和条件，不授予共享文件、认证、运行产品或用户实例的操作权限。

## 任务 ID 与范围

| 项目 | 当前内容 |
|---|---|
| 任务 ID | U2-07；前端验收关联 U2-09 |
| 用户结果 | N02 运行、身份、来源、成果、取消、恢复和完成核查的连续界面行为；旧响应不得覆盖当前范围 |
| 主记录 | [U2-07](U2-07.md)；验收检查记录 [U2-09](U2-09.md)；公共执行记录 [UPGRADE-2-EXECUTION](UPGRADE-2-EXECUTION.md) |
| 唯一状态 | `specs/feature-delivery.json` 的 `active_feature_id=UPGRADE-2-EXECUTION`，`active_task_type=IMPLEMENTATION` |
| 当前阶段 | `UPGRADE_2_CORE_IMPLEMENTATION_IN_PROGRESS`；完整产品交付 `NOT_COMPLETE`；视觉 `NOT_VERIFIED`；用户验收 `PENDING_USER_ACCEPTANCE` |

## 当前源码与 Git 状态

工作目录：`/Users/liuhaoxian/Downloads/我的/AI项目/Boss-Agent`。

- 分支：`main`
- HEAD：`72d9ed63937ffca5adc525a694d0d27a13297c2c`
- `git status --short`：编写本文前 413 项，本文新增后 414 项；包含多个窗口的既有未提交和未跟踪内容；未提交 Git。
- 唯一状态中的 `implementation_commit` 为 `636ba070a0111adfccc587e225a972ae8e5d0a05`，`baseline_commit` 为 `7a2be73a864232ec1dfb866ab2246101e4eaf063`；当前工作树以 HEAD 加未提交内容为准，不能把任意未提交文件当作 main 成果。
- 本窗口最近涉及的前端文件均为未提交或未跟踪内容；其他窗口文件保持原状，没有回滚或覆盖。

当前前端关键摘要：

| 文件 | SHA-256 |
|---|---|
| `app/webui/Upgrade2CompletionInspection.tsx` | `533754a43ff2be0768a7621f5698faa5f4787a393d0962c3940da99ea37a62b8` |
| `app/webui/Upgrade2ResumeStatus.tsx` | `8004a82edf0ce19f0840c1feab29f39ef062192e0bf8cd0e6cbe4f06db5dc95b` |
| `app/webui/Upgrade2RunPanel.tsx` | `77934430de2dfc6d8cab4b44c21f33e94c126fa42f63480ed719b448d20347d9` |
| `app/webui/Upgrade2ConversationRun.tsx` | `14dad0404710236b59d9d03e4e7303782cd4308bd4d89d81d7e3ad863bf05e9a` |
| `app/webui/useUpgrade2Run.ts` | `a2aa401b1de0fe8aceade19a2565f9b134a0088ebde019786176790e18f1126b` |
| `app/webui/upgrade2-run-client.ts` | `d42da03811ac02aca6813cc3250f51a7741f0f4e407c93e8372dc5e7b4c9fb4d` |
| `app/webui/upgrade2-run-scope.ts` | `9c9eaa57efb783363ebd0dbc3d75b0f93262fea0c413877a39c0a19fac44bd60` |
| `app/webui/RunInputReceiptStatus.tsx` | `4ad2b4db16e921bf5e34b040273a84ff9b43099dfe6154199f7fabca98de0b68` |
| `app/webui/MinutesEditGuard.tsx` | `b733525c6280de843685cd49d6610181954d350555f0ffcebcd2157ec5eeafcb` |
| `app/tests/u2_09_completion_logic_check.cjs` | `6ee9bc0897ac273e43631a4e88d068734dbd993629dd13cae66817d7b649c6c5` |
| `app/tests/test_u2_09_completion_logic.py` | `a95e31e169f72e4bab79059ad8f8f7777693d9d879655d8b76bed2d792ba9bab` |

注意：U2-07 完成核查小节中 `upgrade2-run-client.ts` 的旧摘要 `4c117...` 对应完成核查类型加入前的源码；当前摘要是上表 `d42da0...`。接手后若获准更新 U2-07，应把该历史摘要保留为“该次检查时源码”，并另记当前摘要；本次交接只记录差异，未修改其他文件。

## 已验证事实与证据

以下均为局部技术检查，不等于真实本人流程或完整产品验收。

### 完成核查前端读取

- `upgrade2-run-client.ts` 已接入 U2-02 的 `GET /api/v2/runs/{run_id}/completion-inspection`，包含 `CompletionInspection` 类型、路径方法和不抛异常的 Schema 检查。
- `Upgrade2CompletionInspection.tsx` 使用 `XMLHttpRequest` 读取，校验 `run_id`、`current_goal_revision`、`finish_event_id`、`run_revision`；父组件从连续事件中取最近 `RUN_FINISHED` 编号传入。
- `stale=true` 时首行显示“历史核查记录，不作为当前完成结果”，不显示历史 `completion_state`；阻断项标题为“历史核查阻断项”。
- `stale=false` 时才显示当前完成状态；阻断项包含“进程组退出未核查（PROCESS_GROUP_EXIT_UNVERIFIED）”等实际值。
- 运行或 token 变化时中止旧请求并清除旧范围数据；读取错误、超时和 Schema 错误不保留旧核查。
- `node app/tests/u2_09_completion_logic_check.cjs` 输出 `{"blocker_label":true,"historical_notice":true,"historical_state_hidden":true,"finish_goal_run_match":true,"invalid_schema_rejected":true,"wiring":true}`。
- `app/tests/test_u2_09_completion_logic.py` 结果 `1 passed in 0.98s`。
- 全源码 TypeScript 检查 `tsc -p app/tests/upgrade2-full-source-tsconfig.json --pretty false` 退出码 0。

该检查没有使用真实完成核查记录，也没有使用手工 `RUN_FINISHED`。真实监督回执、本人认证后的成功读取、真实 401/403/404/409/503 和真实 `stale` 响应均为 `NOT_RUN`。

### 恢复条件错误与迟到响应

- `Upgrade2ResumeStatus.tsx` 使用 `XMLHttpRequest` 的 `onload`、`onerror`、`ontimeout` 和本地超时计时器；不使用 Promise 拒绝回调、`catch` 或 `try/catch`。
- 网络不可连接检查 `1 passed in 13.31s`；Schema 错误、HTTP 503 与有效状态检查 `1 passed in 12.92s`；HTTP 401 检查 `1 passed in 63.85s`。
- 超时、组件卸载、运行 A 到 B、token A 到 B 和 401 清理组合检查 `1 passed in 20.92s`；旧延迟响应没有更新新页面。
- 这些检查使用项目内独立技术服务和实际组件，不校验本人认证，不作为真实认证或完整恢复证据。

### 其他已检查行为

| 行为 | 结果 | 边界 |
|---|---|---|
| 运行结果读取失败时隐藏旧正文并提供重新读取 | `app/tests/test_u2_07_result_render.py` `1 passed in 9.41s` | 错误状态由页面输入，真实 409 未执行 |
| F05 来源不可用后的重新核查 | `app/tests/test_u2_07_domain.py` `1 passed in 19.18s` | 使用独立模拟数据库；本人认证未执行 |
| 运行 A 延迟响应后切换运行 B | `app/tests/test_u2_09_run_switch.py` `1 passed in 29.21s` | 独立服务不认证；最终页面为 B，旧 A 正文隐藏 |
| 取消请求、结果核查与已取消显示 | `app/tests/test_u2_09_cancel_state.py` `1 passed in 9.14s` | 技术运行，真实本人取消未执行 |
| 补充输入回执当前/历史/高于当前版本 | `1 passed in 8.00s`；当前复验 `1 passed in 3.96s` | 技术存储，真实本人补充未执行 |
| token 变化且存在未保存编辑时提示 | `1 passed in 2.88s` | 只提示内容已清除，不恢复草稿 |
| 引擎失败原因显示 | `app/tests/test_u2_09_failure_ui.py` `1 passed in 2.08s` | 已有监督产生的 `ENGINE_PROCESS_EXIT` 事件；没有手工 `ENGINE_GROUP_UNVERIFIED` |
| 运行说明检查 | `6 passed`；最近一次 `11.23s` | 文档与链接检查，不代表业务 |

旧版 `app/tests/test_v6_minutes_approval_ui.py` 为 `4 failed, 3 passed`：一项缺少 v6 设计文件，三项为旧文案断言，对应字符串在 HEAD 源码中同样不存在。该结果不能登记为通过。

## 未完成验收

以下保持 `NOT_RUN` 或 `NOT_VERIFIED`：

- 真实本人认证、真实产品服务和正式 Hermes 监督链路。
- 完成核查的真实成功响应、`stale=true` 真实响应、真实 401/403/404/409/503、真实完成事件编号和目标版本变化。
- 执行空间切换的真实入口、即时隐藏、真实 409、WebSocket 1008、迟到请求和未保存内容处理；没有切换广播，只有下一次请求或连接关闭。
- 运行切换、身份变化和 token 变化后的完整页面连续操作；已有局部组件检查，不替代真实流程。
- 跨认证未保存草稿的保存与恢复；当前只有内容清除提示，没有可验证的会话关联。
- 正式成果列表、打开、版本关系和导出；产品成果路由仍受本人认证和工作区隔离限制。
- 完成核查前端成功路径、真实历史核查展示及阻断项呈现；当前只验证了纯逻辑和 Schema 拒绝。
- 独立可重建前端、正式启动入口、Electron 宿主连续操作、72 页完整业务验收、视觉检查和用户验收。
- 旧版 v6 检查失败项的负责人核查。

## 依赖与共享交接

| 依赖 | 需要提供的内容 | 当前状态 |
|---|---|---|
| U2-02 | 完成核查路由与 Schema 已存在；真实运行记录、版本和过期响应 | 路由已具备；真实记录未取得 |
| U2-03 | 实际 Hermes 监督产生的 `RUN_FINISHED`、退出与完成核查记录 | 未完成 |
| U2-04 | 正式成果投影、受限读取、打开和导出 | 关闭/`NOT_RUN` |
| U2-05 | 记忆与方法的真实采用、删除传播 | 局部检查，真实流程未完成 |
| U2-06 | 计划触发与恢复 | 正式调度关闭 |
| U2-08 | 独立安装、备份恢复、桌面启动 | `NOT_RUN` |
| 主执行者 | 认证、公共 Schema、正式状态、最终集成 | 由主执行者维护 |

共享认证、`validation/application.py`、`validation/role_channel.py`、运行存储、公共 Schema 和 Hermes 文件不由前端窗口修改；需要字段或行为时提交具体接口、权限和错误语义交接。

## 允许目录

本窗口允许修改：

- `app/webui/` 前端专属组件、样式和客户端。
- `app/tests/` 对应前端检查。
- `docs/development/U2-07.md` 与 `docs/development/U2-09.md` 的对应记录。
- `docs/升级2.0运行与接口说明.md` 中已授权的运行说明更新。
- 已授权的 Electron 宿主和前端准备文件。

本次交接任务只允许新增 `docs/development/DSH-HANDOVER-UI.md`，没有修改其他文件。

禁止修改：Hermes 专属模块、`validation/application.py`、`validation/role_channel.py`、其他窗口的运行、成果、计划和迁移主记录、唯一正式状态、用户资料和凭据。不得使用脚本修改代码或文档，只能使用文件编辑工具。

## 下一步

1. 在获准条件下取得实际监督产生的完成核查记录，验证成功、`stale=true`、`finish_event_id`、目标版本和运行版本；不要手工发送 `RUN_FINISHED`。
2. 使用真实执行空间切换入口验证旧请求、事件轮询、WebSocket 关闭和未保存内容；没有通知入口时保持 `NOT_RUN`。
3. 用真实本人认证验证完成核查 401/403/404/409/503 和运行切换后的旧响应隐藏。
4. 接收 U2-04 正式成果投影后再验证列表、打开、版本关系和导出。
5. 更新 U2-07 中 `upgrade2-run-client.ts` 的当前摘要与历史摘要对应关系。
6. 在前端可重建入口和正式启动条件具备后执行完整构建、桌面连续操作、视觉检查和用户验收。

## 具体完成条件

- 真实服务、真实本人身份和实际监督记录下，完成核查的成功、历史、缺字段、权限和错误状态均按实际响应显示；旧核查不会作为当前结果。
- 运行或 token 变化后的迟到响应不能更新新运行页面；执行空间切换有可验证的通知入口和实际清理证据。
- 运行、恢复、取消、补充输入和完成核查的页面操作具有实际服务回执，权限和异常检查分别通过。
- 正式成果读取和导出、跨认证未保存内容处理按实际接口完成并验证。
- 源码摘要、命令、环境、结果和限制逐项记录；没有 mock、伪造身份、手工完成事件或虚假成功响应。
- 视觉检查、用户验收和完整产品交付分别登记；没有用户确认时保持 `PENDING_USER_ACCEPTANCE`。
