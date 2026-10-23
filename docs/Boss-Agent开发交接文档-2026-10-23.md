# Boss-Agent 开发交接文档

> **文档版本**：HOVER-20261023-v1.0  
> **核对时间**：2026-10-23（北京时间）  
> **仓库**：https://github.com/LIUgongxi2046/Boss-Agent  
> **交接基线**：`main` = `a83e6272e41354f48213206d96dd5a40f5c04401`（编写前核验）  
> **状态声明**：**开发中，不是最终 PRD 交付，不得作为正式生产验收证明。**  
> **开发优先级**：先完成真实功能与 E01—E06 异常闭环，再补足农业专题模拟明细；全程保持 Desktop v6 高保真视觉，不降级设计。

## 0. 接手人首先阅读

这是一个**单老板 Agent 桌面应用**，不是面向各部门的多 Agent 平台。用户已经确定产品形态、开源技术底座、PRD 和 v6 UI。继续工作需要**直接在已有开源工程增量开发、测试和验收**，不能重做风格、重写基础 Agent，也不能把静态页面、假数据或 CI 编译成功视作完整软件。

**本次实际台账和证据**：

| 指标 | 仓库核验结果 | 正确解释 |
|---|---|---|
| 项目计划 | 27 个工单 T00—T26：**4 ACCEPTED、5 IN_PROGRESS、18 TODO** | T00、T01、T02、T04 已验收；T03、T11、T17、T18、T19 开发中。其余仍 TODO |
| 72 页实现映射 | **70 页部分代码接入，2 页设计占位/上游登录承接** | 70 不是已完成页面数；N01、D08 为身份登录/会话过期入口 |
| 页面功能端到端验收 | **0/72** 取得 `actual_e2e_verified=true` | CI 所测试的 SQLite 协议不等于真实桌面端到端 |
| 页面像素级验收 | **0/72** 取得 `visual_pixel_verified=true` | 源视觉尺寸和截图检查脚本存在，尚无目标 Mac 的逐页验收结果 |
| 设计状态 | 72 页、561 个明确设计状态索引 | F/A/V 51 页有独立状态索引，N/D 21 页继承通用状态 |
| 最近一次完整成功 CI | [Actions 39881014652](https://github.com/LIUgongxi2046/Boss-Agent/actions/runs/39881014652) | 对应 `59a841d2...`：**300 项 Python 测试通过，React/TypeScript 生产构建通过** |
| 最新 main | `a83e6272...` | 比上述成功 CI **仅多一个 README、项目台账、开发索引文档提交**；这不代表最新 HEAD 又跑过独立 CI |
| 正式安装/真实 API/系统能力验收 | 未形成完整通过记录 | 不得声称 macOS Intel 正式安装包、真实 DeepSeek 完整流程、麦克风/通知权限和休眠恢复已通过 |

**资料冲突的处理**：`README.md` 前半部分仍保留早期“13 页接入、59 页待开发”表述，`docs/development/T16.md` 等历史文档也有旧测试数量。遇到冲突，**以最新 `delivery-ledger.json`、`specs/page-service-map.json`、`main` 实际代码及对应 commit 的 Actions 结果为准**；不要复制历史文字当最新状态。

## 1. 固定产品边界和决策

### 1.1 用户确认的约束

1. 产品主体只有**一个老板 BOSS**；**MAINTAINER** 只做技术维护、获准模拟数据和场景管理，不能阅读老板私人正文或代老板作业务决定。其他员工/部门是模拟联系人、资料作者或交办对象，**不创建部门 Agent 或部门登录账号**。
2. 产品必须是**电脑桌面应用**，当前目标环境为 **Intel x86_64 Mac / macOS 13.7.8**；老板侧和技术维护侧都要可在桌面窗口使用。
3. 复用 `HKUDS/nanobot` 的 Runtime、原生聊天 WebUI、设置与 Skills 能力；在其上加 Boss-Agent 业务层，而非重新开发基础框架。
4. 模型采用 **DeepSeek**，原固定配置为 `deepseek-flash` / Chat Completions / thinking disabled。未经核实不得自动切换模型或换成其他供应商。模型连通性与真实会话要在目标设备测试。
5. 视觉以 **`Boss-Agent-Desktop-Complete-v6/`** 为冻结基准：既定 Logo、蓝绿白配色（`#005BAC`、`#5CA63B`）、大鹏场景素材与动画、桌面布局、全部 72 页及适用状态，不接受“功能完成但 UI 降级”。
6. 用户最近多次明确：**优先把功能开发完整，再补数据**。农业专题目前缺失的真实指标保持未知，不要填造数字。
7. 用户曾明确要求**不用 Codex 云环境**；目标电脑实际执行和演示必须在**本机**。GitHub Actions 可以提供源码/CI 证据，但不能充当目标 Mac 实机运行证明。
8. 对话与正式资料均**不能泄露 API Key、Token、私人日历、真实消息内容**；不能将本机配置或密钥提交 GitHub。

### 1.2 规范优先级和源文件

| 顺序 | 规范 | 位置 | 用途 |
|---|---|---|---|
| 1 | 产品和 BDD 验收 | [`docs/PRD.md`](../docs/PRD.md) | PRD V1.2、FR-01—FR-32、管理能力、E01—E06、AC-nn-S/E |
| 2 | 用户历史确认 | [`docs/项目决策记录.md`](../docs/项目决策记录.md) | D11 单老板、D16 开源复用、D17 桌面、D20 架构固定、D21 恢复开发授权 |
| 3 | 冻结设计 | [`Boss-Agent-Desktop-Complete-v6/`](../Boss-Agent-Desktop-Complete-v6/index.html) | 72 页原图/HTML、561 状态、Logo/大鹏素材；设计稿不是运行界面 |
| 4 | 已验收的架构 | [`docs/HLD.md`](HLD.md)、[`specs/hld-72-page-map.json`](../specs/hld-72-page-map.json) | 单一来源、角色边界、恢复语义、72 页架构映射 |
| 5 | 实际代码覆盖 | [`specs/page-service-map.json`](../specs/page-service-map.json) | 真实组件、路由、动作、测试、部分实现及未验收状态 |
| 6 | 工单和交付证据 | [`delivery-ledger.json`](../delivery-ledger.json)、[`docs/Boss-Agent项目计划.md`](Boss-Agent项目计划.md) | 27 个工单、34 个验收条款、依赖、状态、接下来的任务 |
| 7 | 可复现验证 | [`.github/workflows/boss-agent-desktop.yml`](../.github/workflows/boss-agent-desktop.yml) | 合成 SQLite 测试、密钥检查、固定 nanobot React 编译 |

冻结架构源含原版逻辑 route；业务组件和真实 API 的**实现事实**必须再核查 `page-service-map.json` 与源代码。不要把 HLD 中“应实现的接口”直接写成“已在运行”。

## 2. 技术结构和主要代码归属

### 2.1 固定基础

| 层 | 已锁定 | 备注 |
|---|---|---|
| Runtime | nanobot 0.3.5，固定上游 commit `1bb712d3488915ca4ed9ccc1a93067ff722f5ab9` | 不改上游仓库；工作目录中确定性叠加 |
| 桌面宿主 | Electron 45.0.0，目标 darwin-x64 | 当前属于开发态宿主，**未完成分发版签名/公证** |
| 前端 | 上游 nanobot WebUI + React/TypeScript/Vite + Desktop v6 增量组件 | 原生会话和已认证客户端继续复用 |
| 服务端 | Python 3.12、aiohttp、`RoleChannel`、`BossCommandAPI`、`BossPageAPI` | 老板/维护角色取自已认证服务端，不取自 UI 参数 |
| 数据与检索 | SQLite、FTS5、`ControlStore/Store` | 当前 `ui-check` 为获准的模拟业务域，**不是真实企业 ERP** |
| 模型 | DeepSeek `deepseek-flash` | API 需在目标 Mac 验证，当前开发默认不启用转写 |
| 依赖管理 | `uv.lock`、Node/npm lockfile | 切勿未经评估批量升级上游、Electron 或模型 SDK |

### 2.2 调用链与单一责任

`Electron 本机宿主 → nanobot 原生 WebUI + BossDesktop.tsx → RoleChannel 已认证 HTTP / WebSocket → BossPageAPI（读取） / BossCommandAPI（写入） → SQLite ControlStore/Store`。

**业务写入的安全路径**：UI 不能提交 `owner_id`、`namespace` 或授权结果；服务端用 BOSS/MAINTAINER 角色白名单、当前来源及版本、`BEGIN IMMEDIATE` 事务、授权对象、`client_request_id` 幂等、最小审计保障状态一致。网络回执不确定时调用 `GET /api/boss/ui/operation-status` 查询原请求；未找到不能直接断定未执行，也不能新建请求 ID 盲目重发。

**重要区分**：`DRAFT`（未发）、`SENT_SIMULATED`（本机模拟发件）、`NOT_VERIFIED`（未确认送达）、`RECEIVED_SIMULATED`（注入模拟回复）、`IN_PROGRESS`、`RESULT_SUBMITTED`、`COMPLETED_CONFIRMED`（老板确认）不得混成“任务完成”。

### 2.3 关键目录速查

- `app/webui/BossDesktop.tsx`、`app/webui/boss-v6.css`：统一桌面 Shell、导航、页面布局、Logo/大鹏与角色入口。
- `app/webui/BossMeetingBrief.tsx`：F04 会前准备、快照、失效来源、F08 缺口资料请求草稿。
- `app/webui/BossMeetingApproval.tsx`、`BossMinutesAssignmentActions.tsx`：F05 纪要确认、逐项建任务；F07 审批、A03 模拟申请。
- `app/webui/BossAssignmentFlow.tsx`、`BossTaskCenter.tsx`、`BossPersonalCommitments.tsx`：F06/N05 交办、进展、延期、完成、催办、本人的承诺。
- `app/webui/BossCommunicationCalendar.tsx`：F08 消息草稿/模拟发送及 F12 私人日程/busy 分享。
- `app/webui/BossResearchView.tsx`、`BossSectorView.tsx`：F09 专题研究及农业专题覆盖页面；农业专题指标大多还没有足够明细。
- `app/webui/MaintainerPromptVersion.tsx`、`MaintainerKnowledgeEditor.tsx`、`MaintainerScheduler.tsx`：A05 Prompt、A07 Knowledge Base、A13 技术调度。
- `app/webui/BossVoiceAssignment.tsx`：F27 麦克风、录音、转写后的本人核对流程；真实转写默认关闭。
- `validation/business.py`、`controls.py`：固定模拟数据、域状态、指标查询、事件调度及存储基础。
- `validation/role_channel.py`：WebUI 网关角色认证、HTTP/WS 权限检查。
- `validation/boss_command_api.py`：受权限保护的业务 Mutation、CAS、授权、幂等与审计。
- `validation/boss_page_api.py`、`boss_workspace_api.py`、`boss_recovery_api.py`：按角色获取页面、工作区、原请求回执与失效状态。
- `validation/boss_meeting_brief.py`、`boss_meeting_approval.py`、`boss_message_calendar.py`、`boss_research.py`、`boss_prompt_config.py`：主要业务实现。
- `scripts/prepare_boss_webui.py`：下载/核对固定上游版本、复制 v6 Overlay 和素材、构建。
- `scripts/run_boss_local.sh`：目标电脑的开发态启动入口；`scripts/visual_qa.cjs`、`visual_diff.py`：浏览器窗口截图和差异辅助检查。
- `app/tests/`：单元、SQLite 集成、角色/幂等/协议及前端静态契约测试；`docs/development/`：每批功能的历史说明。

## 3. 当前已实现到什么程度

**以下“已开发”均指源代码或模拟业务域有对应处理，不代表完成目标电脑端到端或真实企业业务系统集成。**

| 业务范围 | 代码已经覆盖的核心功能 | 关键未完成 |
|---|---|---|
| F01—F03 | 工作台、经营提醒、经营指标与实际模拟来源查询的部分交互 | 全量真实场景、问法、通知和长期使用 |
| F04 | 有来源的会前材料准备、版本快照、参会人/承诺/指标检查、失效 `NEEDS_REVIEW`，可生成 F08 草稿 | 真实会议日历、多会议、外部资料索取/回执 |
| F05 → F06 | 纪要分意见/建议/决定/交办草稿；本人确认后逐条建独立 OPEN 任务，保存纪要版本/原文关联，F06 再授权模拟发送 | 真正外部发送、全真实联系人及全量端到端 |
| F06 / N05 | 任务创建/发送、署名进展与延期申请、结果提交、本人批准延期/取消/确认完成、独立催办、历史回读 | 真实催办送达、系统任务生命周期实机验证 |
| F07 / A03 | 模拟审批申请/附件、金额和版本校验、老板同意/拒绝/要求补件、补件升版与旧授权失效 | 真实业务申请流、支付及专业结果执行（本范围不可伪造） |
| F08 / A04 | 草稿保存、唯一联系人、来源附件版本、模拟发送、回复注入、任务进展联动、原请求结果重查 | 外部消息通道、实际送达/收件人认证 |
| F09 | 已授权资料的版本化研究、来源截取与定位、撤销/改版后失效、缺口请求转 F08 草稿 | 实际语义检索、公开数据摄取/时效、模型研究质量评估 |
| F12 / F13 | 私人日程编辑、会议冲突提示、busy-only 范围分享/撤销；老板个人记忆确认/停止采用 | 真实外部日历共享、多日程、物理安全擦除验收 |
| F14—F23 / V19 | 农业专题页面的设计字段、筛选与“有/无可验证来源”状态 | **主要指标没有完整已批准明细，不可生成真实 KPI 和虚构图表** |
| F24/F30、A15 | 真实模型响应元信息和 Token 观察入口；未观察到时明确未知 | Mac 上 DeepSeek 会话全链路、费用覆盖与模型质量证明 |
| A05 | Prompt 版本草稿、静态校验、启停、运行上下文读取次数 | 真实模型采用效果和提示词质量验收 |
| A07 | 模拟知识源 CAS/版本与 SQLite FTS 维护的一部分 | 全部真实知识索引、权限传播、多库更新与维护验收 |
| A13 / F06 | 调度草稿/规则校验/启停，手动模拟触发和独立催办 | Mac 休眠恢复、通知权限、外部投递、真正可持续调度证明 |
| F27 | 本地录音、权限请求、原生转写协议、人工核对 | **transcription 默认 disabled，真实 STT 服务和 Mac 麦克风未完成联调** |

N01 / D08 原生认证入口没有作为独立 v6 业务页面完整验收。70 页“部分接入”包含**只读技术元信息、能力承接、业务状态展示、缺口提示**，不得对外称为“70 页都完整开发”。

## 4. 运行与验证指南（在目标 Mac 执行）

### 4.1 环境

以 `docs/选型环境.md` 为准：macOS Intel、Python 3.12、Node.js 24、uv、Git、本机网络、合法 DeepSeek Key。首个动作是核查 `git status` 与当前 HEAD，不要使用未经审查的依赖升级来修复上游问题。

### 4.2 首次构建及启动

在已克隆的 Boss-Agent 仓库根目录执行：

```bash
git switch main
git pull --ff-only
git rev-parse HEAD

python3 scripts/prepare_boss_webui.py --build
cd validation && uv sync --locked && cd ..
npm --prefix validation/desktop ci

# 先把用户本人已有的 boss agent.md 放于本机项目根目录，
# 不在终端粘贴真实 key，也不提交此文件。
python3 scripts/configure_local_deepseek.py

bash scripts/run_boss_local.sh
```

`scripts/run_boss_local.sh` 将开发环境设置为 `BOSS_PRODUCT_UI=1`，由本机 Electron 运行；如果失败应检查错误和缺少的前置依赖，**不能仅凭构建通过宣称已安装软件**。认证凭据在本机 `validation/.work/application/access.json`，用于分别以 BOSS、MAINTAINER 测试。禁止复制到仓库或交接文档。

### 4.3 DeepSeek/Agent/视觉的本机验证

```bash
# 真实 DeepSeek 最小调用，可能产生少量费用
validation/.venv/bin/python scripts/check_local_deepseek.py

# 启动研发程序后的只读 Agent/经营工具核对
validation/.venv/bin/python scripts/check_local_boss_agent.py

# 目标 Mac 上的真实截图和几何尺寸检查
cd validation/desktop && npx playwright install chromium && cd ../..
node scripts/visual_qa.cjs --role BOSS --pages F04,F05,F06,F07,F08,F09,F12
node scripts/visual_qa.cjs --role MAINTAINER --pages A03,A04,A05,A07,A13
python3 scripts/visual_diff.py --role boss
```

视觉检查应补测原始 72 页和其对应 561 状态的适用集合、至少 1440×1024 / 1280×800 / 1024×768、字体、布局、交互、滚动、动画、键盘焦点和 200% 缩放。上述命令的存在**不等于已实测**，必须保存实际截图、失败报告与版本信息。

### 4.4 自动化检查

`.github/workflows/boss-agent-desktop.yml` 已进行 Python 域契约/密钥扫描和固定上游 React 编译。最近成功记录为 [CI 39881014652](https://github.com/LIUgongxi2046/Boss-Agent/actions/runs/39881014652)：**300 passed，React 构建成功**。

本地运行测试之前先使用项目锁定环境；不要将测试使用的模拟状态写成真实模型验收。CI 默认同分支新提交会取消旧 run：看到 `cancelled` 要核对是否由更新提交接替，不要误判为测试通过。

## 5. 下一位开发者的任务清单（先功能，再数据）

### P0 — 先固定契约并消除“代码能跑、业务却断”的问题

- 核对 `docs/PRD.md` 与 `docs/Boss-Agent项目计划.md`，补全/验收 T05 数据字典、T06 OpenAPI/事件与权限错误契约、T07 Agent LLD、T08 真实页面/接口映射、T09 可执行验收清单、T10 实施顺序。现有实现不能替代这些工单验收。
- 在模拟 `ui-check` 的真实 SQLite 中，按 F04→F05→F06→F08→F09 逐项执行完整流程，并核查页面互访后**相同的任务 ID、纪要条目、来源版本、消息 ID 和授权 ID**。参考 `app/tests/test_boss_fr04_09_full_flow.py`；它当前是**协议集成测试**，尚非目标 Mac GUI E2E。
- 对所有业务写入补足 E01—E06：断网续接与回执查询、并发 CAS、维护端越权、重复点击及重启、模型/检索/资料不可用、部分下游写入后 UI 恢复。写入和消息投递必须有独立状态；失效源不能通过历史缓存泄漏正文。
- 检查 UI 高保真原设计中的真正操作、状态、键盘访问和必要确认是否逐项有对应后端操作；不能用“组件存在”替代“功能完整”。

### P1 — 真正的 Runtime/技术管理/消息与提醒

- 完成 T11—T20 尚未通过的业务语义及正式验收，特别是 A05 Prompt 激活/运行采用、A07 KB 更新与撤销传播、A13 调度/催办恢复、F06/消息任务状态、F27 转写和 DeepSeek 会话。**Prompt 上下文被载入不证明 DeepSeek 已成功应用该 Prompt。**
- 加入对真实模型调用成功/失败、工具输入输出的安全验证、费用与日志覆盖的受限回执；不写入密钥或模型内部推理。
- 若 PRD 要求真实消息或外部日历能力，必须有**当前获准的 Provider 和实际回执**，不能把 `SENT_SIMULATED`、`NOT_VERIFIED` 或本地 busy 分享当成真实送达。

### P2 — 功能验证后再补全农业业务数据

- 按 T21—T23 和 FR-14—FR-23 补充可追溯模拟明细与规则（原料/饲料、水产/苗种、动保、生猪、禽类反刍、公司养殖、食品、海外、研发），逐模块明确单位、期间、法人/区域、来源、版本、计算字段、测试样本及错误阈值。
- 先经数据口径核查，再展示 KPI 和趋势图；不得使用 `finance-note` 外销资料推算未经支持的其他农业专题指标。页面缺数据应保留“待查询”和来源缺口状态。

### P3 — 正式验收和交付

- T24：在目标 Intel Mac 完成真正的 Electron + DeepSeek + 业务流 + 权限 + E01—E06 + 72 页/561 状态测试，留运行、截图、响应和失败修复证据；检查 Token 费用和技术/老板隔离。
- T25：验证安装、首次配置、重启/断网/休眠恢复、退出、日志、数据迁移、设备权限、文件依赖、应用签名与公证/分发所需条件。当前不是正式可交付安装包。
- T26：审计最终 PRD/设计覆盖、测试证据、许可/第三方依赖、文档与维护交接；只有所有适用 AC 通过，才从 `IN_PROGRESS`/`TODO` 改为 `ACCEPTED`。

**推荐实际推进顺序**：先收敛 T05—T10 契约和核心 F04—F09 业务缺口 → 技术后台实际采用、调度和异常恢复 → 真实 Mac/模型联调 → 农业数据与专题指标 → 全页面视觉和系统验收 → 安装包/正式交接。不允许只按页面数量或 CI 测试数宣布“完工”。

## 6. 必须保留的安全与合规边界

1. **不要提交 `boss agent.md`、`validation/connection.json`、`validation/.work/`、`.work/`、BOSS/MAINTAINER Token、真实私人材料。** 本机文件与 Git 忽略规则由 `scripts/configure_local_deepseek.py`、`scripts/check_git_secrets.py` 管理。既然密钥曾通过会话附件提供，建议后续由本人轮换，不能硬编码进仓库或日志。
2. 维护者可以操作获准的模拟数据、Prompt、知识库和调度，但**不能代老板发送、审批、确认完成、读取私人日历或个人记忆正文**。维护端技术索引只显示必要 ID/版本/状态。
3. **资料与版本是有条件的信任边界**：来源撤销、换版本或权限变化后，历史引用可以留下审计元数据，当前页面不能继续展示失效原文或据此授权新动作。
4. **区分模拟、实际、本机和生产**：SQLite `SENT_SIMULATED`、静态校验 `VALIDATED_STATIC_ONLY`、上下文调用 `RUNTIME_CONTEXT_PROVIDER_INVOKED`、本地模拟 `DELIVERED`，均不能当成真实外部投递或完整模型质量证明。
5. 密钥及回执只通过受限本地服务端读取；响应和审计按最小字段返回，失败不能把原请求/对话/私人材料输出到维护 UI。
6. 不增设未经要求的部门 Agent；不引入 Dify/Coze 取代已确认的开源底座；不为了视觉或进度报表填充无来源 KPI。

## 7. 每轮开发结束的交付格式

接手后每一轮提交必须记录下列信息，并同步 `delivery-ledger.json`、`specs/page-service-map.json` 与 `docs/development/`：

| 交付项 | 实际提供的证据 |
|---|---|
| 需求和页面 | FR/AC、页面 ID、对应原始 v6 图和状态 ID |
| 源码 | 具体新增/修改文件、可复现的 commit SHA，`main` push 状态 |
| 业务行为 | 请求/身份/版本/来源/授权/幂等/实际数据库写入或只读回执 |
| 回归 | 用例数、失败/修复明细、CI URL、实际对应提交 SHA |
| Mac 测试 | 实际设备、运行命令、授权窗口、运行日志、真实 API 响应、真实截屏 |
| 高保真 | 当前真实 UI 截图、原始 v6 参考、差异、页面逐项结果、仍未修复的差距 |
| 不通过项目 | 当前未完成事项、外部依赖、阻塞原因与下一步责任 |
| 台账 | 只有证据达到 AC 才设置 PASS/ACCEPTED；否则保持部分实现状态 |

## 8. 交接结论

截至本文核验时，这个仓库已经有规模较大的 **nanobot + Electron + React + SQLite 模拟业务软件开发基础**，存在真实的角色边界、持久化事务、版本与幂等、多个老板及维护页面、较多自动化检查。

但**“70/72 页部分接入”绝不代表“接近完整交付”**：仍有 23 个工单没有达到 ACCEPTED（5 在建、18 待办），正式端到端和像素级验收为 0/72。Mac Intel 上的真实 DeepSeek/语音、业务异常与正式安装包没有满足整体验收的证据。

**交接给下一位开发者的核心指令**：继续复用已经固定的源码、PRD、HLD 和 v6 高保真设计，**先把功能与异常完整跑通、再补农业数据、最后逐页视觉和实机验收**。不得把模拟成功、源代码存在、静态 UI 或 GitHub CI 成功包装成产品已交付。

---

### 可直接打开的关键资料

- [Boss-Agent 仓库](https://github.com/LIUgongxi2046/Boss-Agent)
- [PRD](PRD.md)
- [项目计划及 T00—T26](Boss-Agent项目计划.md)
- [HLD](HLD.md)
- [项目决策](项目决策记录.md)
- [原始 Desktop v6 设计](../Boss-Agent-Desktop-Complete-v6/index.html)
- [72 页实际代码覆盖](../specs/page-service-map.json)
- [项目交付台账](../delivery-ledger.json)
- [开发记录索引](development/index.md)
- [最新成功 CI](https://github.com/LIUgongxi2046/Boss-Agent/actions/runs/39881014652)
