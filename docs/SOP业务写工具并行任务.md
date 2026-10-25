# W5 SOP业务写工具并行任务

用户于2026-10-23要求新增一个窗口负责尚未完成的SOP业务写工具，使用独立文件和明确接口；W2继续预算及无进展控制，W3继续公共集成。全部外部依赖使用显式模拟数据，权限与本人确认遵守PRD，界面高保真还原并融合当前开源项目UI。执行模式CONTINUOUS_DELIVERY，使用haonan-s008-coder及相应设计、测试职责；不得增加其他会话。

本工作属于既有T07/T16等任务的并行实施，正式任务仍28项，受监督正式任务仍23项、192个检查点。父任务归属、全部未完成承诺及验收条件保持；W5工作项单独报告，不与父任务、测试用例或正式检查点相加。旧W4继续移出监督，不读取或操作其会话、目录。

## 当前依据与依赖

代码采用W3已接收的8292824de09a2ce6b243325717c0c451f3424702。开始时读取自身目录当前AGENTS.md、docs/PRD.md、HLD.md、LLD-data.md、LLD-backend.md、LLD-agent.md、LLD-frontend.md、项目决策记录及development/index.md和T07/T14/T16/T18/T19主记录。当前监督规划以原始项目docs/Boss-Agent项目计划.md第13.19节和本任务文件为准。

读取specs/agent-assets.json的sop_backend_bindings、tool_policy及十三份agent/skills/boss-sop*/SKILL.md，核查正式OpenAPI、business-tools.schema.json、page-service-map.json、acceptance-cases.json和真实领域接口。SOP03现有读取路径保留。先按全部十二组建立操作与权限映射，区分已经存在、可由Agent执行、仅本人可确认及必要依赖尚未满足的操作，不能按缺少工具名称直接推断业务缺失。

Data与Backend：当前已有领域服务及接口的操作可独立推进，复用真实SQLite、当前来源、CAS、幂等与回执。缺少必要领域语义时，仅暂停对应操作，给W1/W3提供准确的输入、结果和拒绝条件，继续其他已满足依赖的工具。禁止另建业务数据库模型或重写领域状态机。

Agent：使用当前固定nanobot Tool/Registry与现有可信身份、执行范围和授权机制。W5提供专用适配模块及显式注册清单，公共注册、配置准入及最终运行由W3接收。Frontend：优先沿用现有页面及真实Client/Provider，新增界面仅在必要时使用专用组件；公共Shell连接由W3负责。Integration：独立注册与本地业务行为由W5完成，最终页面、公共Runtime及全部SOP采用由W3完成。

## 专有文件与共享责任

W5仅修改自己的独立目录中以下专有路径：

- validation/sop_write_tools/：新增适配模块、显式注册工厂及必要内部支持。
- specs/sop-write-tools.json及specs/sop-write-tools.schema.json：专用接口、权限分类、接入清单及Schema。
- app/tests/sop_write_tools/及evidence/T07/sop-write-tools/：独立BDD、Registry、领域、恢复和证据检查。
- docs/development/sop-write-tools/：每组唯一主记录和专有index.md，统一交接HANDOFF.md。
- app/webui/sop-write-tools/：确有必要的专用组件、样式和相应检查，不重复已有页面。

W1维护业务领域与来源、计算、调度模块；W2维护预算/无进展、Runtime记录、现有只读工具、知识及专题模块；W3维护application.py、RoleChannel、Command/Page/Workspace/Shell、现有运行配置、公共CSS、Electron、依赖锁定、构建白名单、agent-assets.json、原生方法正文、全局索引及统一台账。W5不得修改这些共享文件，不编辑任何其他窗口目录，不覆盖或批量复制公共实现。

W5提供新增模块、当前基线、准确提交与文件摘要、注册函数及参数、工具名称、输入输出Schema、身份和确认要求、依赖版本、W3接入位置、W1/W2必要增量及未完成范围。接收者按当前文件逐项集成，保留全部有效修改。执行中的窗口不接收追加消息；交接先写入专有HANDOFF.md及原始监督记录，窗口自然空闲后按监督规则发送一次。

## 全部工作项

下列操作名称沿用当前规范，允许执行范围必须重新依据PRD及可信授权核查；列入映射不代表允许注册为模型工具。已经存在的create_assignment/send_assignment等操作复用，assignmentSourcesConfirm及其他本人专属决定保留本人操作，不新增同名替代工具。

| work_item_id | SOP与用户结果 | 核查操作 | 验收责任 |
|---|---|---|---|
| T07-SOP01-WRITE | 今日事项次序保存后重新读取 | todayReorder | A07/A18，W5独立实现，W3公共采用 |
| T07-SOP02-WRITE | 提醒确认、暂缓及关闭保持当前状态 | boss.reminder.ack/snooze/close | A07/A17，W1领域，W3公共采用 |
| T07-SOP04-WRITE | 会前材料与会议草稿及合法状态转换 | boss.meeting.brief.prepare、meetingDraftSave、meetingConfirm、meetingCancel、meetingHeld | A07/A14/A18 |
| T07-SOP05-WRITE | 纪要保存、本人确认及关联交办 | boss.minutes.save/confirm/assignment.create | A07/A14/A18 |
| T07-SOP06-WRITE | 交办创建发送、催办延期、完成取消与来源复核 | create_assignment、send_assignment、boss.assignment.nudge/extend/complete/cancel、assignmentSourcesConfirm | A07/A14/A17/A18 |
| T07-SOP07-WRITE | 本人审批决定及当前版本重读 | boss.approval.decide | A07/A14/A18 |
| T07-SOP08-WRITE | 消息草稿及有授权的明确发送 | boss.message.draft.save、boss.message.send | A07/A14/A18 |
| T07-SOP09-WRITE | 专题研究准备与当前来源采用 | boss.research.prepare | A07/A15/A18 |
| T07-SOP10-WRITE | 会面材料准备、关联及解除 | boss.people.prepare/attach/detach | A07/A14/A18 |
| T07-SOP11-WRITE | 行程复核、本人确认及取消 | boss.travel.review/confirm/cancel | A07/A14/A18 |
| T07-SOP12-WRITE | 私人日历保存、忙碌分享、撤销及删除 | boss.calendar.save/share/share.revoke/delete | A07/A14/A18 |
| T07-SOP13-WRITE | 本人记忆确认及删除后后续采用 | boss.memory.confirm/delete | A07/A15/A19 |

每组主记录为docs/development/sop-write-tools/SOPxx.md，记录相同work_item_id、FR/BR/AC、实际正式操作ID、角色、依赖状态、输入结果、修改文件、当前行为证据及准确未完成项。专有index.md仅建立唯一检索关系，不维护另一套正式验收台账。

## 权限、确认与异常

每个写操作必须由服务端可信执行上下文确定role、owner、namespace、授权、对象及来源版本；不能信任模型或客户端提交身份。按PRD分别处理草稿准备、本人确认、授权内执行和外部投递，不让模型自行签发持续授权、制造确认或选择无限范围。禁止仅凭confirmed=true等模型输入代替真实本人操作；本人专属操作从模型注册清单排除，并保留现有UI操作和明确拒绝检查。需要领域或公共入口增加确认机制时准确交接，不自行扩大权限。

正常流程通过实际ToolRegistry调用已有领域服务，保存真实SQLite后独立重读、重建服务再读；覆盖来源变化、授权撤销、对象终态、重复编号重查、并发/CAS及写入后取消/超时。结果未知时保留原请求编号，不能重放产生第二份业务结果。错误在发生位置明确报告，不能吞掉失败、自动改为模拟成功或绕过依赖。

外部系统、模型、语音和资料API全部使用项目明确SIMULATED模式及当前Schema；不新增真实外部请求，不等待凭据。模拟范围仅限外部依赖，本地认证、权限、持久化与异常使用实际实现。模拟证据不能登记真实模型质量、真实外部投递或正式验收。

## UI、验证及完成要求

遵守prd要求和高度还原UI设计继续开发，优先把功能做完整，然后再补数据。依据Boss-Agent-Desktop-Complete-v6/design-tokens.json、meta/页面配置.json、meta/v6-状态关联.json及对应页面文字规格，继承蓝绿白、Logo及大鹏素材，保持当前nanobot开源UI的Client/Provider、导航、状态提示、键盘与组件交互一致。不要新增与现有设计脱节的页面，也不能以沿用开源UI为由省略PRD页面行为。禁止主动视觉、截图和图像查看；执行允许的DOM、计算样式、Token映射、视口及行为检查，视觉验收保持未执行。

每组从当前真实输入和BDD开始，完成成功、拒绝、当前版本/授权、持久重读、重启、重复请求及后续使用方的必要验证；全部适用检查通过并记录后继续下一组依赖满足任务。独立Registry通过、构建或提交不能代替公共页面和Runtime采用。交接包含原始结果、相关源码摘要、运行环境、模拟来源、公共接入未运行项及完整剩余范围。

验证使用自身独立端口、业务数据库、构建目录和依赖环境，不操作用户预览，不终止其他窗口进程。禁止读写/tmp，禁止Git恢复代码，文件编辑使用编辑工具。重复检查必须对应新功能、缺陷或相关修改，避免无依据重复全量验证及无关重构。任务持续执行，阶段提交后继续已授权且依赖满足工作；缺少必要输入仅限制对应操作。

## 监督

新增窗口标记W5，与W1/W2/W3一并每30分钟检查。W5按十二个work_item报告开发状态、限定行为、已完成/总检查点及公共接入条件；完整分母核查前写待核实。父任务T07/T16的23项正式汇总和192检查点保持，跨窗口结果只计一次。旧W4不恢复监督。运行中只读；自然空闲后复查仍空闲才发送一次具体续接，并记录防重复标识。
