# MENU-N02 聊天交办

task_id=MENU-N02-N3；CURRENT；2026-10-24；IN_PROGRESS。唯一正式状态为原始目录 specs/feature-delivery.json，主工单为 /Users/liuhaoxian/Downloads/我的/AI项目/Boss-Agent/docs/menu-delivery/N02.md。当前完整稳定检查点 MENU-N02.C01—C26，baseline_id=boss-menu-n02-coverage-20261024-v1，共26项，初始结果 NOT_RUN，候选和开发覆盖分子待核实。视觉及用户验收独立。

当前另有 D-UI-FIDELITY-20261024：执行原始 docs/menu-delivery/高保真还原执行要求.md，所有菜单高度还原原稿，公共框架及正文宽度、比例/层级/间距、组件尺寸/文字/图标和交互逐项核查。当前 Shell 和开源默认布局不能作为接受差距的依据。F01状态为需要设计返修，原业务证据保留；当前仅实施 N02，进入 N03前完成 F01必要返修，用户 F01/UI02/MVP窗口和资料保持。

## 输入、检索与当前依据

使用 S000 DELIVER 整理需求、实际依赖与续接；实施使用 S008，界面/前端设计继承已采用 S003-2/S005-4。已读取当前 PRD 决定、菜单计划、完整 FR-08/24/29、FR-27 暂停范围、共同 E01—E06、N02 原 HTML、页面配置内完整对象、原始提示词、实际 chat builder、design-v6.js、样式及 Token。通用状态 S00—S10 由交互规范继承；N02 的独立 states 数组为空，不据此删除状态要求。

检索开发索引、UI02、F01、FC01/02、T18消息与日历记录、公开 Page/Command 和原生会话。准确前置业务体验候选 d0e6326bcca49a2c8372c476c50808d454076127；F01原业务证据按未变依赖保留，当前设计返修及用户验收待确认。F01 制品、启动入口与10611/10612/20611保持；新 N02 不使用这些业务资料验证。

## 依赖与责任

| 依据 | 当前结论及消费者 |
|---|---|
| 需求/设计 | SATISFIED；当前完整26项工单、原 N02 区域与通用状态，不按原生组件当前功能缩减 |
| 身份/原生框架 | SATISFIED 输入基础；UI02 当前 ClientProvider、历史、新建/选择/搜索、原生输入/上传/流式/停止及 D06；当前完整采用仍需逐项核查 |
| 领域/消息/来源/版本 | 已接收附件6164aac至eb9a4fe、上下文9c47e22至66fc44d及记录c9dada0；Conversation Schema1.2.0、实际上传及正式来源元信息已采用。任务实际工具引用的来源投影继续核查 |
| Agent/Runtime | 已接收原生b1eb8ed至2260000、条件查询cd1a5b0至1b7a7fa、原请求历史a74e97a至9c3caf8；六项读取和query_metrics共七项正式工具，同一实际AgentLoop及Registry |
| 公开接收/前端 | N3唯一维护实际注册、RoleChannel、App、Shell、组件/样式、独立制品与连续验证；采用准确已有接口，不编造新业务值 |
| 独立核查 | N4按原 PRD/设计建立26项独立矩阵；准确候选后只核查必要差距和受影响消费者 |
| 新框架/真实外部/新视觉 | NOT_APPLICABLE；沿用当前技术及设计；SIMULATED_FIRST，FR-27保持暂停 |

原 HTML 的会话列表/中部对话/任务与来源，与实际加载 chat 的当前会话/对话执行及持续进展共同映射。历史区域保持克制，当前任务/来源可打开，连续阅读及输入采用原生组件，区域顺序、宽度、间距和重排依据保存到当前设计说明。固定 Token、44px目标及键盘/200%要求继续有效；设计预览标识和静态示例不进入产品。

## 当前验证与续接

当前没有完整 N02产品或业务通过声明。26项必要断言引用完整工单；N1/N2已有正确接口直接接收，存在差距才增量实施。公共层需要核查自然输入、附件、当前事项、同一 Runtime、任务/来源/产物、消息授权、原编号恢复及独立共享路径，不能仅将旧原生会话改名后登记完成。

已实施当前草稿及普通缓存保护增量：ThreadComposer暴露仅在进程内的 ComposerDraftController，涵盖文字、实际附件、引用和排队输入；ThreadShell透传，App以当前会话注册，用于切换、浏览历史地址及离开业务路径。本人明确放弃时清除对应未发送内容，返回继续编辑保留内容；beforeunload覆盖仅附件/排队状态。本人会话明确设置 persistQueuedPrompts=false，继续使用原生内存队列，不读取或写入普通 localStorage队列正文。源码增量保存在 app/webui/nanobot-menu-n02.patch。

独立menu-n02-n3-dist完成TypeScript及Vite构建，当前manifest=9abccea0d664926083f9e568e3d3bcf088a30fa1ddc3651386ced43835961c8e，日志.work/menu-n02-build.log。`check-menu-n02-native-privacy.cjs`的最近证据为native-privacy.json，manifest=04982d32e86a0183e68bba1cbcfa5747a5cd0ed97c669d4ab75b02d3582c5c3e，独立10731/10732/20731及代理10733。实际产物Dialog/Escape/焦点、批准YAML仅附件离开保护、真实输出延迟下内存队列未发送/不缓存/明确放弃后不恢复均通过；当前完整候选按未变控制器及实际消费者继续核查，不据该限定结果登记26项通过。

BossConversationWorkspace采用真实topicSessions、原生新建/选择/搜索、同一ThreadShell和D06；主列保留当前关联事项、资料版本、任务对象及对话/可观察执行，右列呈现实际进展、异常、来源与可展开附件。实际Runtime产物通过当前会话及原运行引用重读，关闭后返回原按钮；请求/身份/会话变化使迟到结果失效。N02为当前实际入口，原NATIVE本人地址保持兼容，维护Settings保持既有入口。F08仅开放本菜单所需的既有共享消息路径，完整消息授权/回复和一般会话采用继续核查。

N2模块提供ConversationContext/ConversationScope、六项正式读取适配、ConversationQueryTool、ConversationSimulatedProvider/ConversationRuntimeRecorder及NativeConversationAgent，记录输入/参数摘要与正式引用，不提供模型本人确认。当前公共ProductConversation采用同一AgentLoop、SessionManager、Registry及Runtime；query_metrics明确使用继承ConversationReadTool的ConversationQueryTool、同库Fc02Tool及本轮QueryBinding，执行前后检查当前范围与允许参数摘要；其他读取按当前可信范围适配。FeatureRecorder准备阶段使用当前RequestContext，配置必须实际启用七项工具及正式工作投影模式。已接收原请求模块的当前组合为54 passed、16.77秒，native-runtime-receiver.xml；正式读取、查询、普通文档、仅附件、命令、取消/超时和原编号历史分别保持限定范围。

公共runtime-records.schema.json为1.12.0：接收feature_id=N02、conversation_context中输入摘要/允许调用摘要/正式引用、原请求及媒体摘要、附件编号/摘要/状态和待补充数量；工具结果允许正式draft_id及parameters_sha256。不接收正文或原始参数。RUNTIME_RECORD只允许conversationRead，并禁止携带source_id、query_id、task_id、message_id、draft_id、authorization_id、source_refs或bi_query_context；SIMULATED业务结果继续采用原有规则。当前公开消费者形成的14条真实运行全部通过CurrentRuntimeRun严格验证，check_menu_n02_runtime.py及native.json保存实际结果。

RoleChannel在原生router之前核查当前本人、attach、token及期限，优先采用晨间绑定，一般会话通过NativeConversationAgent.admit接收。实际上传成功后内部record_media采用gateway返回路径；同一chat/turn内容重复只返回原回执，同键内容变化拒绝。boss.conversation.request按当前连接的chat_id/turn_id读取，HTTP原编号入口仅按client_request_id读取；均不产生业务变更或自动重放。SDK非Agent命令保留原路径。准备失败仅记录provider名称、时间及错误类别，不记录输入或原异常正文。

check-menu-n02-native.cjs已通过，准确制品manifest=9abccea0d664926083f9e568e3d3bcf088a30fa1ddc3651386ced43835961c8e，证据native.json。独立10761/10762/20761、生成的测试账号和SQLite通过实际WebSocket连续来源读取及追问，参数摘要随选择变化，每轮只有一个N02 Runtime；重复轮次没有额外执行，同键异内容拒绝，未知编号读取没有写入。真实JSON附件与仅附件提交分别保存元信息或等待用途；经营条件不足等待，补充后产生正式查询，改变产品及指标后产生关联父查询的新结果和新参数摘要。页面当前来源支持关系、原/当前版本、完整查询表格、Dialog关闭和焦点返回均按实际结果核对；问题不进入URL或普通存储。

同一公开连续检查从N02进入共享F08，使用正式联系人及实际财务资料保存草稿；未保存编辑由D06保护，草稿保存零发送，当前本人明确确认后只产生一条SIMULATED发件，维护输入明确SIMULATED回复后reply_to仍指原消息，delivery_state保持NOT_VERIFIED。返回同一会话的运行选择、滚动和焦点保持，Native实际读取原消息后可以重读同一业务对象。共享F06缺少条件和取消决定均零任务，明确创建后新增OPEN任务且没有自动发送；Native读取形成同一task_id/version的实际产物，运行结束没有结束任务。共享路径不登记F08/F06整套菜单完成。

实际完成且finished_at已保存的WAITING_INPUT不计在途运行，运行配置可以正常继续维护；QUEUED/RUNNING及尚无结束时间的等待记录继续限制启用。公开检查通过真实维护配置暂时缺少必要工具产生准备失败，原client_request_id保持FAILED且run_id=null；恢复配置后新请求正常。boss.conversation.requests严格接收chat_id，当前本人/attach/有效身份和资料范围均核查；维护、未订阅、注入归属或错误字段拒绝。关闭本检查自己的服务并同库重启后，14个run_id、15个原请求、附件和原回执保持，没有额外执行。

N1领域与既有消息消费者在当前PRODUCT共19 passed、10.81秒，原始证据evidence/menu-delivery/N02/received-domain.xml。PublicConversation已接入RoleChannel的四项只读webui_request：boss.conversation.read/artifact/messages/attachments。身份和会话归属由当前认证连接及已订阅chat核查，session_id从原生映射产生，客户端不能提供owner/namespace/session_id。消息历史明确为OWNER_MESSAGE_HISTORY。`check-menu-n02-conversation-read.cjs`通过，结果public-read.json；采用独立10741/10742/20741及实际SDK晨间运行依赖，证明准确运行/产物读取、重复读取不变及维护/未订阅/注入字段/无关产物拒绝。该检查不证明一般会话规划、完整附件处理或完整N02菜单。

实际原生上传成功后，由RoleChannel当前请求内的可信上下文将accepted_media/accepted_paths交给PublicConversation内部record_upload；模型和客户端没有文件路径命令。Schema1.1.0公开区分当前/上传时大小与摘要、可空原生位置及STORED/MISSING/CHANGED/REFERENCE_UNAVAILABLE，不公开内部文件引用。实际WebSocket上传批准morning-coverage.json并完成SDK保存后，public-read.json核对原名/MIME/大小/摘要、无路径输出与原运行；附件领域/SDK保存/既有消息消费者23 passed、8.05秒，证据native-file-receiver.xml。文件保存不授予业务来源资格。当前文件变化状态及一般会话实际采用仍需对应消费者。

N1上下文9c47e229e3ee6e67d853076b6b98089e7067e966已接收至66fc44d；当前上下文和附件接收13 passed、8.61秒，context-reference-receiver.xml。当前页面直接呈现正式context_references中的原/当前版本、作者、时间、范围、采用状态与上下文/工具支持关系，不根据模型正文推断来源。任务实际工具引用的必要投影继续由N1核查，marker=MENU-N02-N1-TASK-REFERENCES-20261024。

N2当前必要原请求只读历史a74e97abb4d8a93a027cc6287e6e941a5d0917cb已接收至9c3caf8，公开Schema为conversation-requests.schema.json，包含尚无Runtime的准备失败或取消记录。明确来源追问与独立问题的必要引用核查由N2交付3259f2a4ff74420b8b8b6b941bef37e96ff35472，当前待准确接收；marker=MENU-N02-N2-CURRENT-REFERENCES-20261024。公开注册由N3负责，同一请求不得重复生成Runtime。

原设计实际加载检查已运行：18组DOM/计算样式/尺寸见reference-dom.json，含三种窗口100%/200%及阈值相邻样本。当前独立10751/10752/20751及真实新建空会话记录framework-current.json；核查同一实际视口、外框、导航宽度、标题区边界/字号和stage内距/间距共18组。源码及样式按N02-D01—D12必要差距实施，六项主导航与原稿快捷操作保持；尚未交付菜单保持不可用、语音暂停；当前业务入口继续可从目录访问。正文/控件、全部状态及交互仍需完整复核，记录见design-gaps.md，不能把框架尺寸结果作为完整设计通过。当前N02构建未改变F01冻结manifest e3b36c80baac9bbba869d5012b53d38c43b2a05d1869ec9ce10a0c365bafd62c及index 11a935970330ddfa87e50faeb5f266cd27163f11750945e01797be25d3396b1f，已只读复核。

已发送当前四窗口的角色续接，marker=MENU-N02-START-20261024；每次发送前复查 idle。N1 turn=01a16df8-d1c1-79f3-87d2-3b362d5c889e，N2 turn=01a16df8-e6aa-7ac3-8a7b-a0abfc791fc0，N4 turn=01a16df8-f3bc-7ad1-8f73-d95ab5c77283；工具分别返回对应既有 threadId。运行中仅只读，角色准确自然交付后接收必要增量，禁止重复接续。

主记录随准确接口、设计选择、实际修改和原始结果更新；保持全体未完成项、当前范围与必要阻塞。正常完成当前26项后登记开发交付待用户验收，并处理进入 N03前必要的 F01设计返修，始终只实施一个菜单。暂停语音独立保留，不计完成。现有四窗口仅在 idle 复查后一次具体续接，marker=MENU-N02-START-20261024，运行中只读。

## 资料与运行

保护原 UI02/MVP 及当前已交付 F01 的制品、账号、SQLite、会话、端口与用户窗口。新候选使用独立目录、制品和端口，不自动退出、重启、覆盖或热替换已有体验。受控账号注入仅填写当前角色表单，手动登录仍经正常认证。全部外部 SIMULATED_FIRST，无新增真实外部请求；STT/F27/FC28暂停。禁止主动视觉、截图、图像、/tmp、Git恢复和程序化修改源码。
