# DSH Hermes 窗口交接

交接时间：2026-11-01 11:20（Asia/Shanghai）
任务ID：U2-01、U2-03
窗口：Hermes 兼容与业务装配

## 当前状态

唯一正式状态为 `specs/feature-delivery.json`：

```text
active_feature_id = UPGRADE-2-EXECUTION
active_ticket = docs/development/UPGRADE-2-EXECUTION.md
current_stage = UPGRADE_2_CORE_IMPLEMENTATION_IN_PROGRESS
active_task_type = IMPLEMENTATION
```

U2-01 状态为 `PARTIAL`。U2-03 状态为 `PARTIAL`、`ENGINE_START_BLOCKED`。正式启动、完整隔离、真实本人认证和完整产品交付均未完成，正式门禁保持关闭。

## 源码与未提交状态

- 工作目录：`/Users/liuhaoxian/Downloads/我的/AI项目/Boss-Agent`
- 分支：`main`
- HEAD：`72d9ed63937ffca5adc525a694d0d27a13297c2c`
- 未提交条目：413 项
- 当前源码以工作树为准，未提交和未跟踪文件不能视为 main 成果。
- 没有执行 Git 回滚。

本窗口关键文件当前为未提交或未跟踪：

```text
validation/hermes_process_anchor.py
validation/hermes_anchor_supervisor.py
app/tests/test_hermes_process_anchor.py
app/tests/test_hermes_anchor_supervisor.py
app/tests/test_hermes_isolation_boundary.py
app/tests/hermes_isolation_probe.sb
docs/development/U2-01.md
docs/development/U2-03.md
packaging/product/
```

其他窗口文件、`validation/application.py`、`validation/role_channel.py`、`specs/` 和前端文件也有未提交内容。交接后先重新读取当前文件，不得以旧摘要覆盖其他窗口修改。

关键源码摘要：

```text
validation/hermes_anchor_supervisor.py
70d74c6d96fad28f856840314d326c05355599069669007bd53498f322afe212

validation/hermes_process_anchor.py
300b1302d92e89e2e08d5375c10eb23bf2c37080c2635dc1b505a8c3d9dbcedf

app/tests/test_hermes_anchor_supervisor.py
fcf6dbf7d78f4b5aa7f539a8a769e8efcaa02d077edd6f2093d6f223bdbbbb36

app/tests/test_hermes_isolation_boundary.py
17294b1ece270773e28718011004c27ffb8b1bd91451c9a0983bc75bb5ec8375
```

## 已完成的局部验证

### U2-03 锚点

`validation/hermes_process_anchor.py` 已有：

- 锚点启动报告校验。
- 锚点 PID 与实际引擎 PID 的进程组与会话归属验证。
- 控制管道和启动输入关闭。
- 单次回收保护、并发回收拒绝和回收超时关闭。
- 可选 CPU、文件大小、描述符资源限制包装。
- 同组子进程、孙进程、锚点提前退出和脱离新会话后代的局部检查。

记录结果：

```text
app/tests/test_hermes_process_anchor.py
23 passed in 30.76s
```

锚点仍未接入 `EngineProcessSupervisor`、`HermesProcessEvidence` 或产品启动。

### U2-03 独立监督适配

`validation/hermes_anchor_supervisor.py` 已使用真实 `agent_runs` 表：

- 只读 SQLite URI 和只读 `BEGIN`。
- 先校验租约持有者、代次和到期时间。
- 读取当前目标版本的等待输入事件。
- 读取当前租约代次的等待确认事件和意图状态。
- 处理终态、取消请求、超时、非零引擎退出、`QUEUED` 和异常收尾。
- 回收前再次读取状态和租约，发现租约易主返回 `LEASE_CHANGED`。
- 不写共享进程记录、不释放并发预留、不写完成检查。
- 来源授权、租约续期和事务保证未完成，分别标记 `authorization=NOT_VERIFIED`、`lease_renewal=NOT_AVAILABLE`、`consistency=SNAPSHOT_ONLY`。

最新合法测试：

```text
PYTHONPATH="$PWD/validation:$PWD/.work/upgrade2/u2-03/clean-hermes" \
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.work/upgrade2/u2-01/temp" \
.work/upgrade2-u2-04/locked-env/bin/python -m pytest -q app/tests/test_hermes_anchor_supervisor.py \
--basetemp=.work/upgrade2/u2-03/anchor-supervisor-no-auth-001 -p no:cacheprovider --tb=short
```

结果：

```text
16 passed in 14.20s
```

已移除本轮曾加入的真实 HTTP 生产者联合测试及其 `boss-1` 身份和 bearer capability 构造。真实 HTTP 联合路径保持 **NOT_RUN**。等待事件 `goal_revision` 的代码来源仍是 `validation/hermes_transport.py` 的实际生产者。

### U2-03 隔离探针

`app/tests/hermes_isolation_probe.sb` 当前允许默认行为，拒绝受保护路径、拒绝外部网络，只允许指定本机端点，并拒绝两个 mach lookup。隔离子集检查：

```text
app/tests/test_hermes_isolation_boundary.py
app/tests/test_hermes_no_spawn.py
app/tests/test_hermes_isolation_status.py
```

结果：

```text
8 passed in 6.50s
```

已验证：

- 工作目录读写。
- 受保护测试目录读写拒绝。
- 符号链接越界读取拒绝。
- 指定本机端口可连接，未允许端口拒绝。
- fork、posix_spawn、detached 子进程在禁止 profile 下拒绝。
- 隔离状态接口保持 `NOT_VERIFIED` 和 `launch_allowed=false`。

仍未隔离：

- `scutil --dns` 在受限制进程仍成功。
- `dscacheutil -q host -a name localhost` 在受限制进程仍成功。
- 系统配置、DNS 解析和其他系统服务未完整隔离。
- 原有测试 profile 使用 `allow default`，不能作为正式产品 profile。

### U2-01 固定环境与制品

U2-01 记录固定 Hermes commit：

```text
903230b1e23e0c496b28e5d2e8c4f2639cd506b6
```

固定源码归档 SHA-256：

```text
2902bae7c50d1a93b10cc7a42042dc0c54a40f8b665de91b54e88553f20cff7b
```

`uv.lock` SHA-256：

```text
e6d08c634c3f9a252a896135a9c30324776fa343ce68432e88d22f2968f257e2
```

当前记录的产品源分发和轮子：

```text
.work/upgrade2/u2-01/product-sdist-025/boss_agent_product_runtime-0.1.0.tar.gz
.work/upgrade2/u2-01/rebuilt-wheel-025/boss_agent_product_runtime-0.1.0-py3-none-any.whl
sha256: 3c50a178833a7c9e3a6f7975487d327e3ebbbe007d45c4a5ea1d18749142f134

.work/upgrade2/u2-01/alt-wheel-026/boss_agent_product_runtime-0.1.0-py3-none-any.whl
sha256: 15db2cdbc8f2ea56cd0f65b00db59dde4e4029914ba5f351a4b946437700f6d7
```

U2-01 记录称两个轮子包含当前 `hermes_anchor_supervisor.py` 和 `hermes_process_anchor.py`，源码摘要与当前文件一致。该结论只适用于制品清单和文件摘要，不代表完整产品运行。

前端源码重建、桌面、skills、完整依赖制品和正式安装入口仍未通过。

## 上次停止时的检查

最后完成的检查：

```text
app/tests/test_hermes_isolation_boundary.py
app/tests/test_hermes_no_spawn.py
app/tests/test_hermes_isolation_status.py
```

结果：`8 passed in 6.50s`。

随后执行：

```text
app/tests/test_hermes_resource_exec.py
app/tests/test_hermes_process_launch.py
app/tests/test_hermes_process_evidence.py
```

结果：`21 passed, 1 failed`。

失败项：

```text
test_supervisor_dual_failure_keeps_first_exit_error
```

失败表现为 `hermes_budget_gateway._report` 解析 usage JSON 时出现 `JSONDecodeError`。该用例单独运行：

```text
1 passed in 3.43s
```

该项是顺序依赖或测试间状态污染问题，当前未修复，不能把整组 `21 passed, 1 failed` 登记为全部通过。没有正在后台运行的检查任务；交接时没有测试进程、锚点进程或资源包装残留。

## 未解决失败与阻碍

1. `test_supervisor_dual_failure_keeps_first_exit_error` 在资源/进程证据组合中顺序失败，单独通过。根因未定位。
2. U2-03 独立监督适配未接入 `EngineProcessSupervisor`、`HermesProcessEvidence` 或产品启动。
3. `AnchorRunStateStore` 的租约续期、来源授权、父子运行检查未接入；`lease_renewal=NOT_AVAILABLE`、`authorization=NOT_VERIFIED`。
4. 读取状态和回收之间无法稳定控制租约易主或取消竞争；该竞争为 **NOT_RUN**，没有使用测试替身证明。
5. 负责人提前退出后的同组后代回收仍为 `LEADER_ONLY`/`NOT_VERIFIED`；脱离新会话后代和锚点异常退出后的后代回收为 **NOT_RUN**。
6. 产品隔离门禁 `launch_allowed=false`，`require_isolation()` 始终拒绝。macOS 仅发现 `/usr/bin/sandbox-exec`，没有可用容器或虚拟机后端。
7. 沙箱 profile 的系统服务边界不足：`scutil --dns` 和 `dscacheutil` 仍可读取 DNS 和系统配置。
8. U2-01 固定依赖存在 `browser-harness 0.1.13` 要求 `pillow==12.3.0`、固定上游使用 `Pillow==13.0.0` 的声明冲突。`DECLARATION_COMPATIBILITY=FAIL`，完整浏览器、截图、视频和 Pillow 13 API 兼容未验证。
9. U2-01 官方 PM、桌面制品、完整依赖锁、前端重建和正式安装入口未完成。
10. U2-02 运行接口、用量接口、完成核查和恢复仍有 503/保守过期路径；真实本人认证、会话订阅、来源证明和并发预留释放未通过。
11. 真实本人认证、真实模型成功路径、业务写入、成果读取和正式启动均为 **NOT_RUN**。

## 隔离与依赖阻碍

- Hermes 和业务环境分别要求独立 Python 版本；当前记录为业务 Python 3.12、Hermes Python 3.14.9。
- 产品启动依赖固定 Hermes commit、完整依赖锁、可重建制品和隔离后端。
- 当前只具备 `sandbox-exec` 的局部文件/端口/进程派生验证，缺少完整文件根、网络出口、系统服务、资源和后代回收证明。
- 没有容器、虚拟机或 launchd 产品接入。
- 共享运行记录、迁移、并发预留和完成检查由 U2-02 维护，不得由本窗口修改。
- 不得通过降级、`--no-deps`、元数据改写、mock、伪造身份或替代凭据规避依赖和隔离条件。

## 允许目录

U2-03 工单允许：

- `docs/development/U2-03.md`
- Hermes 专属模块和测试
- `validation/hermes_process_manager.py`
- `validation/application.py`
- `validation/role_channel.py`
- `.work/upgrade2/`

本窗口后续按当前用户授权继续限定在 U2-03 专属监督模块、锚点、直接测试和 U2-03 工单。U2-01 只允许其记录和 `.work/upgrade2/`；产品包装文件归属由主执行者协调。

不修改共享 Schema、U2-02 运行记录、并发预留、完成检查、用户资料和用户实例。

## 依赖顺序

1. U2-01 固定源码、依赖、制品和隔离条件。
2. U2-02 身份、会话、租约、运行状态、事件、完成检查和恢复接口。
3. U2-03 Hermes 引擎适配、工具装配和正式运行。
4. U2-04 成果、U2-06 计划、U2-07 前端、U2-08 迁移/恢复和 U2-09 验收按各自依赖继续。
5. 全部窗口完成后由主执行者协调正式集成和用户验收。

U2-03 正式完成不得早于 U2-01 和 U2-02 的前置条件。

## 主记录

- `specs/feature-delivery.json`
- `docs/development/UPGRADE-2-EXECUTION.md`
- `docs/development/U2-01.md`
- `docs/development/U2-03.md`
- `docs/PRD2.0.md`
- `docs/HLD2.0.md`
- `docs/升级2.0详细设计.md`
- `docs/升级2.0执行与验收计划.md`

## 完成条件

U2-01 完成条件仍未满足：

- 固定 Hermes 版本、依赖声明和锁文件可重建。
- 官方 PM、桌面和产品制品可实际安装、启动和验证。
- 真实模型、工具、取消、事件和 usage 覆盖实际路径。
- 文件、网络、系统服务、资源和后代回收隔离通过。
- 前端重建、桌面制品和正式启动入口可用。

U2-03 完成条件仍未满足：

- 实际引擎通过产品适配启动并调用获准业务工具。
- 本人认证、会话订阅、租约、取消、来源变化和记忆变化通过。
- 完整模型请求预算、事件、usage、完成检查和回执通过。
- 进程归属、取消、超时、租约失效、异常退出和后代回收可证明。
- 产品启动、隔离门禁和用户验收通过。

当前 U2-01、U2-03 均保持 `PARTIAL`，不得登记正式完成，正式门禁保持关闭。
