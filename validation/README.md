# T02 接入验证工程

业务材料为 D02 授权的 SIMULATED 数据。模型范围仅 DeepSeek；工具、HTTP、SQLite、Cron、原生 WebUI DOM 和 Electron 均实际运行。固定上游 nanobot 0.3.5、Electron 45.0.0。完整环境、首次下载与配置说明见 [选型环境](../docs/选型环境.md)，逐项断言、复用矩阵及限制见 [选型验证](../docs/选型验证.md)。

## 配置和运行

当前 connection.json 通过 credential_file 引用用户指定的服务端 Markdown 文件；connection.example.json 为无密钥模板。connection.py 只在服务端读取凭据；不要复制密钥到代码、命令参数、浏览器或证据。模型入口不自动加载 .env。临时数据、依赖、数据库和安装包位于被忽略的 .work/、.venv/、desktop/node_modules/。

在 validation 目录执行：

```bash
mkdir -p .work/tmp
TMPDIR="$PWD/.work/tmp" UV_CACHE_DIR="$PWD/.work/uv-cache" uv sync --locked
TMPDIR="$PWD/.work/tmp" .venv/bin/python connection.py
TMPDIR="$PWD/.work/tmp" .venv/bin/python check_runtime.py
TMPDIR="$PWD/.work/tmp" .venv/bin/python model_probe.py
TMPDIR="$PWD/.work/tmp" .venv/bin/python fault_probe.py
```

实际前端必须按选型环境从固定上游源码构建。`.venv/bin/python application.py` 启动业务服务和原生两端；另一个终端运行 check_ui_business.py/check_admin.py。集成入口 check_reuse.py 自动拥有并结束应用进程，执行用户 DOM、管理配置两次保存重载、重启及下一任务采用；要求初始 maxToolIterations=8。管理独立检查会在 8/9 之间切换，必须明确按页面要求重启后核查生效值。

desktop/check-desktop.cjs 自动启动实际 Electron 和 Python 服务，检查真实模型采用、记忆删除、任务重读、IPC、尺寸、缩放、重复启动、最后窗口关闭和重启。桌面与 standalone application 使用同一端口及 FileLock，不能同时启动。所有检查只采集 DOM/ARIA 文本，不采集截图。

## 检查入口与职责

| 文件 | 真实职责 |
|---|---|
| business.py / controls.py / service.py | 确定性业务材料、JSON Schema、SQLite/FTS5、本人授权、反馈与完成、资料撤销、规则和服务端角色 |
| check_materials.py | 独立读取实际持久初始资料，核对 IM01—IM10 必需字段及实体关系 |
| check_local.py | 真实 HTTP、Decimal 复算、幂等、范围/角色拒绝、配置版本、保存重读、进程重启与重置 |
| check_scheduler.py | 上游 CronService 真实计时及两个独立进程的恢复、暂停、取消 |
| check_controls.py | 反馈、老板决定、授权/资料撤销、私人日历、同版本并发、业务时钟和提醒规则 |
| model_probe.py | 两个相同初始快照的独立 DeepSeek 共同任务，记录输入 hash、实际 API 和新 session 重读 |
| connection.py | 官方 API 与官方 SDK 接入记录；流式 response_id、usage 由官方 SDK 解析 |
| fault_probe.py | 实际模型资料注入、产品变化、轮数限制、部分执行、取消、消费流关闭及真实接口 503/超时 |
| application.py / role_channel.py | 原生 UI 生命周期、工具、会话、配置快照、唯一调度、实际角色鉴权与进程退出 |
| check_ui_business.py / check_admin.py / check_reuse.py | 实际 Chrome DOM、正式 API、两端配置采用及持久状态核对 |
| inventory.py / source_audit.py | 固定归档、安装版本、完整 docs、全部 Python 编译、前端与桌面依赖声明和许可原文 |
| summarize_evidence.py / audit_evidence.py | 全部尝试的真实用量与费用覆盖、代码 hash、敏感凭据扫描 |
| capture_validation.py / capture_reuse.py | 调用统一记录器保存实际命令、退出码、当前依赖范围及输入 hash |
| desktop/main.cjs / preload.cjs / package.mjs | Electron 宿主、渲染隔离、固定 IPC、Python 子进程所有权、官方打包 |
| desktop/check-system.cjs | 用户可配合时执行实际系统权限与人工操作检查；本次完整系统过程未验证 |

`.venv/bin/python capture_validation.py models <全新目录名称>` 可生成正式模型命令记录，runtime/faults/desktop 同理；输出位于项目 evidence/T02。两端使用 `.venv/bin/python capture_reuse.py <全新目录名称>`，已有目录存在时立即拒绝覆盖。

结果的 PASS 限定于对应检查范围。T02/A02 本轮选型可行性按用户 D18 决定完成，固定项目基础可供后续改造。未验证变体和系统条件逐项交接后续任务，完整业务页面由 T18/T19 验收。没有真实企业收益、全部模型质量统计、语音、跨系统兼容或最终产品安装器的通过声明。
