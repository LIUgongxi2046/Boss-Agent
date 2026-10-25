# MENU-N02 聊天交办
## 2026-10-25 从F01工程冻结切换至N02：当前v7第一批集成接收

根据用户最新明确指令 `D-NEXT-MENU-N02-20261025`，先完整阅读 `docs/开发接手与执行规范.md`、`AGENTS.md`、正式 `specs/feature-delivery.json`、队列、N02原26项、FR-08/24/29 与共享 E01—E06、现有v6 HTML/加载CSS和全部 N02 正式记录，再核对 `main`。**从这批起本文件下方“DEVELOPED_PENDING_USER_ACCEPTANCE，26/26”属于之前 Desktop v6 限定交付历史**，绝不代替当前 Desktop v7 严格版验收。当前唯一活动 `MENU-N02`、v7 完整0/26、视觉未执行、用户待确认。F01 冻结源码 `5ac660330fce99c925163f06a62951563a24d383`，完整v7/目标Mac验收后置但未获批准降级；N03 源码与26项状态原样暂停保存，没有多菜单并行、自动认证、任何工作聊天的自动调度。

### N02 已修复真实问题、准确源及消费者

| 缺陷/对应要求 | 真实修改、实际消费者与恢复规则 |
|---|---|
| **当前任务上下文可能过期**；C07/C20/C21 | `50759cb`新增 `app/webui/n02-context-guard.ts`，`f672af7`/`1124446` 修改正式 `BossConversationWorkspace.tsx`：在连接断开、会话/身份变化、重新校验期间及 `boss.conversation.task.read` 失败后，不再将上一次 BOUND 任务及来源显示为当前有效的可操作对象。只展示同一 BOSS 当前连接并由正规接口成功核查的记录；原历史审计仍可读，不自动改业务结果 |
| **较早经营绑定响应覆盖当前会话**；C20/C21 | `sameActiveN02Scope` 对客户端实例、token、聊天ID、角色、可见页面和连接状态逐一匹配；旧响应与失败不能回写新身份/新会话。采用 `boss.conversation.business.read` 现有接口，不另造服务或越过后端 |
| **阅读位置重试误取消自身**；C23/C25 | `481707a`/`ba9b2f2`：恢复失败后的“重新定位原消息”按钮保留原 `conversationPosition` 技术坐标，不再在 click-capture/Enter/Space 阶段触发取消；Tab/Shift+Tab导航保留可达。用户主动在其它页面位置点选或其他键盘交互仍可中断旧恢复请求。保留 `BossConversationPosition` 与原生 `ThreadViewport` 阅读控制器的同一实现 |
| **断线/离开时运行资料仍显示上次当前值**；C09/C15/C18/C21 | `d1436ab`：`BossConversationWorkspace` 在非当前 BOSS/关闭连接/隐藏页面时，清除当前已采用的运行、附件及原请求列表，在原位置明确说明需连接后重读。既有的原生消息记录与用户输入由 SessionManager 和原草稿保护机制独立保存，**未删除实际会话或发件箱** |

**实测范围：**`40202750401` 的 N02 独立 GitHub Actions workflow 为 **Node 4/4、正式 SQLite/业务/任务/附件/来源 37/37、真实 nanobot AgentLoop/SessionManager/Registry 回归 59/59，合计100项 PASS/0 FAIL**。领域用例原有一个早期夹具未接入真实原生 SessionManager（对应晨间/任务入口互斥）导致首次 CI 失败；`903d9af` 调整为原 `ProductMorning.native.bind_sessions(sessions)` 正式注入，保持互斥和权限拒绝断言，没有跳过测试或伪造SDK。

固定上游产品构建 `40202750383` 中 `react-webui-build` 为 **PASS**，包含 nanobot锁定源码、签入原生补丁、真实TypeScript/Vite、再准备 manifest一致、真实dist/资源哈希与 Electron主进程语法；整个 workflow 的另一个 `python-domain-contract` 因之前 N03 代码/环境失败仍显示**FAILURE**，本次没有修改/屏蔽N03。该构建的**产品源码提交** `d1436abc614dbfeb842421b5b1bdefe53d9d5df9`；GitHub Actions `boss-agent-frontend-d1436abc614dbfeb842421b5b1bdefe53d9d5df9`，artifact ID **12603035088**，约10.8MB，GitHub报告 ZIP SHA256 `d436ac9bc8684d0a26a2c1b4f0e03a5b622a3d90d86b330e0cf782f37a019f3a`，**2026-11-08到期**；内容只有完整静态前端与编译来源摘要，不包含Mac安装包/账号/个人SQLite。复用 `scripts/verify_f01_candidate.py` 中的**通用只读产品哈希验证**（旧文件名不表示这是F01版本），后续人工运行应使用对应原始 `repo_commit` 的隔离工作树而非旧N02 v6体验目录。

### 新版N02人工验收启动器与准确制品

`2a8a4f5` 在 N02 唯一当前菜单内新增 `scripts/run_n02_manual_review.command`，该入口只做编译来源/本地 HEAD/哈希一致性、手工预置的独立账号目录/端口及前端目录安全检查，**不会自行登录、自动初始化、读取凭据正文、修改现有用户 N02/F01/UI02/MVP 或触发真实外部调用**。新默认独立端口 `11421/11422/21421`，新资料目录必须单独命名为 `menu-n02-v7-review-*`；若缺少用户准备则安全失败退出，不将此视为运行成功。CI `b5b05d2` 还校验该 Shell 语法。

**能够同时提供新启动器与实际对应编译制品的准确仓库提交为 `b5b05d2da40299045cae36842006edf87c211ef9`**；经 GitHub compare 从产品源码 `d1436abc614dbfeb842421b5b1bdefe53d9d5df9` 到 `b5b05d2` 仅 CI/N02交接/正式状态/新增启动器变化，前端功能代码未变化。新提交的 `40203082570` 中 `react-webui-build` PASS、整个 workflow 因 N03 旧 Python job 仍 FAILURE；准确产物 `boss-agent-frontend-b5b05d2da40299045cae36842006edf87c211ef9`、artifact ID `12603230096`、GitHub ZIP SHA256 `f71ef50d4a2af43c76047bd7f4beb8b086e5ebc84142c8377bfa5ba31915afd4`，约10.8 MB，2026-11-08 到期。后来的文档更新不改变该编译产物。实际手动体验步骤和必需阻碍见 `docs/menu-delivery/N02/experience-v7-revalidation.md`。这个 ZIP 仅静态前端，不等于完整 Mac 安装包、用户已登录或v7高保真通过。

### 当前必需的未验证项与继续实施顺序

既有N02旧版`docs/menu-delivery/N02/delivery.json` 的26/26和旧UI/布局/启动器证据保留为同版本历史，不作为新版分子。新版仍缺 Desktop v7 N02（历史摘要2880×5256）的完整原HTML、加载CSS/JS与引用素材原字节，目前仅可读取 Library ZIP 名称/尺寸而无法用于本任务成对 DOM/计算样式对照；当前目标Mac手动登录、原生连续操作、真实Dialog/焦点/滚动、断连及同库持久化的**本候选实际 GUI**也尚未进行。不要沿用旧 `scripts/run_menu_n02.command` 的v6制品宣称当前main体验完成。

进入下轮时只推进 N02 真实已证实的阻断级缺陷、当前FR/BR/AC必要行为和独立验证。不得重新启动 F01 普通开发、并行 N03、打开视觉/截图或自动账号初始化；保持 SIMULATED_FIRST、STT 暂停。正式26项里，已有功能与模拟/源码集成证据在本节准确列明，但当前所有必需视觉结构/真实整页状态/准确GUI尚未成对确认，所以 **新版完整0/26** 与用户待验收在唯一状态中保留，避免走之前F01无限叠加局部测试的循环。



task_id=MENU-N02-N3；CURRENT；2026-10-25；DEVELOPED_PENDING_USER_ACCEPTANCE。唯一正式状态来源为原始specs/feature-delivery.json。完整稳定范围MENU-N02.C01—C26，baseline_id=boss-menu-n02-coverage-20261024-v1；当前开发覆盖26/26，用户通过分子null，视觉及用户验收独立待确认。完整逐项证据为本目录delivery.json，连续操作为experience.md。

当前实现3ebb31cdcac6f90e39b3b2c0808e5e9f21116c98；准确交付候选由正式状态文件提供。业务/原生实现继承22180cb5ad9bf855d2241590e4815853aaab7d44，当前指定标题导航样式与实际状态核查已合入。制品manifest=b2b0d845349e0a87d5263a501f2821c4e6a64223bcca37e2d7443c7e5166d6b4，index=d48741e7cb653318a8cf275a93b1ae2680e2a280de7079d7c6d0f2d34b447139；严格TypeScript及Vite构建15.58秒。

## 输入与当前依据

使用S000 DELIVER、S008以及适用S003-2/S005-4。已读取适用AGENTS、原始N02完整26项工单、当前PRD决定、完整FR-08/24/29及BR/AC、共同BR-C01—C07/E01—E06、FR-27暂停范围、原HTML/页面配置/原始提示词、实际加载chat builder、design-v6.js、CSS/Token及交互规范。检索开发索引、UI02/F01/MVP、FC01/02及消息/日历、原生会话/附件、公开Page/Command/RoleChannel与当前Runtime。

D-MENU-DELIVERY-20261024规定一个活动实施菜单；D-UI-FIDELITY-20261024要求按原稿核查必要区域、字段、比例、样式和状态。F01必要设计返修须在N03前完成；本N02交付不登记F01/F06/F08等完整菜单或FR-27完成。

## 实际实现与接口

| 文件或identifier | 当前职责及实际使用方 |
|---|---|
| BossDesktop、delivered-navigation、boss-n02.css | 同一可信身份与Shell，N02合法导航、标题、历史、连续对话、执行/来源/产物/异常；当前未交付菜单不可用 |
| BossConversationWorkspace、PublicConversation | 当前chat/session的正式运行、原请求、附件、来源关系、消息及产物重读；服务端核查本人、当前订阅及范围，客户端不能提供owner/namespace/session_id |
| NativeConversationAgent、ProductConversation、RoleChannel | 同一实际Nanobot AgentLoop、ClientProvider、Registry及SessionManager；当前意图/媒体摘要、工具参数摘要、固定配置与正式结果；没有第二模型循环或模型本人确认工具 |
| BossTaskConversationEntry、ConversationAPI.task_entry | F06实际选定任务的prepare/bind/read/receipt；固定任务/来源版本及摘要。实际原生空会话保存后绑定，打开期间零问题/Runtime/业务任务/发送 |
| App、ThreadComposer、ThreadShell、ComposerDraftController | 当前进程的文字、真实附件、引用及排队输入；persistQueuedPrompts=false。D06继续编辑保持内容，明确放弃清理原范围，退出及关闭使用同一保护 |
| BossConversationPosition、ThreadReadingController | 原chat、原生消息标识、相对位置、工作区位置、历史展开、原运行及返回操作。仅技术标识及数值进入地址，正文/附件/凭据不进入普通持久缓存 |
| ThreadViewport、readingHistoryPending | 原消息经实际历史分页呈现后恢复；初始loading、较早分页及消息采用均参与等待。失败明确说明，本人交互及显式新会话取消恢复 |
| BossCommunicationCalendar、既有交办共享流程 | 正式联系人、正文/附件/范围/版本及本人授权；保存草稿、模拟发送、回复、准备交办和本人确认分别处理；返回原会话及阅读位置 |
| main.cjs、preload.cjs、guardLeave/requestLogout | 受控主窗口当前主Frame及实际关闭请求；继续编辑保持窗口与后端，明确放弃才退出。账号填充仅在明确本机演示模式按对应角色执行，没有自动提交登录 |

任务绑定前重新核查当前任务与来源，官方gateway.workspaces.persist_scope保存实际空会话及已有空间范围。当前身份、任务/来源版本和本次选择在准备、绑定、打开前分别核查；等待期间新增编辑再次使用D06。prepare/bind进入不重放清单，未知按原client_request_id只读核查；历史回执不授予当前采用资格。当前任务正式取消或版本变化后，后续输入在Runtime创建前拒绝，原记录保留。

原生消息与当前工具均使用正式服务结果。一般会话配置必须启用七项会话工具及WORKSPACE_PROJECTIONS；默认配置启用14项既有工具，晨间绑定实际限定四项，普通会话实际限定七项。每次运行固定配置版本及当前授权范围。Runtime Schema1.13.0接收受限conversation_context/task_entry及摘要/正式引用，拒绝正文、原始参数和额外私有字段；RUNTIME_RECORD只允许conversationRead及其受限元信息。

运行终态与业务状态分别呈现。草稿保存零发送，正式模拟发件仅保存一次；SENT、delivery_state、reply_to与任务进展分别重读，NOT_VERIFIED保持未验证。准备交办缺少条件或取消确认均零任务，明确本人确认后创建OPEN；运行结束没有结束任务。未知写入、刷新、重连及服务重开均不能自动再次提交。

跨页返回采用当前本人及当前chat重新读取，保留原消息、原运行、内外滚动及触发操作焦点。控件在click阶段取消在途恢复，普通区域、滚轮及键盘按实际交互取消，避免在一次点击中改变目标位置。原消息缺少时明确报告，不能采用其他会话或消息。历史阅读不因后续输出强制跳到底部，查看最新进展由本人触发。

## 接收的准确依赖

| 范围 | 生产者及接收 | 当前必要证据 |
|---|---|---|
| N1附件 | 6164aac401712f397072fdfac788d04ffd91488a→eb9a4fe | native-file-receiver.xml：23 passed，8.05秒；真实原生上传、原名/类型/大小/摘要及当前保存状态 |
| N1上下文与任务引用 | 9c47e229e3ee6e67d853076b6b98089e7067e966→66fc44d；8f2fa156e739b1d0a16640988bb5e75da31e2eb7→d5c9316 | context-reference-receiver.xml：13 passed，8.61秒；task-reference-receiver.xml：6 passed，6.45秒 |
| N1任务入口 | 5fb1def3cfd17e895691ccd8c52d1effed441886→5919fd3；记录接收4d7038dc7e5accb2e0123a3f3a28392e2a8c2385 | task-entry-receiver.xml：14 passed，3.96秒；既有消费者4 passed，3.86秒；Conversation Schema1.3.0 |
| N2一般原生消费 | b1eb8ed5c4bdf8458591bf541173572298343483→2260000；cd1a5b0f75b68da909fc423bc8125580f9cbcc19→1b7a7fa | 同一SDK/Registry及实际工具参数；native-runtime-receiver.xml保留61 passed，144.412秒 |
| N2原请求/当前引用 | a74e97abb4d8a93a027cc6287e6e941a5d0917cb→9c3caf8；3259f2a4ff74420b8b8b6b941bef37e96ff35472→490ba0b | 尚无Runtime的准备失败也可只读核查，当前必要引用和历史采用分别呈现 |
| N2取消/期限/可观察失败 | 4836527f3de19383d5eed8bb608c4fc891215104→e31370e；d6196221f92d5e9b325a6e3011b217d782a1225b→ba1fbde | 当前配置120秒实际经过120.424秒；observable-failure-receiver.xml：4 passed，3.88秒，真实输出管道失败保留已保存结果 |
| N2固定任务消费 | e2d76dceb354d50781fd13f0100d2979a74f3c7a→6d620bb | task-bound-consumer-receiver.xml：16 passed，10.68秒；模块1.3.0 |
| N2严格Runtime Schema | b5e2fbe6a6571d90f5f3c2d5c0ae407e3817980c→b131d96 | task-bound-schema-receiver.xml：4 passed，4.32秒，包含58项受限输入拒绝；Schema1.13.0，基准为固定def38c6原文 |

生产者完整85项SDK回归为160.79秒，包含实际120秒deadline；该数量不改记为N3当前界面检查。N1领域及消息消费者received-domain.xml保留19 passed、10.81秒。未变后端及SDK依赖按准确版本沿用，当前公开消费者另外验证完整1.13.0。

## 当前实际验证

全部12份界面/启动报告采用同一当前b2b0制品：11份PASS，framework-current为MEASURED。实际SQLite、原生WebSocket、公开认证、当前Runtime及隐藏Electron DOM均来自独立本机实例，没有mock或替代业务结果；全部外部SIMULATED_FIRST。

| 报告及命令入口 | Given/When/Then与当前实际断言 |
|---|---|
| native.json；check-menu-n02-native.cjs | 本人真实新会话连续读取及追问；参数摘要随来源/经营条件变化，每轮单一N02 Runtime；同键异内容拒绝、重复轮次零重复；真实JSON上传、仅附件等待用途、来源元信息及完整查询/任务产物。共享F08单次模拟发件、正式回复reply_to、F06明确创建OPEN、完整返回；同库服务重开保持14运行/15原请求及附件，完整Schema1.13.0 |
| task-entry-ui.json；check-menu-n02-task-entry.cjs | 实际F06选择及D06；prepare/bind成功响应分别真实中断，每项提交一次；刷新原编号恢复，显式打开期间零问题/Runtime。本人问题采用固定任务/来源；当前来源/任务详情返回保持。真实迟到准备不改变新选择，绑定期间新编辑保留；新会话无原任务；任务正式取消后FAILED/null Runtime |
| morning-entry.json；check-menu-n02-morning-entry.cjs | 当前F01晨间两轮及选中事项进入N02，固定清单/事项/来源版本与实际SDK一致，刷新/返回对象保持；晨间四工具，显式新会话七工具且没有原晨间上下文。F01完整设计及焦点验收单独保留 |
| return-position.json；check-menu-n02-return-position.cjs | 同库重开32次真实SDK运行形成的历史；实际发送成功响应中断后刷新及原编号只读核查，再返回原消息。较早历史读取一次，消息相对位置-77px、scrollTop93、工作区35px、原运行和按钮焦点恢复；本次一次发送、零新增Runtime。再次真实延迟历史HTTP响应后显式新建会话，当前输入/选择保持且旧消息未进入新会话，零新增发送/Runtime |
| unknown.json；check-menu-n02-unknown.cjs | 实际草稿保存及发件成功后中断真实响应；刷新/重连不再次提交，原编号只读得到原对象及唯一发送，返回N02入口保持 |
| input.json；check-menu-n02-input.cjs | 真实Chromium IME候选Enter零提交，Shift+Enter换行、空白不可提交；65536 bytes文字及6291456 bytes实际文件准确允许边界，实际超限源码及源码导出拒绝。真实权限读取失败、选择取消、四附件/数量拒绝、格式拒绝及192 bytes长文件名保留原输入；D06/退出/两角色重登隔离，零提交及零STT |
| native-privacy.json；check-menu-n02-native-privacy.cjs | 实际产物Dialog/Escape/焦点；后续真实输出到达时本人历史阅读位置保持；真实延迟输出下排队输入只在内存，明确放弃后不恢复；仅附件离开保护 |
| close.json；check-menu-n02-close.cjs | 真实窗口关闭及app.quit使用D06，继续编辑保持文字/附件/服务；共享F08关闭及退出继续编辑保持；明确放弃实际应用退出码0。有限动画完成后六组视口目标≥44px、Tab/Shift+Tab真实操作 |
| shared-layout.json；check-menu-n02-shared-layout.cjs | 固定任务状态、共享F08及业务D06各六组，目标≥44px且滚动后位于视口内，没有页面横向超出；业务D06可见焦点solid3px/rgb(23,91,165) |
| framework-current.json；check-menu-n02-framework.cjs | 同一视口18组默认、18组展开及18组提交按钮五状态；本实例12次真实请求形成历史，搜索及键盘选择、对应历史恢复。外框/列/hero/输入/子Panel/SVG/实际滚动与原稿记录对应，主操作84×44px、14/690/24px，输入88px/600 |
| header.json；check-menu-n02-header.cjs | 原稿及产品18组标题导航；品牌文字Range，字体/颜色/背景/圆角/字距/显示，其他元素padding/gap及头像宽高比较差异零。18组各2项选中/未选中导航悬停、按压样式相同；真实Tab/Shift+Tab及solid2px/rgb(10,100,232)/外距3px。搜索左右14px、≤700快捷6px，当前可见操作目标≥44×44 |
| launcher.json；check-menu-n02-launcher.cjs | 独立10791/10792/20791实际新建初始化并重用启动；14项有效配置版本及一般会话实际七工具。受控主窗口分别填BOSS/MAINTAINER表单，零自动登录，手动正常认证及单窗口；密码不在普通地址/存储中，账号文件元数据和业务资料保持 |

各命令为validation/desktop下同名Node脚本，使用validation/.venv与已安装Electron/Playwright。中断代理只处理真实请求/响应的延迟或交付中断，不替换正文或业务结果。运行与任务/发件结果分别重读；可观察事件只采用实际SDK字段，不索取或保存内部推理。轮数限制包含准备阶段拒绝，不声明已经进入SDK max_iterations耗尽路径。

## 设计与指定审查

原HTML/source_summary的历史、连续输入及任务/来源，与实际loaded chat的当前上下文、对话执行、持续进展共同采用。固定Token、原SVG/品牌素材及原断点保留；语音明确暂停。真实身份、当前事实及权限进入产品，预览工具与静态业务答案不进入产品。数值与分组见design.md和design-gaps.md。

当前主列加310px右列，≤1250为260px，≤1050单列；历史默认收起，宽屏展开213px。品牌文字17/26.35px、820及#172B4D；身份头像33px原渐变，身份文字11/15.4px，≤1250按原规则隐藏。小窗口快捷操作最小宽度44px依据Token/工单目标，其余字体和内距采用原稿。有限CSS过渡结束后读取实际状态。框架自动比较、原始测量及本记录组合判断分别保留，未测像素/视觉细节不作通过声明。

N4完整交付资料已核查准确a1f8a2a/6399f83，指定修正关闭后准确3ebb31c的G05及导航状态审查APPROVED；当前qa.md摘要404c7dadd9a778334933a211440c5cc43fafefe9879bbf33d8b8b4753c5ec2e5，turn=01a16fcb-6291-74f1-a240-46592bac5728，marker=MENU-N02-N4-SPACING-CLOSURE-20261025。G04/G05关闭，该指定范围没有确定剩余必要缺陷。N4没有执行产品或浏览器，没有独立全26项PASS要求；N3当前12份实际报告与逐项映射另行完整登记。

## 交付、资料与限制

scripts/run_menu_n02.command使用独立menu-n02-n3-dist、validation/.work/menu-n02-release-experience及10711/10712/20711。最终目录已经READY，实际配置版本2、14项注册工具和四项资料投影；用户资料没有用于业务测试。初始化只在新目录创建获准模拟资料及账号，通过正式维护入口保存/核查/启用；已有目录启动核查声明，不重写账号、SQLite或配置。

candidate-inventory.json核查693份来源、实际安装Nanobot、准确制品、配置和报告摘要，排除凭据值。F01原manifest e3b36c80baac9bbba869d5012b53d38c43b2a05d1869ec9ce10a0c365bafd62c及index 11a935970330ddfa87e50faeb5f266cd27163f11750945e01797be25d3396b1f保持；UI02/MVP制品亦核查一致。F01/UI02/MVP原资料、SQLite、会话、窗口和10611/10411/9961等各自端口不用于本次验证，不终止、重启、覆盖或热替换。

检查在启动及生成运行前核查空间，常规至少200MiB，含大文件导出的输入检查至少230MiB。只清理无进程使用的独立浏览器缓存、可重新生成的源码导出及已确认旧pytest临时ControlStore数据库；当前账号、业务数据库、原生历史、报告和全部用户体验保持。

全部外部SIMULATED_FIRST，没有新增真实模型/外部投递请求。未知usage/cost/price等保持null；STT/F27/FC28按用户暂停。视觉、用户验收、真实外部质量/送达及独立安装未执行。当前26项开发交付完成后处理F01必要设计返修，再进入N03；始终只保持一个活动实施菜单，四聊天仅在发送前复查idle后一次必要续接。
