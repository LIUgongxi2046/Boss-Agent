# Boss-Agent 文档索引

每次接手完整读取 [开发接手与执行规范](开发接手与执行规范.md)。当前执行状态唯一来自 [feature-delivery.json](../specs/feature-delivery.json)，队列来自 [menu-plan.json](../specs/menu-plan.json)；索引中的日期和阶段状态仅代表对应文档核查范围。

## 当前实现与使用文档

适用源码为 `9cd9888490521242def326f475c93823a68ec95b`及当前未提交修改，核查日期为2026-10-28。当前活动工单通过唯一正式状态读取；本次文档更新保留全部完整产品需求与未完成验收。

| doc_id | 受众与关键词 | 文件与来源 | 文档有效性 | last_verified |
|---|---|---|---|---|
| DOC-INTEGRATION-CURRENT | 开发者；认证、HTTP、WebSocket、经营范围、会话绑定、错误与恢复 | [集成指南](开发者集成指南.md)、[经营接口](../specs/product-business-overview.openapi.yaml)、[账号接口](../specs/product-auth.openapi.yaml) | CURRENT；代码与Schema核查 | 2026-10-28 |
| DOC-DATA-CURRENT | 开发者；SQLite、FTS5、来源、经营绑定与公开基准 | [当前数据字典](当前数据字典.md)、`business.Store`、`BusinessOverviewEntry` | CURRENT；物理定义及相关实体 | 2026-10-28 |
| DOC-RUNTIME-ENV | 开发与维护；依赖、启动矩阵、目录、端口、制品、配置及影响 | [运行环境](运行环境.md)、当前启动与准备脚本 | CURRENT；源码及本机文件核查 | 2026-10-28 |
| DOC-OPS-CURRENT | 老板与维护；连续操作、Prompt、SOP、故障与原编号恢复 | [操作手册](操作手册.md)、当前界面及领域入口 | CURRENT；使用条件与限制 | 2026-10-28 |
| DOC-RELEASE-CURRENT | 产品与维护；候选行为、证据范围、兼容与未完成项 | [发布说明](发布说明.md)、[仿真主记录](development/SIMULATION-20261028.md) | CURRENT；本机研发候选 | 2026-10-28 |
| DOC-AGENT-SIX-COMPONENTS | 产品与开发；业务场景、六类Agent组件及实际采用 | [Agent说明](Agent六要素设计与实现说明.md)、文内源码与验证记录 | 按原文核查范围使用 | 2026-10-28 |
| DOC-SYNC-20261028 | 接手者；文档范围、来源版本、检查、依赖与完整剩余项 | [文档任务主记录](development/DOC-SYNC-20261028.md) | CURRENT；仅文档任务 | 2026-10-28 |

以上文档由当前主执行者维护；关联业务任务为 `V7-FRONTEND`、`V7-BACKEND`、`USER-REVIEW-20261027`、`SIMULATION-20261028`。详细任务通过[开发索引](development/index.md)检索。

## 设计基线与原任务资料

下表按原核查日期检索设计和任务。各项验收状态具有原版本范围，当前代码及运行方式采用前述2026-10-28文档；未完整复核的设计章节保持 NEEDS_REVIEW，不据旧表中的“当前”表述切换任务。

| doc_id | 内容与关键词 | 当前文件 | 维护责任 | 状态 | last_verified |
|---|---|---|---|---|---|
| DOC-HANDOVER | 每次必读、依据关系、工程入口、开源复用、接手检查与完整交付 | [开发接手与执行规范](开发接手与执行规范.md) | 当前接手负责人 | CURRENT；仅规范与来源核查 | 2026-10-28 |
| DOC-REQ | 电脑桌面应用、老板秘书、农业经营、模拟服务、模型与验收 | [需求输入](Boss-Agent需求输入.md) | S002 | CURRENT | 2026-10-22 |
| DOC-PLAN | S001—S012、老板范围、R01—R32、依赖、工单；第 8 节桌面任务与验收，第 11—12 节战略设计与 A00 审查 | [项目计划](Boss-Agent项目计划.md) | S000/S007；S001 维护战略章节 | CURRENT | 2026-10-22 |
| DOC-DEC | 授权、候选、模型、预算、语音、资源及 D17 桌面产品决定 | [决策记录](项目决策记录.md) | S000 | CURRENT | 2026-10-22 |
| DOC-LEDGER | 承诺、验收、任务状态与全部未完成项 | [delivery-ledger.json](../delivery-ledger.json) | S000/S007 | CURRENT | 2026-10-22 |
| DOC-ENV | 需求版本、目录状态与计划检查范围 | [计划环境记录](计划环境记录.md) | S000 | CURRENT | 2026-10-22 |
| DOC-VALUE | G01—G04、H01—H37、M01—M17、协议、未知阈值与桌面资源条件 | [价值验证定义](../specs/value-validation.json) | S001；S009 采集结果 | CURRENT | 2026-10-22 |
| DOC-PRD | 32 项 FR/BR/AC、48 个功能与管理线框、六类 Agent 组件、两端开源复用；第 10.5 节桌面窗口、权限与生命周期 | [PRD](PRD.md) | S002 | IN_REVIEW | 2026-10-22 |
| DOC-PROBE | T02 的 15 步骤、37 断言；DeepSeek、记忆、调度、权限、两端复用及桌面安装恢复 | [共同验证定义](../specs/selection-probe.json) | S002；T02 执行 | DEFINITION_ONLY | 2026-10-22 |
| DOC-MODEL-LOCAL | DeepSeek 配置引用、真实SDK与公共应用证据、运行元信息及当前验证范围 | [T16开发记录](development/T16.md)、[公共集成记录](development/T11.md)、[本机配置脚本](../scripts/configure_local_deepseek.py) | T11/T16/T18/T19 | PARTIAL_EVIDENCE；完整A16未验收 | 2026-10-23 |
| DOC-DEV-FIRST | 固定开源 v0.3.5、Desktop v6 React 首批实现、可复现构建、权限测试、剩余阻塞 | [首批开发记录](development/T11.md)、[运行脚本](../scripts/run_boss_local.sh) | S008 / T11，后续 T18 接收 | IN_PROGRESS（不等于 T11/T18 验收通过） | 2026-10-22 |
| DOC-PAGE-SVC | 72 页真实代码绑定/未实现区分、F06/A04事务动作、视觉像素检查入口 | [当前页面服务映射](../specs/page-service-map.json)、[T18开发记录](development/T18.md)、[T19开发记录](development/T19.md) | T08/T18/T19 | DRAFT_PARTIAL_CODE（非产品验收） | 2026-10-22 |
| DOC-DEV-MINUTES-APPROVAL | FR05纪要分类/确认、FR07附件和金额版本审批、A03模拟申请与补件升版、v6原稿几何复核 | [开发与测试记录](development/T18-meeting-approval.md)、[72页实际实现映射](../specs/page-service-map.json) | T08/T18/T19 | PARTIAL_CODE；A18/A19 NOT_RUN | 2026-10-22 |
| DOC-HLD | 固定 nanobot/Electron/DeepSeek 架构、身份与权限、唯一数据来源、生命周期、ADR、NFR 和任务交接 | [HLD](HLD.md) | S004 / T04 | A04 PASS（仅静态架构设计，非产品验收） | 2026-10-22 |
| DOC-HLD-72 | 桌面 v6 72 页逐页实现责任、上游复用锚点、逻辑路由、语义读写、561 状态及验证任务 | [72页实现映射](HLD-72页面实现映射.md)、[结构化映射](../specs/hld-72-page-map.json) | S004 / T04；S005-4 / T08 接收 | A04 PASS（架构映射固定，待 T08 实际绑定） | 2026-10-22 |
| DOC-INTEGRATION | 当前源码、来源规则、会议终态、身份、独立宿主与A15公共查询 | [T11公共集成](development/T11.md)、[运行环境](运行环境.md) | T11 | IN_PROGRESS；正式验收未通过 | 2026-10-23 |
| DOC-ACCOUNT | T27账号密码、会话、身份范围、桌面品牌与公共重启 | [T27主记录](development/T27.md)、[公共接收](development/T11.md)、[本机初始化工具](../scripts/provision_boss_accounts.py) | T27/T11 | IN_PROGRESS；完整A27未验收 | 2026-10-23 |
| DOC-LLD | 数据/API、Runtime记录、Agent与前端字段和责任 | [数据](LLD-data.md)、[后端](LLD-backend.md)、[Agent](LLD-agent.md)、[前端](LLD-frontend.md) | T05—T08 | IN_REVIEW；状态引用台账 | 2026-10-23 |
| DOC-REVIEW | 全部FR/AC、异常、安全及实施接收条件 | [T09评审与验收](development/T09.md)、[T10执行接收](development/T10.md)、[设计评审](设计评审.md) | T09/T10 | IN_PROGRESS | 2026-10-23 |
| DOC-SELECTION | nanobot 0.3.5、Electron 45.0.0、DeepSeek 实际任务、六类入口、AD01—AD16、两端 DOM；D18 选型可行性完成及后续检查责任 | [选型验证](选型验证.md) | S004 | ACCEPTED_FEASIBILITY | 2026-10-22 |
| DOC-SELECTION-ENV | 本机依赖、独立验证程序、服务端配置及运行命令 | [选型环境](选型环境.md)、[验证工程](../validation/README.md) | S004 | CURRENT | 2026-10-22 |
| DOC-UI | 桌面六类老板入口、16 类管理能力、48 个线框映射与系统权限；第 13 节规定最终高保真和素材，等待 T02 完成制作与绑定 | [交互与页面规范](交互与页面规范.md) | S003-1/S003-2；T08 接收 | PARTIAL_HANDOFF | 2026-10-22 |
| DOC-PROMPT | 72 个视图、电脑标准及紧凑窗口、16 个核心视图、统一配色；1266 份文字提示词 | [全页面提示词](全页面图片生成提示词.md)、[桌面提示词包](../deliverables/T03/Boss-Agent-desktop-page-prompts.zip) | S003-1/S003-2 | PROMPT_ONLY | 2026-10-22 |

`CURRENT` 表示已核查文档引用与需求版本。任务及验收状态只读取台账。T00 战略设计与 T01 PRD 作为当前来源；T03 文字交互规范已形成，T08 可读取业务交互、组件职责和样式要求。T02 已按 D18 完成选型可行性，交付两端页面/API 矩阵和真实模型、DOM、业务及桌面证据，T03 可继续绑定，T04/T07/T16 引用同一固定基础。选型验证第 6 节保留后续产品检查的实际状态和责任。T03 必须交付全部高保真页面及适用状态稿、可编辑来源、可操作预览、设计 PDF 和真实素材压缩包；PARTIAL_HANDOFF 表示尚未完成全部交接。检查证据位于 `evidence/T00/`、`evidence/T01/`、`evidence/T02/`、`evidence/T03/`。真实企业效果数值保持未知，T02 实际用量及费用覆盖单独记录。PRD 的 IN_REVIEW 表示尚未登记用户批准，A01 评价设计完整性。HLD、LLD、接口规范、开发记录、测试和运行文档的路径、生产任务及内容要求见项目计划第 9—10 节；相应任务产出后更新本索引。S000 与 S007 共同维护这一份项目计划。

S008 实施每项工单时保存 `docs/development/Txx.md` 与 `docs/development/index.md`，记录输入、实际修改、运行命令、结果和关联资料。跨模块知识按实际产生的内容维护，本索引提供检索入口。

T04 固定的 HLD 与 72 页架构映射可交接 T05—T08：前者固定系统边界和唯一维护来源，后者固定每页到设计源/上游组件/语义操作/角色/任务的追踪。用户新指令 D21 已批准开始代码开发。首批 React 工作台、RoleChannel 真实模拟业务读取、开源构建脚本已入库；T11 为 IN_PROGRESS，T18/T19/T20 完整页面及最终验收未通过。
