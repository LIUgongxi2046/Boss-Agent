# V7-BACKEND 后端与页面服务

任务ID：`V7-BACKEND`。负责人：本次主执行者。核查日期：2026-10-26。源码基线：`016c3927533ce03806797bb33ceaad5d28acc95d`，当前修改未提交。

每次开始、恢复或交接必须完整读取`docs/开发接手与执行规范.md`、`specs/feature-delivery.json`、本记录与对应PRD和设计。允许目录为`validation/`、`app/`、`scripts/`、`specs/`、`docs/`及必要工程配置。不得修改已有用户数据库、账号、凭据或运行进程。

依赖：`V7-FRONTEND`当前组件与接口定义、固定nanobot v0.3.5、现有ControlStore、BossPageAPI、BossCommandAPI、RoleChannel、SessionManager、AgentLoop与CronService。前端TypeScript及Vite已通过；前端完整高保真与业务验收继续待执行。

## 服务范围

| 服务 | 实际状态所有者与接入要求 | 状态 |
|---|---|---|
| 本人记忆、授权与历史 | 现有memory、authorization、audit及运行采用记录；本人写入使用当前授权事务 | 记忆确认、到期、删除、原生会话上下文清理、归档个人要求、历史决定、原附件版本、归档会话文字与附件、通知快照已通过限定检查；桌面通知实际返回、派生归档和备份传播待完成 |
| 运行详情、异常与取消 | 正式runtime_run、工具结果、会话与任务记录；取消仅影响未执行动作 | 读取、授权取消请求及Runtime检查点已接入；完整原生运行验证待完成 |
| 技术访问、工具及指标版本 | 草稿、校验、启用、历史及真实消费者；维护不得获得本人业务决定权 | 访问、五项基础业务工具及六项经营指标配置已接入；全部工具、原生维护入口及专题指标覆盖继续开发 |
| 模型连接 | 复用原生Provider配置与模型运行；保存、真实验证、启用、实际采用分别记录 | 版本服务、验证任务、Provider选择和运行采用代码已接入；本地版本及权限检查通过，外部请求验证及正式计价待完成 |
| 数据集、关系与专题 | 统一获准模拟资料、生成与关系校验、独立执行空间、旧结果只读、指标实际计算 | 候选生成、校验、明细、影响清单、载入与重置命令、原生重新执行和历史元信息已接入；限定运行检查通过；认证界面、全部历史正文、完整十四类资料及专题继续开发 |
| 知识资料 | 成熟文件解析库、版本化来源、FTS索引、获准检索与撤销 | TXT、Markdown、DOCX摄取及版本、索引、撤销已通过检查；PDF解析路径已实现，实际文件验证待完成 |
| 调度与评测 | CronService单一执行责任、实际计划版本、全部评测尝试和隔离评分资料 | 调度字段、范围和重启策略已接入；原生事件计时与重启暂停通过检查；评测服务继续开发 |
| 设备与恢复 | 实际服务、宿主、安装和恢复记录，不生成成功状态 | 版本和服务读取、宿主自启动状态接入；安装、备份及目标设备验证待完成 |

读取继续使用认证后的HTTP GET，写入继续通过原生WebSocket requestMutation。新增路径和字段以V7-FRONTEND组件定义为准。服务端核查身份、对象、版本和授权，数据库事务记录幂等回执。未知结果使用原请求查询，禁止自动重发。

## 完成条件

全部新增前端读写均具备正式数据生产者和实际消费者，能够保存、重新读取与核查原请求；鉴权拒绝无越权写入及正文暴露；来源和配置版本可追溯；重置与历史空间隔离；后续Agent使用同一业务状态。集中运行真实领域检查和构建，完成后进入V7-AGENT。视觉与用户验收分别保留。

真实外部请求、自动认证和语音继续采用已有用户限制。全部服务和产品交付保持未完成。

## 当前接收范围

2026-10-26接收全部Desktop v7页面组件与表单，当前统一构建日志为`.work/takeover/conversation-complete-build.log`，TypeScript与Vite通过，源码摘要与编译制品记录一致。该接收用于继续实现服务，72页产品DOM、高保真及完整业务验收保持待完成。

活动任务采用V7-FRONTEND主记录中的33项后端接收要求，逐项保持字段、权限、来源版本和原请求恢复要求。会话知识库选择已连接原生SessionManager、正式来源目录与FTS索引、会话上下文采用及Runtime检查点，限定检查见本记录末节。继续连接会话授权摘要、专题、会议与资料目录、本人业务及维护服务的完整字段和操作。已有服务证据按实际版本和覆盖范围复用，未完成要求不得删除。

## 当前实现与集中检查

本人服务采用`boss_v7_owner.py`及对应记忆、历史和运行模块。技术服务采用`boss_v7_technical.py`、`boss_v7_configuration.py`、`boss_v7_knowledge.py`、`boss_v7_relationships.py`、`boss_v7_audit.py`及`boss_v7_local_system.py`。写入加入现有SQLite事务、幂等回执和审计。技术访问在写入事务内再次检查当前配置；业务本人身份限制继续独立执行。

知识解析直接使用`pypdf==5.9.0`和`python-docx==1.2.0`。原文件、摘要、资料版本及有效期保存在同一执行空间。SQLite FTS5维护原文检索索引，文档写入、修订和撤销通过数据库触发器同步索引；当前检索只返回获准且有效的来源。通用资料读取继续核查原文与索引的对应关系。

调度通过`BossSchedulerRuntime`连接原生CronService。原生系统任务读取正式计划，采用CRON、EVENT或EVENT_OR_TIME；当前计划保存唯一责任组件、IANA时区、表达式、获准任务范围和重启策略。配置保存与CronService实际采用分别显示，未采用的新版本显示CONFIGURATION_PENDING。当前完整退出行为由桌面宿主及其所属服务控制。

2026-10-26集中运行`app/tests/test_v7_backend_services.py`、`test_boss_scheduler_config.py`、`test_boss_knowledge_ingestion.py`、`test_boss_memory_runtime.py`，42项通过，耗时10.50秒。检查使用项目`.work/takeover/pytest-v7-services-final`独立数据库及原生CronService，没有认证现有应用或调用真实外部模型。证据日志为`.work/takeover/backend-services-final.log`。访问事务定向复验2项通过，日志为`.work/takeover/access-transaction.log`。

项目依赖锁文件通过`uv lock --check --offline --project validation`；修改后的Python模块编译检查、桌面宿主JavaScript语法检查及`git diff --check`通过。前端重新准备后，TypeScript与Vite构建通过，Vite耗时18.17秒，日志为`.work/takeover/frontend-build.log`。这些检查只证明对应源码和范围，不代表完整业务、72页还原或目标Mac验收。

## 后续必要工作

继续完成模型连接的实际外部验证、正式计价及完整任务采用验证、专题指标覆盖、模拟资料生成与独立执行空间切换、专题服务及独立评测。接入全部原生维护入口的访问策略，完成全部工具目录、运行详情、取消后状态、历史决定和删除传播。全部服务完成后推进Agent集成与完整用户流程；自动认证、视觉和真实外部模型请求采用现有授权限制。

## 模型连接服务

`boss_v7_models.py`保存连接草稿、历史版本、全部验证尝试与启用引用。维护页面使用同一认证读取及WebSocket写入体系；保存检查对象版本，启用同时检查连接编号、连接版本、内容摘要和公共配置版本。凭据仅使用服务端环境变量引用；验证与启用核查凭据摘要，页面不返回摘要或秘密值。保存草稿保持当前运行方式。

实际验证需要页面明确确认，使用固定nanobot的OpenAICompatProvider及现有RecordedProvider记录请求。当前协议为Chat Completions，Provider选择支持DeepSeek与OpenAI。验证程序调用诊断工具读取服务实际时间，核查后续回答采用该时间，并核查流式文本事件；所有尝试、已观察请求和服务返回用量保存，取消尚未执行的验证及服务停止、重启中断分别记录，禁止自动重发。开发期间没有执行真实外部验证。尚无已核实价格版本，费用保持未知。

`ProductRuntime`将当前连接作为原生Config和ProviderSnapshot的明确配置，`FeatureProvider`仅在已验证且明确启用后采用对应RecordedProvider。原生工具循环继续使用同一业务权限与资料。进行中任务阻止配置切换；运行记录保存连接编号和版本，HTTP观察记录实际用量，外部调用共用整次运行截止时间，失败保持当前模型。进程停止时释放验证任务及Provider连接。上述外部调用与启用路径已经编写，尚无真实外部调用或完整Agent任务的运行证据。

2026-10-26集中检查`test_v7_backend_services.py`、`test_boss_runtime_records.py`和`conversation_agent/test_runtime.py`，34项通过，耗时7.90秒。使用`.work/takeover/pytest-v7-models-final`独立资料，日志`.work/takeover/model-services-final.log`；涵盖模型草稿、版本冲突、幂等回执、权限、未准备Runtime拒绝及既有原生模拟会话，不代表真实模型验证通过。新增Python模块编译检查通过。前端重新准备后，TypeScript与Vite构建通过，Vite耗时15.98秒，日志`.work/takeover/model-frontend-build-final.log`。全部修改继续未提交；完整产品保持开发中。

## 指标配置与实际计算

对应FR-02、FR-03、FR-26和WF-AD10，设计来源为Desktop v7的A10指标与规则页面。`boss_v7_metrics.py`提供当前资料中的销量、收入、成本、毛利、毛利率和单吨毛利配置。名称、公式、维度、单位、显示精度、外销或已结算外销范围、生效时间、刷新间隔与变更说明通过既有维护事务保存，配置保留草稿、复算、启用、历史和实际采用记录。

公式与单位必须符合已注册指标的业务定义，不执行用户表达式。复算读取当前获准明细，按可比范围分组，用`fractions.Fraction`核对Decimal运算，启用时再次核查明细和来源摘要。原始计算值保持Decimal精度，ROUND_HALF_UP仅用于显示。缺少资料、零分母或单位不相容保持未知。维度分组保留明细引用，查询缓存同时绑定配置、实际明细及可用状态，达到刷新间隔或输入改变时重新计算。

`Store.query_metrics`、正式范围查询、会议材料、经营总览及提醒观察采用同一配置。查询保存配置摘要、期间计算和维度依据；旧查询、历史查询及模拟资料读取检查当前配置，配置改变后要求重新查询。会议材料的配置采用发生变化时需要重新核查。提醒观察保存计算版本，来源检查要求当前配置一致，持续条件的计算依据包含配置摘要；CronService监测有效指标配置变化。未来生效版本保留等待状态，达到设备时间后才参与后续计算。

2026-10-26集中检查`test_v7_backend_services.py`、`test_boss_metrics.py`、`test_fc02_bi_queries.py`、`test_boss_meeting_brief.py`、`test_menu_n03_overview.py`与`test_fc04_public_alerts.py`，58项通过，耗时6.64秒。证据为`.work/takeover/metrics-verified.log`，独立资料为`.work/takeover/pytest-v7-metrics-verified`。覆盖六项指标的配置、独立复算、原始数值、维度、缓存、生效时间、旧查询状态、会议材料、经营总览稳定摘要及提醒来源状态。完整专题指标、数据集切换和产品验收继续未完成。

指标配置变化与原生调度、提醒来源的定向复验3项通过，耗时2.58秒，日志`.work/takeover/metric-scheduler.log`。前端重新准备后，TypeScript与Vite构建通过，Vite耗时15.87秒，日志`.work/takeover/metrics-frontend-build-final.log`。Python模块编译及`git diff --check`通过。本轮没有启动或认证现有应用，没有执行外部模型请求。

## 模拟数据集生成与读取

对应FR-25、FR-26与WF-AD03，设计来源为Desktop v7的A03数据集页面及原始提示词。`boss_dataset_generator.py`提供`business-facts-1`生成器和`supply-quality-1`关系配置。参数包括非负安全整数seed、1/4/16组业务实体、连续1至36个月的期间和明确版本。当前期间覆盖所选月份，比较期间采用相同天数；业务时钟采用当前期间结束后第二天。随机经营明细使用Decimal计算收入和成本，汇总直接来源于明细。

供需品质资料采用仓库获准SIMULATED定义，通过现有JSON Schema与`SupplyQualityAPI`保存、检查来源作者、有效时间、引用、归属、库存可用量、配方比例和加工投入产出。生成参数、模板与Schema摘要、原始生成事实和汇总共同形成可复现内容摘要。相同参数及版本复用相同数据集；不同seed产生独立经营事实。生成候选不包含本人记忆、私人安排、确认目标、动作授权或当前执行结果。

`boss_v7_datasets.py`在同一SQLite事务中建立未启用的候选空间和独立资料目录。已有业务空间、会话与本人资料保持原有归属。候选保存实际来源及采用引用，关系检查核对完整性、明细汇总和业务引用；候选内容变化后，读取显示NEEDS_REVIEW，校验和明细采用拒绝继续。维护页面可生成、重读原请求、重新校验、按类别分页读取实际明细，记录生成时间和检查时间；身份、版本与明细范围由服务端检查。

载入和重置通过正式命令接入服务停止、原生重新执行及实际采用记录，历史空间提供元信息和运行记录的独立只读入口。认证后的完整界面操作与本人历史正文读取继续待完成。进程绑定、空本人资料、影响清单、切换范围及限定验证见后文；完整十四类接口资料与专题范围继续保留。

2026-10-26集中检查`test_v7_datasets.py`、`test_v7_backend_services.py`、`test_boss_supply_quality.py`与`test_boss_simulation_api.py`，128项通过，耗时28.11秒。独立资料为`.work/takeover/pytest-v7-datasets-verified`，日志为`.work/takeover/dataset-services-verified.log`。检查覆盖三种规模、闰年期间、复现、seed变化、来源完整性、权限、版本、分页和原有模拟接口及原生工具目录。BusinessTool发布启用Schema的根定义并保留本地引用，原生目录与实际工具读取通过检查。

前端重新准备后，TypeScript与Vite构建通过，Vite耗时15.12秒，日志为`.work/takeover/dataset-frontend-build-final.log`。Python编译与`git diff --check`通过。当前检查没有认证现有应用、修改用户资料、执行真实外部请求或进行视觉检查；全部修改仍未提交，完整产品与72页验收继续未完成。

## 执行空间绑定与重置影响

`boss_execution_scope.py`将服务进程绑定到启动时确定的`BOSS_EXECUTION_NAMESPACE`。领域服务、页面、业务工具、原生运行记录及后台调度采用同一空间；数据集需要正式生成目录、版本和事实摘要。应用启动读取唯一有效空间，必要时以该空间重新执行应用入口，随后创建原生服务。新空间使用独立配置、工作目录、SessionManager目录、Cron文件和诊断目录；身份与账号继续由实例统一管理。

`DatasetWorkspace.stage_execution`从已核查的生成事实建立未启用空间，保存来源和内容摘要。`commit_execution`核查原空间、目标版本、准备资料及在途运行，在同一事务内变更唯一有效空间并记录PENDING_RUNTIME。公共命令通过`ExecutionTransition`调用这些操作；PENDING_RUNTIME不表示原生服务已经采用。HTTP、WebSocket和业务命令入口检查绑定空间及切换请求，切换期间拒绝接收新业务。

生成空间允许没有本人记忆和私人安排。页面、上下文、晨间、会议与行程读取保持空值；本人首次确认记忆或保存私人安排以版本0提交，并产生实际版本1与本人授权。没有生成版本0历史正文、本人确认或日历冲突。原生业务工具发布当前空间的维护配置，运行范围继续由服务端请求绑定。

重置影响检查使用当前SessionManager和正式数据库，返回会话、记忆、任务、本人计划、发件箱、在途运行、技术调度配置及模型验证任务数量。内容摘要绑定业务对象、会话版本、原生目录和Runtime配置。页面重读时重新核查摘要，资料变化显示STALE；维护页面不返回会话正文。没有原生Runtime时，影响检查明确不可用。数据集操作回执存入资料目录的独立幂等范围，认证后的维护身份能够在新空间查询原请求；本人身份不能读取维护回执。

2026-10-26集中检查`test_execution_namespace.py`、`test_v7_datasets.py`、`test_v7_backend_services.py`、`test_boss_memory_runtime.py`、`test_boss_message_calendar.py`、`test_boss_supply_quality.py`与`test_boss_simulation_api.py`，150项通过，耗时38.78秒。日志为`.work/takeover/namespace-final.log`，资料为`.work/takeover/pytest-namespace-final`。独立子进程实际读取十四类接口、处理空本人资料、首次保存记忆及私人安排、读取跨空间原请求，并通过nanobot工具循环查询新数据集和读取依据。原生SessionManager保存会话后，影响数量和变化状态通过检查。十四类接口可读取不代表每类生成资料已经覆盖全部业务要求。

`test_product_bi_runtime.py`、`test_product_morning_runtime.py`、`test_product_assignment.py`、`test_product_reminders.py`和`test_product_fc01.py`的13项原生业务运行检查通过，耗时17.28秒，日志为`.work/takeover/namespace-sdk.log`。这些检查采用真实nanobot运行组件与显式SIMULATED Provider，全部会话使用专用检查目录。前端重新准备后，TypeScript及Vite通过，Vite耗时19.08秒，日志为`.work/takeover/namespace-impact-build.log`。Python编译与`git diff --check`通过。

## 载入、重置与原生重新执行

`boss_execution_transition.py`处理正式载入与重置请求。请求要求本人空间、已生成数据集版本、最新影响摘要和明确确认；重置只采用当前已载入的生成数据集。生成候选必须通过资料关系和内容摘要核查。保存请求时检查原生配置及凭据引用，随后停止新请求接收。已经提交的经营查询、工具结果和本人动作保留原归属。

`ProductRuntime.run_bot`跟踪实际SDK调用任务，`stop_runs`取消并等待这些任务；运行Hook在工具和迭代检查点识别切换请求。应用停止Cron任务、SDK运行和原生AgentLoop，关闭连接及模型验证资源，完成后才允许提交目标空间。普通退出信号不会触发自动重新执行；未完成请求保留中断状态。应用的启动异常记录RUNTIME_START_FAILED，错误继续向调用方报告。

目标空间保留模型连接、运行配置、访问与工具配置和技术Prompt及其版本；采用来源记录在目标manifest中。指标配置采用、本人记忆、私人安排、会话、交办、本人计划和发件箱保持原空间归属，新空间的技术调度暂停。原生配置使用环境变量凭据引用，新空间具有独立目录。应用释放实例锁后通过`restart_execution`重新执行Python入口；入口重新读取有效空间并重新构造全部原生对象。WebSocket监听就绪及原生配置、工作目录和会话目录核查完成后，切换记录成为ADOPTED。

页面展示请求、目标空间、请求时间、实际采用时间与中断信息。原请求回执可以在重新登录后继续查询；重复提交同一请求不会再次切换。历史入口返回原空间的归档时间、原生会话数量、业务对象数量和分页运行记录，明确标记READ_ONLY及`current_evidence_eligible=false`。维护入口没有历史会话正文，本人历史正文范围见后文。

2026-10-26集中运行执行空间、数据集、V7服务、运行记录和五类原生业务检查，65项通过，耗时54.35秒。命令包含`test_execution_transition.py`、`test_execution_namespace.py`、`test_v7_datasets.py`、`test_v7_backend_services.py`、`test_boss_runtime_records.py`、`test_product_bi_runtime.py`、`test_product_morning_runtime.py`、`test_product_assignment.py`、`test_product_reminders.py`和`test_product_fc01.py`。日志为`.work/takeover/transition-verified.log`，独立资料为`.work/takeover/pytest-transition-verified`。

切换检查使用真实nanobot组件、数据库和显式SIMULATED Provider。实际在途查询取消后，载入目标数据集，调用产品共用的`restart_execution`；保持所属PID并重新初始化Python运行，读取原请求、历史空间和新数据集。随后重置当前生成数据集并再次重新执行，核查原始事实一致、新空间隔离和原生经营查询。检查没有使用认证自动化或启动用户应用；完整应用窗口、认证重连及异常退出流程仍需限定验证。

前端重新准备后，TypeScript与Vite构建通过，Vite耗时16.27秒，日志为`.work/takeover/transition-verified-build.log`。Python编译与`git diff --check`通过。当前源码继续未提交，用户运行空间没有切换，完整产品和72页高保真验收继续未完成。

## 本人归档记忆与历史决定

对应FR-13、FR-25、FR-05和FR-07，采用Desktop v7的F13个人记忆、N11历史决定及D09历史通知要求。`boss_owner_history.py`统一限制本人查询范围：当前空间及正式登记READ_ONLY、已停用、属于同一本人且具有有效数据集来源的归档空间。生成候选与未归档空间不进入本人历史查询。

N11读取原授权、原始申请决定意见、确认时纪要版本及附件版本。来源正文使用授权保存的明确版本，版本更新后从正式`document_revision`读取；未记录版本或当前权限不允许时不返回正文。来源撤销、版本更新和当前有效性分别展示，历史版本保持原内容。归档记录具有原空间、归档时间及独立编号，撤销、继续当前事项和原请求恢复入口均不接受归档对象；没有登记的当前对应事项明确保持空值。当前授权页面仍只查询当前空间。

F13历史版本增加归档空间选择与分页展示。归档个人要求保留原数据集、版本和确认时间，明确不参与当前会话与任务采用。删除保留已清空正文的版本记录；截至删除版本的正文、来源说明和引用保持清空，本人随后重新确认的新版本按自身版本展示。D09采用相同空间范围；完整通知正文和历史会话正文继续开发。

2026-10-26集中运行`test_execution_transition.py`、`test_v7_backend_services.py`、`test_boss_meeting_approval.py`及`test_boss_memory_runtime.py`，48项通过，耗时17.66秒。日志为`.work/takeover/owner-history-verified.log`，独立资料为`.work/takeover/pytest-owner-history-verified`。检查通过正式命令保存个人要求、删除、重新确认、模拟申请和本人拒绝决定，再实际载入与重置，经过两次原生重新执行读取历史内容。核查原空间正文、删除版本、撤销附件、更新后的原附件版本、跨空间写入拒绝、维护身份拒绝及读取前后数据库内容一致。

前端重新准备后，TypeScript及Vite构建通过，Vite耗时17.94秒，日志为`.work/takeover/owner-history-build.log`。本轮没有认证现有应用或执行外部模型请求。完整历史会话、通知详情、删除传播、专题和产品验收继续保留，完整产品未交付。

## 归档会话文字与通知快照

对应FR-25、FR-13和FR-29，采用Desktop v7的N02历史会话区域和D09历史通知详情。N02新增归档空间会话入口，按原空间列出原生WebSocket会话，分页读取本人消息与Agent文字回复。读取只接受正式归档目录及归档清单中的会话编号，不接受当前空间、SDK会话或候选空间。原生会话文件通过`jsonlines==4.0.0`只读解析，文件损坏直接报告错误；不调用具有文件修复行为的读取方法。文件名采用nanobot的`JsonlSessionStore.storage_key`，消息展示复用`public_history_message`、`is_hidden_history_message`及`strip_think`。原生Runtime上下文、隐藏消息、工具内容、Provider状态和内部推理不进入历史文字页面。

`boss_notification_snapshot.py`在正式调度写入通知时保存当时事件与关联任务版本。D09读取原通知和通知修订，按保存版本展示事件状态、经营事实、任务内容及来源；旧资料没有保存正文时保持缺少说明。来源更新或撤销状态单独显示。本人历史接口继续拒绝维护身份，维护模拟接口返回原有元信息范围。

桌面通知目标增加`execution_namespace`，宿主以原空间、事件和版本共同记录通知实例。通知点击携带原空间，认证后的读取将归档通知映射到D09及明确记录编号；当前通知仍核查有效状态。D09选择对应记录，无有效记录时隐藏不存在的内容并显示返回说明。N06提供获准历史通知入口。该宿主连接与页面返回代码已编写，尚未在实际Electron窗口执行通知与点击检查。

2026-10-26集中检查`test_execution_transition.py`、`test_fc04_notification_target.py`、`test_boss_scheduler_config.py`、`test_fc04_public_alerts.py`和`test_v7_backend_services.py`，37项通过，耗时18.73秒。日志为`.work/takeover/history-content.log`，独立资料为`.work/takeover/pytest-history-content`。实际原生重新执行后读取32条原生SessionManager保存的本人消息，核查分页、原空间归属、权限拒绝及读取前后数据库和会话文件摘要一致；事件变更后仍读取发送时版本，旧空间通知目标返回D09。

采用实际`OwnerMemoryContext`和nanobot的Runtime上下文附加方法保存消息后，原生重新执行定向检查1项通过，耗时14.86秒，日志为`.work/takeover/history-context.log`。页面返回原本人文字，Runtime附加内容没有进入结果。依赖锁文件离线核查、Python编译、宿主JavaScript语法与`git diff --check`通过。前端重新准备后，TypeScript与Vite构建通过，Vite耗时16.36秒，日志为`.work/takeover/history-content-build.log`。

历史会话附件读取、会话删除传播、认证后的界面流程、实际系统通知及其余专题服务继续开发。本轮没有认证用户实例、执行真实外部模型请求或进行视觉检查，完整产品和72页高保真验收继续未完成。

## 归档会话附件

对应FR-08、FR-25及Desktop v7的N02历史会话要求。正式应用将当前`ConversationAttachments`连接到`ProductRuntime`，执行空间切换保存该实例的获准媒体目录。本人归档读取复用附件记录、原文件名、类型、大小、摘要及原始消息位置；服务端不返回内部相对引用或媒体目录。媒体目录没有归档记录时，只显示已保存元信息并说明无法核查文件。

`ConversationAttachments.read_snapshot`直接读取已解析的原生会话快照，不调用SessionManager的文件修复路径。下载同时核查本人身份、归档空间、原会话和原附件编号；只读取获准目录内文件，核对读取期间文件状态及上传时大小和SHA-256。文件缺少、内容变化或引用无法核查时拒绝下载。N02归档浮层展示附件状态，点击下载后再次核对服务端范围、大小和SHA-256，再交给浏览器保存；没有将原附件加入当前会话或任务。

2026-10-26检查使用实际`WebUIMediaGateway`上传仓库的`specs/morning-coverage.json`，保存原生附件元信息与消息，再进行载入、重置及原生重新执行。原生上传与跨空间附件定向检查2项通过，耗时13.19秒，日志为`.work/takeover/history-attachments-targeted.log`。附件消息位置定向检查1项通过，耗时10.15秒，日志为`.work/takeover/history-attachment-message.log`。核查33条原生消息分页、附件下载字节与原文件一致、原始消息位置、读取前后会话与数据库内容一致、维护身份拒绝、未知附件拒绝，以及检查专用文件变化和缺失后的拒绝读取。相关V7服务与原生会话基础检查42项通过，范围不包含真实外部模型或认证界面。

前端重新准备后，TypeScript及Vite构建通过，Vite耗时18.40秒，日志为`.work/takeover/history-attachments-build.log`。修改模块编译与`git diff --check`通过。实际浏览器保存文件交互、认证界面、桌面通知、会话删除传播及其余产品范围继续保留；没有改变用户运行实例，完整产品未交付。

## 进行中任务的记忆采用

对应FR-13、AC-13-E及Desktop v7的F13个人记忆要求。`RuntimeRecordHook`在开始运行、模型迭代、工具执行、流式回调与最终内容返回时重新核查已采用的记忆编号、版本、有效期限和本人确认授权。已经采用的版本被删除、重新确认、撤销授权或达到有效期限时，通过原生取消流程终止运行，保存`CANCELED`及`OWNER_MEMORY_CONTEXT_CHANGED`。已经完成的工具读取与原采用版本保留可查，不自动重新执行本人请求。

2026-10-26集中运行`conversation_agent/test_native.py`、`test_boss_memory_runtime.py`及`test_boss_runtime_records.py`，47项通过，耗时17.47秒，日志为`.work/takeover/memory-running.log`。检查使用真实nanobot、正式本人命令和获准SIMULATED Provider；实际完成来源读取后分别删除、重新确认、撤销及推进业务时间，核查后续模型步骤没有执行、会话意图同步取消及原工具结果仍有记录。没有新增外部请求或认证用户实例。

这些检查覆盖原生运行检查点。已发送到界面的流式内容、持久会话正文与摘要清理、派生资料和备份恢复仍须完成相应传播机制，不能登记全部删除传播完成。前端源码未因该检查点修改，沿用此前构建证据；完整产品继续开发。

## 原生会话上下文清理

对应FR-13、AC-13-S/E及Desktop v7的F13、A12。`MemorySessionManager`继承固定nanobot的SessionManager，继续使用原生会话身份、缓存、文件锁和持久保存。`OwnerMemoryContext`以采用版本摘要标记Runtime来源。本人要求、确认权限或有效状态变化后，会话读取与保存核查该标记，使用原生`detach_runtime_context`移除旧Runtime附加内容，清理会话摘要、Runtime恢复状态及Provider延续状态，并把后续模型采用范围设置到当前消息之后。受旧记忆影响的历史回复继续供本人查阅，不进入新的模型请求。消息编号、媒体引用和原本人可见文字保持原位置。

应用启动及本人记忆确认、删除、授权撤销和业务时间推进后的传播操作使用相同服务。旧版与当前删除命令共同清空本人记忆正文、历史版本和候选要求，保存传播记录。F13展示会话清理状态、核查数量、核查时间和备份状态，并提供本人再次清理入口；A12只提供对应技术元信息。读取和写入出现内容标记不一致时直接报告错误，传播记录保存FAILED，原生会话不能继续采用该内容。`MemoryAutoCompact`清除对应会话的进程内摘要缓存。

2026-10-26集中检查`conversation_agent/test_native.py`、`test_boss_memory_runtime.py`、`test_boss_runtime_records.py`及`test_v7_backend_services.py`，62项通过，耗时23.23秒，日志`.work/takeover/memory-sessions.log`。真实nanobot处理获准来源后删除记忆，核查清理、原消息保留、重新打开会话、重复清理及下一次实际模型输入。原生执行空间切换、V7服务和公开记忆读取检查17项通过，耗时17.07秒，日志`.work/takeover/memory-propagation.log`；其中通过实际ProductRuntime调用删除传播和再次清理命令。

会话内容异常及旧Session对象重新保存的定向检查2项通过，耗时5.37秒，日志`.work/takeover/memory-cleanup-recovery.log`。内容异常产生FAILED并拒绝会话读取；保存原始有效会话后重新清理恢复正常。旧Session对象再次保存时仍根据当前删除状态清除旧上下文和摘要。该结果只覆盖原生会话保存路径，不表示完整数据库与文件备份恢复已经完成。

前端重新准备后，TypeScript与Vite构建通过，Vite耗时16.56秒，日志`.work/takeover/memory-sessions-build.log`。后台摘要归档产生的独立资料、原始获准资料保留范围、完整备份恢复和认证界面继续待完成。没有启动或认证用户实例，没有执行真实外部模型请求；全部产品与72页高保真验收继续未完成。

## 会话知识资料选择与实际采用

对应FR-08、FR-24及V7-FRONTEND第33项接收要求，采用Desktop v7的N02知识库选择和来源区域。`boss_conversation_sources.py`提供`boss.conversation.sources.list/bind/receipt`，通过现有RoleChannel和PublicConversation接收已认证且已订阅会话的本人请求。目录使用当前空间的正式来源和FTS5全文索引，返回版本、作者、有效状态与不可采用原因。目录摘要覆盖完整资料范围，搜索词变化保持同一目录版本；目录和原请求读取不创建会话或业务记录。

绑定使用SQLite事务核查资料空间、资料集、目录版本、会话选择版本及全部来源。保存当前选择、版本记录和原请求回执，重复编号仅返回原结果；并发提交只允许符合当前版本的请求采用。运行中的会话不能更换选择。新会话通过原生WebUIWorkspaceController保存当前工作空间，已有会话绑定原生创建时间；会话删除后重新创建不能采用旧实例的选择。空列表清除当前显式选择，全部结果保持业务授权和业务修改标记为false。

一般会话、当前交办讨论和经营查询通过原生AgentLoop实际执行`bossEvidenceRead`，保留各自的原始入口范围。晨间会话复用`morningSourceRead`读取明确选择的知识资料；来源选择独立记录，晨间事项与清单范围继续核查。运行保存选择编号、上下文版本、来源版本和摘要，工具结果保存实际读取关系；N02来源投影同时返回已选择关系、实际读取关系及当前版本状态。来源撤销或变化后，后续模型步骤、工具调用和最终内容返回均重新核查并拒绝继续采用。

2026-10-26集中检查使用真实ControlStore、原生SessionManager、Nanobot和显式SIMULATED Provider。一般会话与资料服务47项通过，日志`.work/takeover/conversation-sources.log`，耗时24.93秒；资料选择及原有晨间、任务、经营入口64项通过，日志`.work/takeover/sources-entries.log`，耗时37.28秒。晨间原生检查26项通过，日志`.work/takeover/morning-sources-final.log`，耗时15.16秒。

当前来源投影与目录、回执检查23项通过，日志`.work/takeover/sources-projection.log`，耗时8.21秒；晨间来源投影与事项定向检查3项通过，日志`.work/takeover/morning-sources-projection.log`，耗时7.23秒。当前交办和经营查询实际采用所选资料的检查2项通过，日志`.work/takeover/sources-selected-entry-final.log`，耗时3.97秒。这些检查包含保存重读、原请求只读恢复、并发版本冲突、清除选择、新会话保存、重建会话拒绝旧选择、运行期间变更拒绝及来源撤销后的终止。业务对象与原本人授权保持检查前状态。

最终返回检查使用原生Runtime的实际结束状态：来源在模型生成回答后发生变化时，返回前核查拒绝采用，并记录FAILED及已完成工具结果。资料服务、Runtime记录与本人记忆检查29项通过，耗时7.70秒，日志`.work/takeover/main-final-context.log`；晨间资料读取、工具读取后撤销和回答生成后撤销检查3项通过，耗时9.38秒，日志`.work/takeover/main-final-morning.log`。

Python编译及`git diff --check`通过。前端源码没有因本次服务接入修改，沿用`.work/takeover/conversation-complete-build.log`的TypeScript与Vite构建证据。认证后的知识选择界面、完整授权摘要、查询趋势及其余32项服务要求继续保留；没有认证用户应用、执行真实外部模型请求或进行视觉检查，完整产品尚未交付。

## 会议资料目录（N04）

对应FR-04/05/07/09/10的资料目录及V7-FRONTEND第14项接收要求。`boss_v7_library.py`提供本人只读投影，接入`/api/boss/ui/owner/meeting-library`；只读取当前执行空间的正式对象，读取不写业务对象或审计。

会议记录采用当前会议对象及初始快照版本，参会人、材料版本、材料缺口、纪要状态与关联交办分别核查；材料按当前业务时间判断有效状态。资料记录只列出本人获准的模拟来源；撤销、失效或越出本人范围的来源保留状态并禁用“阅读原文”。待决定申请采用正式application对象及附件状态；人员会面采用person_brief当前版本与有效来源。研究材料当前没有正式存储对象，返回`NOT_PROVIDED`及原因，不生成样例记录。

目录动作携带目标页面与来源编号，包括准备会议、打开纪要、阅读原文、继续讨论、查看历史决定、打开申请和打开人员会面；会议尚无纪要时“打开纪要”保持不可用并给出原因。目标页面接收`bossLibraryContext`与`bossLibraryAction`并据此选取对象的功能仍待接入，完整连续流程尚未验证。

2026-10-26检查`app/tests/test_boss_meeting_library.py`3项通过，耗时2.03秒，日志`.work/takeover/meeting-library-tests.log`；会议审批、纪要交办及V7服务回归61项通过，耗时9.59秒，日志`.work/takeover/v7-owner-regression-20261026.log`。认证后的运行实例读取返回200，记录为meeting-1、finance-note、meeting-minutes，覆盖为meeting/document COMPLETE及approval/research/people NOT_PROVIDED，日志`.work/takeover/meeting-library-http.log`。N04实际页面显示“经营会议 · 2026-10-23”行、参会人与分类计数（会议1、资料2），日志`.work/takeover/meeting-library-ui.log`。没有执行会议材料写入、审批决定或外部请求；完整产品与用户验收继续未完成。

## 评测服务（A16/F31）

对应FR-31及V7-FRONTEND评测接收要求。`boss_v7_evaluation.py`提供`/api/boss/ui/admin/technical/evaluation`读取及`boss.technical.evaluation.start/reset/cancel`写入，身份限定MAINTAINER，写入走现有SQLite事务与原请求回执。

任务集采用当前获准模拟资料。`selection-core`包含四项断言：毛利率与原始明细一致、会议材料在业务时钟下有效且属于本人、本人记忆保持已确认版本、评测不写业务对象；`selection-evidence`包含来源版本与数据集摘要两项断言。启动必须携带全部所选对象的当前版本并明确确认人工配对条件；版本变化返回冲突。

版本目录来自正式状态：数据快照为当前执行空间的`selection` v1，模型为当前配置`deepseek-flash` v1，Prompt使用当前已启用版本，未配置时明确标注“内置运行时提示 vbuiltin-1”；SOP版本读取`agent/skills`中SOP01—SOP13的`0.1.0`。每次尝试保存全部断言预期与实际观察、证据编号、耗时与失败清单；没有模型请求时费用保持null、覆盖标记`NO_MODEL_REQUESTS`。失败的断言保存为失败记录，已结束的尝试不能取消；重置保留全部历史并新建尝试。评分与断言不进入Agent上下文，尝试记录不改写业务对象。

2026-10-26检查`app/tests/test_boss_v7_evaluation.py`4项通过，耗时3.53秒，日志`.work/takeover/evaluation-tests.log`；与会议资料目录、会议审批、纪要交办及V7服务回归65项通过，耗时12.27秒，日志`.work/takeover/evaluation-regression-20261026.log`。认证后的运行实例读取返回200，A16页面显示两个任务集、数据快照、模型、Prompt与13项SOP版本，日志`.work/takeover/evaluation-http.log`与`.work/takeover/evaluation-ui.log`。

2026-10-26 A16页面实际选择任务集、数据快照、模型、Prompt与SOP，确认配对条件后通过原生写入启动评测。服务记录尝试`eval-…`，状态`PASSED`，包含4项断言与4份证据，`usage_coverage`为`NO_MODEL_REQUESTS`；没有执行真实模型请求。日志`.work/takeover/evaluation-start-ui.log`。完整评分隔离与用户验收继续待执行。

## 场景与事件（A04）

对应FR-25与V7-FRONTEND第10项接收要求。`boss_v7_simulation_events.py`提供`/api/boss/ui/admin/technical/simulation-events`读取及`boss.technical.simulation-events.inject/reply/advance-clock`写入，身份限定MAINTAINER，写入走现有SQLite事务与原请求回执。

投影来自当前正式状态：执行空间、数据集版本、业务时钟及其版本、获准事件类型与目标、模拟作者、当前有效来源及全部操作记录。保存时逐项核查命名空间、数据集、时钟版本、目标版本、作者版本、来源版本与资料时间；内容、作者、来源或时间变化即拒绝。事件与回复保存为模拟记录与模拟事件对象；结果分项标记保存`RECORDED`、任务与通知`NOT_TRIGGERED`、模拟执行`NOT_TRIGGERED`、Agent`NOT_REQUESTED`，不把记录保存解释为业务执行。时钟推进采用当前版本、只允许前进且单次不超过366天，任务与通知结果标记`PENDING_CRON`，实际派发由CronService负责。

2026-10-26检查`app/tests/test_boss_v7_simulation_events.py`5项通过，耗时2.72秒，日志`.work/takeover/simulation-events-tests.log`；与评测、会议资料目录、会议审批、纪要交办及V7服务回归70项通过，耗时9.51秒，日志`.work/takeover/simulation-events-regression-20261026.log`。认证后的运行实例读取与A04页面版本选项见`.work/takeover/simulation-events-http.log`与`.work/takeover/simulation-events-ui.log`。事件对任务、通知及Agent的实际效果仍待后续接入，完整产品未交付。

## 会话授权摘要

对应FR-24/29及V7-FRONTEND第33项接收要求。`read_runs`为绑定当前任务的运行增加`authorization_summary`：执行对象、授权状态、待补条件与覆盖范围。授权取自当前正式authorization对象：未撤销、未过期，且目标或载荷任务与运行绑定任务一致；来源引用状态不是`CURRENT`时列入待补条件；没有有效授权时状态为`MISSING_AUTHORIZATION`、覆盖为`PARTIAL`。未绑定任务的运行不生成摘要，N02保持“尚未核查”。

N02“授权与必要决定”区域按该字段显示执行对象、有效授权、待补条件与覆盖范围；缺少条件只从正式记录产生，不推断授权通过，也不扩大业务写入权限。

2026-10-26检查`app/tests/test_boss_v7_authorization_summary.py`3项通过，耗时0.56秒，日志`.work/takeover/authorization-summary-tests.log`；运行记录、V7服务、评测与模拟事件回归38项通过，耗时11.43秒，日志`.work/takeover/authorization-summary-regression.log`。完整授权条件、Agent上下文采用及界面连续操作继续待验证，完整产品未交付。

## 专题查询范围响应

对应FR-14至FR-23及V7-FRONTEND专题接收要求。`boss_sector_api.py`接收`page`、可选`filters`与`overview_reference`，校验JSON对象与字段类型，回显实际应用条件并生成稳定`query_id`。返回`sector-workspace`投影，包含业务时钟、指标定义版本、按页面配置生成的覆盖标签、缺失字段、联系人及记录/趋势/关系集合；没有正式专题明细时指标保持`SOURCE_NOT_AVAILABLE`，不以示例数值填充。经营关注入口的范围引用原样返回，供页面核对同一查询范围。

2026-10-26检查`app/tests/test_boss_v7_sector_scope.py`3项通过，耗时1.44秒，日志`.work/takeover/sector-scope-tests.log`；认证后的F15与F22页面正常读取范围响应，覆盖标签与缺失字段显示，日志`.work/takeover/sector-scope-ui.log`。

`boss_sector_pack.py`按执行空间写入一次版本化模拟资料包`SECTOR-PACK-1`：每个专题页一份来源文档，包含2026-08至2026-10三项指标点、单位、定义版本与明确`SIMULATED`标记，数据由固定种子生成，不代表真实经营结果。包在应用启动时按数据集版本写入，重复启动不重复生成。

专题读取使用该资料包返回指标数值、单位、期间、来源编号、三点趋势与模拟覆盖标签，`availability`为`SIMULATED_METRICS_ONLY`。资料包同时提供按页面字段生成的模拟明细、章节文本、F16与F20的关系证据、F17的流程阶段；`applied_filters`参与明细筛选，来源统一指向当前资料包文档。资料包按页面配置提供`filter_options`，页面以选择框呈现区域、品种、阶段与比较周期等条件；选择后按明细维度筛选，例如 F15 选择“华东”后不再返回“华南”行。2026-10-26检查同一测试文件6项通过，耗时17.83秒，日志`.work/takeover/sector-filters-tests.log`；认证后 F15 返回4组筛选选项与6条明细，页面显示4个选择框并在应用“华东”后只保留对应行，日志`.work/takeover/sector-filters-http.log`与`.work/takeover/sector-filters-ui.log`。

2026-10-26检查同一测试文件4项通过，耗时1.81秒，日志`.work/takeover/sector-records-tests.log`；认证后的F15、F16、F17、F22读取返回200，F15为6条明细与4个章节，F16含7项关系，F17含5个流程阶段，页面显示明细、章节、关系与阶段，日志`.work/takeover/sector-records-http.log`与`.work/takeover/sector-records-ui.log`。

## 专题后续决定

`boss_v7_sector_actions.py`实现本人专题决定命令`boss.sector.decision.save`，仅对具备“记录资源决定”“调整项目”“记录安排”动作的页面开放。保存前核查页面、执行空间、数据集版本、由当前条件计算的查询编号、动作类别、来源版本以及目的与决定正文；版本不一致返回冲突。决定保存为带记录编号、版本、查询编号和来源的正式记录，不创建任务、计划或会议，也不发送消息。

专题读取返回`followup_actions`与`followups`：决定类动作在资料包可用时开放，协调、复查、会议类动作明确标记“当前服务尚未提供该后续动作”；已保存决定按页面列出并保留原查询编号。2026-10-26检查同一测试文件6项通过，耗时8.82秒，日志`.work/takeover/sector-decisions-tests.log`；认证后的F22读取显示决定动作开放，页面点击后出现目的与决定表单，日志`.work/takeover/sector-decisions-http.log`与`.work/takeover/sector-decisions-ui.log`。协调、复查与会议类后续动作及指标计算口径继续待接入。

## 集中复验（2026-10-26）

后端检查91项通过，耗时30.90秒，日志`.work/takeover/round12-regression.log`。覆盖会议资料目录、评测、模拟事件、运行授权摘要、专题范围与决定、会议审批、纪要交办、V7服务与运行记录。正式准备脚本构建通过，日志`.work/takeover/round12-build.log`；运行实例WebUI返回200。该结果证明上述源码范围与限定检查通过，不表示完整业务、专题数据口径、Agent接入或用户验收完成。
