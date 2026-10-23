# Boss-Agent 项目开发交接文档（v2.0）

> 编写日期：2026-10-23（北京时间）  
> 仓库：[LIUgongxi2046/Boss-Agent](https://github.com/LIUgongxi2046/Boss-Agent) · 目标分支：`main`  
> 本次交接核对基线：`3627e594b0c5f518908112b6dcc3ef1567b8a1cb`（创建本文档之前的 HEAD）  
> 最近一次**已核验完整成功的功能代码 CI**：`4be661d3d0993ff33014bb2ff52204e49332adb2`，对应 [Actions 39891454896](https://github.com/LIUgongxi2046/Boss-Agent/actions/runs/39891454896)  
> 项目状态：**持续开发中；不是正式发布、不是 PRD 全量验收，也没有达到 Desktop v6 像素级验收。**
>
> **接手的首要原则：沿现有开源代码继续开发，遵守 PRD 和冻结的 v6 UI，先补完整功能及异常闭环，再补农业数据。不得用页面数量、模拟成功或 CI 构建结果替代实机验收。**

## 1. 接手时的真实进度（唯一口径）

截至本交接核对，`delivery-ledger.json` 共 27 个正式工单（T00—T26），`specs/page-service-map.json` 共 72 个页面。

| 维度 | 已核对结果 | 解读 |
|---|---|---|
| 正式工单 | **4 ACCEPTED / 5 IN_PROGRESS / 18 TODO** | **23 项尚未完成验收**；正在进行 T03、T11、T17、T18、T19 |
| 已验收的工单 | T00、T01、T02、T04 | 早期价值/需求、选型及 HLD 结果；**不是产品完工** |
| 验收条目 | **4 PASS / 1 BLOCKED / 29 NOT_RUN** | A03 设计验收 BLOCKED；A18、A19、A24—A26 尚无正式通过记录 |
| 72 页覆盖 | **70 页部分接入 / 2 页占位或上游认证承接** | N01、D08 仍为 `DESIGN_PLACEHOLDER_ONLY`；很多“接入”只是只读状态或技术信息 |
| 真实桌面 E2E | **0/72 通过** | `actual_e2e_verified` 全部为 `false` |
| 逐页高保真像素验收 | **0/72 通过** | `visual_pixel_verified` 全部为 `false`；不是说 72 页都没有 React，而是**尚无按原图验收的结果** |
| 自动化代码检查 | **346 项 Python 测试通过；React 生产构建通过** | 仅对应功能代码提交 `4be661d` 的 Ubuntu CI；**不能证明 Mac、DeepSeek 完整会话、通知、语音和 UI 像素已通过** |
| 当前最新分支 | 以 `git rev-parse HEAD` 为准 | 这份交接和 README 更新之后 HEAD 会再次前进；无需将文档提交等同于功能复测 |

**口径优先级**：当前 `main` 代码、`delivery-ledger.json`、`specs/page-service-map.json` 与**同一提交**的 Actions 记录优先。过去各批开发记录里的历史测试数和页面数只说明对应时点的状态。

## 2. 不能更改的产品和设计约束

1. **用户对象：一个老板。** BOSS 是唯一业务使用者，MAINTAINER 是独立技术维护身份；联系人、资料作者和交办对象不是产品账号。不建设部门 Agent、部门独立工作台或部门登录体系。
2. **电脑桌面优先。** 目标为 Intel Mac、macOS 13.7.8（详见 `docs/选型环境.md`）。后续实际 GUI、模型与系统权限验收必须在目标电脑完成；**不要使用 Codex 云端环境代替本机开发和演示**。GitHub CI 只负责代码校验。
3. **固定已选架构。** [HKUDS/nanobot](https://github.com/HKUDS/nanobot) v0.3.5，锁定上游提交 `1bb712d3488915ca4ed9ccc1a93067ff722f5ab9`；Electron 45.0.0、React、Python 3.12、SQLite/FTS5、DeepSeek（原配置 `deepseek-flash`）。复用现有 WebUI、会话、模型、Tool、Skills、设置和 Cron，不另造基础 Agent。
4. **视觉基线不能降级。** `Boss-Agent-Desktop-Complete-v6/` 内已冻结的 72 页、561 个设计状态以及 Logo、蓝绿白配色（`#005BAC`、`#5CA63B`）、大鹏吉祥物和动画为准；新功能必须嵌入统一 Desktop v6 Shell，尊重原有布局、间距、组件、浮层和交互态。实现后需要截图逐页比对，不能用系统默认表单取代设计稿。
5. **功能优先，数据靠后。** 先完成本人真实业务操作及前后状态、授权、失败回执、跨页引用、持久化；T21—T23 后补专业农业模拟明细。未知 KPI 一律显示缺口/待核查，不允许编造经营数值、成本、趋势或真实 ROI。
6. **模型与来源真实性。** 模型接口、Tool 执行和持久化必须真实调用；业务数据可明确标为 `SIMULATED`。`SENT_SIMULATED`、SQLite 派发 `DELIVERED`、Prompt 运行时上下文被加载，都**不等于**真实外部消息送达、模型遵从或真实业务完成。
7. **安全边界。** MAINTAINER 不能读取/篡改老板私人正文、替本人确认记忆、撤销本人授权、审批、发送或确认交办完成；使用稳定对象 ID、当前来源版本和每动作授权；历史资料撤销或换版后的旧正文不能从缓存继续流出。
8. **敏感信息不入库。** 绝对不提交 `boss agent.md`、`validation/connection.json`、`.work/`、`validation/.work/`、`access.json`、密钥、Token、真实私人材料或敏感日志。不在 issue/commit message 中粘贴凭据。

### 必读规范及可信来源

| 优先级 | 文件 | 接手用途 |
|---|---|---|
| 1 | [PRD](PRD.md) | FR-01—FR-32、管理端需求、BR/AC、E01—E06，新增功能以此逐条核对 |
| 2 | [项目决策记录](项目决策记录.md) | 单老板、上游复用、模型、桌面边界和明确授权 |
| 3 | [最终 HLD](HLD.md) / [72 页 HLD 映射](../specs/hld-72-page-map.json) | 架构、对象流、身份与跨模块依赖 |
| 4 | [Desktop v6 页面源](../Boss-Agent-Desktop-Complete-v6/index.html) / [设计状态索引](../Boss-Agent-Desktop-Complete-v6/meta/v6-状态关联.json) | 每个原版页面及其状态，不可只凭页面标题开发 |
| 5 | [实时页面与服务映射](../specs/page-service-map.json) | 每页实际组件/读接口/写动作/尚缺功能，以及 E2E、视觉状态 |
| 6 | [交付台账](../delivery-ledger.json) / [项目计划](Boss-Agent项目计划.md) | T00—T26 依赖、阻塞、验收证据和实施顺序 |
| 7 | [历次开发记录](development/index.md) | 某次功能代码的具体决策、测试边界和仍待修复缺口 |

## 3. 已开发的业务功能和真正未覆盖的边界

**下表的“已接入”仅表示当前代码可读/可写的业务切片，不代表对应完整 FR / AC 已通过。**

| 页面/范围 | 已有实际代码能力 | 下一位开发者必须继续核查或补齐 |
|---|---|---|
| F01、N02、F03/N03 | v6 今日工作与原生会话入口、获准模拟指标查询和来源定位；F01 显示已确认的本人目标版本 | **F01 真正的今日事项分类/排序及持久化调整**、按日期聚合、来源更新缺口、跨页会话一致性 |
| F02/N06/N08 | 老板知晓/暂缓/关闭提醒；N08 分草稿和本人确认通知时区/免打扰/暂停要求，加入原 Cron SQLite 派发判定；F02/N06 读回实际模拟抑制原因 | 恢复/冷却/去重边界、通知端到端、休眠恢复、系统权限和实际外部投递 |
| F04/N04 | 有版本的会前材料、参会者/历史承诺/任务/来源检查，变化后 `NEEDS_REVIEW`；缺口可创建 F08 消息草稿；联动 F10/F11 与 N07 | 多会议、真实外部日历/资料请求、修改后所有依赖重新核验、原设计全部状态 |
| F05→F06/N05 | 纪要分类、本人确认后逐条创建独立任务；交办单独授权模拟发送，进展/延期/完成和独立催办；原来源 ID、版本、条目与任务关联 | 真实外部收件回执、任务复杂异常、重启后授权和重复投递全路径检查 |
| F07/A03 | 维护端录入模拟申请、附件/金额版本；老板分别同意、拒绝、要求补件并重查 | 真实审批提供方、流程扩展；不得实现资金交易或专业放行 |
| F08/A04 | 消息草稿、版本和单独确认模拟发送、回执和联系人署名模拟回复，任务进展关联 | 外部消息 Provider、身份核验、真实送达、分渠道失败恢复 |
| F09 | 有效资料检索、版本和引用、资料撤销/变更失效、缺资料时转草稿 | 真正企业知识源与语义检索质量、时效更新、完整模型研究评测 |
| F10 | 按稳定联系人 ID 和有效职责准备会面，从任务/反馈/资料形成依据；老板授权将议题附到现有模拟会议或解除 | 多真实会议、真实会议名单/邀请/外部人员通信 |
| F11 | 行程草稿、时区和 DST 校验、会议/私人忙碌/任务截止冲突、本人单独确认/变更/取消 | 实际交通、票务、天气、住宿和日历 Provider；不能假装已经预订 |
| F12 | 私人日历本人编辑与忙碌时段分享/撤销；维护端无私人正文 | 真实日历及第三方收件、系统级隐私删除/备份审查 |
| F13/N07 | 个人记忆确认/停止未来采用；N07 目标、主题、阅读要求保存草稿再单独确认，并按范围传给 F01/F04 和适用的 Runtime Context | 当前模型是否正确遵守已确认内容的独立实测，长期版本和删除传播 |
| F26/N10 | 本人设置中心汇总有效版本及原生退出；N10 原授权 ID、CAS 版本、有效期核验后本人撤销未来权限 | 审计全部授权消费点对 `revoked` 的实际拒绝；真实设备断线及界面恢复验证 |
| N09 | 可以查看当前计划状态及模拟业务时钟 | **本人计划创建/修改范围/暂停/取消及执行结果**，只复用 A13 唯一技术调度来源 |
| A05/A07/A13 | Prompt 草稿→校验→激活/停用及 Runtime Context 加载记录；知识源版本 CAS 和 SQLite FTS；技术调度配置/启停/模拟触发 | 真实 DeepSeek 采用效果、真实知识撤销传播、Mac Cron 休眠恢复、独立配置/权限验证 |
| A01/A09/A10 等 | 部分技术目录、运行元数据、指标定义与只读投影 | 保存→校验→启用→实际采用链路，Tech 与 BOSS 权限隔离及验收 |
| F24/F27/F30/A15 | 模型实际元信息/Token 观察；本地语音捕获和转写协议等部分接入 | 真实 Mac DeepSeek、多轮 Tool、原生 STT/麦克风授权、费用/模型真实质量 |
| F14—F23、V19 专题 | 农业专题筛选、资料覆盖和缺口呈现；未获准的数值保持未知 | T21—T23 的来源、单位、日期、公式、指标明细、质量校验与行业案例（**在功能完成后再补**） |

**新增一轮（本次交接前）开发摘要**：

- F10/F11 与 F04 联动详见 [T18-people-travel.md](development/T18-people-travel.md)。
- N07/N08/F26/N10 与 F01/F02/F04 的生效配置、通知限制和授权撤销详见 [T18-owner-preferences.md](development/T18-owner-preferences.md)。
- 本轮 CI 共 **346 passed** 和 React 构建成功；成功运行：[Actions 39891454896](https://github.com/LIUgongxi2046/Boss-Agent/actions/runs/39891454896)。此前 `failure`/被新提交取消的旧 CI 不作为最新功能验证结果。

## 4. 工程边界：接手时从这些文件进入

| 工程层 | 当前代码 / 责任 |
|---|---|
| 设计与统一页面入口 | `app/webui/BossDesktop.tsx`（72 页导航/角色/统一 Shell）；`app/webui/boss-v6.css`、`Boss-Agent-Desktop-Complete-v6/` |
| 独立老板 React 业务页 | `BossMeetingBrief.tsx`、`BossMeetingApproval.tsx`、`BossTaskCenter.tsx`、`BossPeopleMeeting.tsx`、`BossTravelView.tsx`、`BossOwnerPreferences.tsx`、`BossSettingsHub.tsx`；其他页见 `specs/page-service-map.json` |
| 原生服务与会话 | `validation/application.py` 启动 nanobot/DeepSeek/Cron；`validation/role_channel.py` 对 WebSocket 和 HTTP 实施身份和动作限制 |
| 业务写入 | `validation/boss_command_api.py` 为 BOSS/MAINTAINER 受控 Mutation 路由：校验身份和请求、持久化授权/业务变更/回执/审计 |
| 页面读投影 | `validation/boss_page_api.py`、`boss_workspace_api.py`、`boss_recovery_api.py`、`boss_sector_api.py`；不能绕过角色在前端拼接私人数据 |
| 领域模型 | `validation/business.py`、`validation/controls.py`（SQLite/事件/派发），`boss_people.py`、`boss_travel.py`、`boss_owner_preferences.py`、`boss_owner_authorizations.py` 和其它 `boss_*.py` |
| v6 构建叠加 | `scripts/prepare_boss_webui.py`：固定上游版本，校验 72 页/561 状态，按白名单叠加组件和素材再编译；不要改成从网上追踪 HEAD |
| 桌面宿主 | `validation/desktop/`，`scripts/run_boss_local.sh`；本机开发态与独立正式签名发行是两件事 |
| 测试和检查 | `app/tests/`、`.github/workflows/boss-agent-desktop.yml`、`scripts/check_git_secrets.py`、`scripts/visual_qa.cjs`、`scripts/visual_diff.py` |

**统一业务规则**：所有具有副作用的操作使用已认证 BOSS 或获准 MAINTAINER、明确对象/当前版本、`client_request_id`、SQLite 原子事务和最小审计；草稿、校验、确认、模拟投递和实际外部送达是不同状态。无法确认原请求结果时先查询 `GET /api/boss/ui/operation-status`，不能自动换 request ID 再写一次。失效来源不从历史缓存中返回原文。

**数据真实含义**：当前业务库按 `ui-check` 模拟执行空间运行，业务初始材料、对象引用和业务时钟由固定快照及 SQLite 控制；技术日志和业务回执不能反向提供新的业务授权。真实供应商 Model/Tool/电商/旅行/通知/日历的外部回执都必须单独建证据，不可从“本地对象已保存”推断。

## 5. 接手环境和本机复现

当前目标设备条件见 [选型环境](选型环境.md)：**Intel x86_64、macOS 13.7.8、Python 3.12、Node 24、uv、Git、固定上游联网下载能力**。上游授权/依赖按 Lock 及已核对版本处理。

```bash
# 在已克隆的 Boss-Agent 仓库根目录
git switch main
git pull --ff-only
git status --short
git rev-parse HEAD

# 本地只编译固定 nanobot 版本 + Desktop v6 Overlay
python3 scripts/prepare_boss_webui.py --build

# 受锁约束的 Python / 桌面开发依赖
cd validation && uv sync --locked && cd ..
npm --prefix validation/desktop ci

# boss agent.md 必须已由本人放于本机仓库根目录。
# 以下只读取该本机文件，绝不在命令行传入 API Key。
python3 scripts/configure_local_deepseek.py

# 启动本机 Electron + 后端（不是可分发签名安装包）
bash scripts/run_boss_local.sh
```

补充检查（在本机具备已锁定环境、登录凭据和服务时）：

```bash
validation/.venv/bin/python scripts/check_local_deepseek.py
validation/.venv/bin/python scripts/check_local_boss_agent.py

# 开发态启动并以 BOSS / MAINTAINER 两个身份实测后
cd validation/desktop && npx playwright install chromium && cd ../..
node scripts/visual_qa.cjs --role BOSS --pages F01,F02,F04,F05,F06,F07,F08,F09,F10,F11,F12,F13,F26,N07,N08,N10
node scripts/visual_qa.cjs --role MAINTAINER --pages A03,A04,A05,A07,A13
python3 scripts/visual_diff.py --role boss
```

注意：

- `validation/.work/application/access.json` 的 BOSS 与 MAINTAINER 本机令牌**仅用于本机登录和检测**，不要复制到交接文档/仓库。确认测试账号没有部门角色。
- `validation/.work/` 和 `.work/` 均为本机私有运行/构建物。不要同时启动占用同一端口的 standalone Python 入口和 Electron 宿主。
- DeepSeek 连通性检查可能产生真实调用费用；没有实际返回时保持 `NOT_OBSERVED` 和 null 费用，不自填成功。
- 视觉工具存在并不代表它已经在目标 Mac 对 72 页逐一执行。须保存每页真实图、原 v6 图、尺寸、差异与修复记录。
- Python/React 的可复现自动化测试以 [CI Workflow](../.github/workflows/boss-agent-desktop.yml) 为唯一当前命令清单；单独可优先运行 `app/tests/test_boss_owner_preferences.py`、`test_boss_owner_authorizations.py`、`test_boss_people.py`、`test_boss_travel.py`、`test_boss_fr04_09_full_flow.py`，但不能把它们视为 Mac GUI E2E。

## 6. 下一位开发者的具体任务（先功能，再数据）

### P0 · 先消除业务功能和契约断点

1. 按正式工单 **T05—T10**，把数据字典、API/错误码/权限、Agent LLD、72 页实际动作映射和可执行 BDD/验收用例收敛为可追踪契约；**T03 / A03** 的高保真源和可编辑素材验收也不能跳过。已存在的代码不自动代替这些工单完成。
2. 优先实现 **N09 本人计划**：创建/修改范围/暂停/取消、当前本人版本/执行结果回读；**只能复用 A13 技术调度单一事件/计划源**，不能再建一套老板端 Cron 或让技术维护替本人启用业务授权。
3. 完善 **F01**：按真实模拟日历、任务、承诺、审批、事件及来源更新时间生成有根据的今日分类和排序；允许本人调整次序并 CAS 保存，重启后重读仍采用本人顺序。未知来源提示覆盖缺口，不能把无数据说成没有事项。
4. 补全 **F02/F06/F04—F12/N07/N08/N10** 需要的跨页真实对象引用（task_id / meeting_id / source_id+version / message_id / authorization_id），对已撤销、过期、变更、缺少来源、重复点击、后台失败、断线恢复等执行 **E01—E06**。特别核对 N10 已撤销授权在**所有消费点**确实不能再被未来执行引用。
5. 对每个实际可操作的 v6 页面检查**控件是否真实能用、保存后是否可查、是否有正确的本人确认和失败提示**；不能以一个 read-only 卡片或纯导航视作完成相应动作。

**P0 完成条件**：至少 F04→F05→F06→F08→F09 等实际链路、N07→F01/F04、N08→Cron→F02/N06、N10→权限消费链路在模拟 SQLite 中可重复跑通；包括版本并发、二次提交、断线回执、维护身份越权和撤销来源失效的回归断言。新增功能要有 v6 页面与可复现测试。

### P1 · 技术后台、Agent 运行和真实系统能力

1. 补 **A01、A09、A10** 等技术管理页的保存→静态验证→启用→下一任务真正采用，同时维持 BOSS/MAINTAINER 访问隔离。
2. 验证 **A05 Prompt、A07 知识库、A13 Cron** 在新的 nanobot 会话/重启后实际采用并留下受限回执；应用于业务任务的效果、撤销传播和系统恢复须独立证据，不得仅引用启用开关。
3. 在指定 **Intel Mac** 上联调真实 DeepSeek Tool 多轮执行、语音 STT/麦克风权限、原生通知权限、休眠/断网/重启；对模型超时或服务端写成功但前端未收到回执的情况优先查持久化状态。
4. 如果未来要“真实发送、预订、外部日历/天气”等 PRD 功能，先核实用户授权的供应商、认证方式、权限和真实响应，不能沿用 `SENT_SIMULATED` 冒充生产功能。

**P1 完成条件**：真正的模型/系统请求 ID、状态、次数、来源/费用覆盖、失败与重启结果可审计；维护者无法代替老板决定或读取私人明文。

### P2 · 农业专业模拟数据（等功能稳定后）

T21—T23 逐专题增加**已授权且可追溯**的业务对象和明细：期间、区域/法人、稳定 ID、单位、版本、时间、生效口径、公式、验证样本和缺失情况。F14—F23/V19 指标核算必须能从明细独立复算，数据不全显示未知，不得用外销样例推断其它板块经营结果。

### P3 · 最终质量与桌面交付

- T24：按 PRD AC 和 E01—E06 完成 BOSS/MAINTAINER 真正设备端到端、多轮模型、重启恢复、安全和费用检查；72 页及适用状态在 1440×1024、1280×800、1024×768、200% 缩放等要求下保存真实截图与 v6 对照结果。**没有核验凭证不得设置 `actual_e2e_verified` / `visual_pixel_verified=true`。**
- T25：签名、公证/安装/退出/重启/恢复、打包校验和与配置迁移，在目标 Mac 验证正式可交付安装包，不把研发脚本启动等同于“已安装产品”。
- T26：逐条核对全部 FR/AC 与 D/T 台账、测试和引用证据；只有独立验收通过才变更 `delivery-ledger.json` 的 `ACCEPTED` / `PASS`。

## 7. 下次提交与交接要求

每一批可用功能完成后，按如下顺序办理：

1. 对应 PRD FR/AC、v6 页面 ID 和 561 状态索引定位改动，不重写已有架构或视觉基线。
2. 后端实际写入 + 前端实际回读/错误恢复 + BOSS/MAINTAINER 两身份安全 + 幂等/CAS 测试全部同步完成。
3. 更新 `specs/page-service-map.json`：真实组件、实际读接口、写动作、仍缺的功能及**未经实机验证的 false 字段**。
4. 更新 `docs/development/` 对应开发记录及索引；依据真实证据更新 `delivery-ledger.json`，**不得为了进度美化提前改成 ACCEPTED**。
5. 提交并推送到 `main`；记录 GitHub commit SHA、对应 CI URL、测试用例数和新旧失败。如果 HEAD 只有 docs 变更且 CI 规则未触发，明确沿用上一次**已经核验的代码提交**的 CI 证据，不称文档提交已完成复测。
6. 真正目标 Mac 设备测试另附设备/OS、启动命令、日志、深度联调回执、截图、Diff 与失败修复。**单个页面可验收不代表整体 T18/A18 通过**。

### 本次交接不做的事

- 不新增虚构 KPI、员工账号、部门 Agent、真实发送回执、API Key 或模型费用估值。
- 不把文档提交算成产品功能开发，不改动原有任务/验收状态。
- 不承诺在未执行的 Mac、外部服务或断网/休眠条件下已验证成功。

## 8. 交接结论

当前已有**可延续开发的** nanobot + Electron + Desktop v6 业务代码、受角色约束的 SQLite 写入与回执、功能闭环切片以及自动化测试基础，最近经核实的完整成功 CI 为 **346 passed + React 构建通过**。

但**剩余 23 项正式工单尚未验收**，其中 5 个在建、18 个待办；很多 72 页映射仍为部分可用或只读，72 页实际 GUI E2E 与像素核查全为未验收。下一位接手者应当**优先把业务动作、角色/来源/幂等/恢复和实际运行做完整，再补农业指标，最后做全面高保真对照、Mac 安装与正式交付**。

本文是截至上述核对基线的**开发交接快照**。后续以 `main` 最新源码、交付台账、页面服务映射和同 SHA 的 CI/实机证据更新状态。
