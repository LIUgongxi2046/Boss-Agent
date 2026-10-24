# MENU-N02 聊天交办

task_id=MENU-N02-N3；CURRENT；2026-10-25；IN_PROGRESS。唯一正式状态为原始目录 specs/feature-delivery.json，主工单为 /Users/liuhaoxian/Downloads/我的/AI项目/Boss-Agent/docs/menu-delivery/N02.md。当前完整稳定检查点 MENU-N02.C01—C26，baseline_id=boss-menu-n02-coverage-20261024-v1，共26项，初始结果 NOT_RUN，候选和开发覆盖分子待核实。视觉及用户验收独立。

当前另有 D-UI-FIDELITY-20261024：执行原始 docs/menu-delivery/高保真还原执行要求.md，所有菜单高度还原原稿，公共框架及正文宽度、比例/层级/间距、组件尺寸/文字/图标和交互逐项核查。当前 Shell 和开源默认布局不能作为接受差距的依据。F01状态为需要设计返修，原业务证据保留；当前仅实施 N02，进入 N03前完成 F01必要返修，用户 F01/UI02/MVP窗口和资料保持。

## 输入、检索与当前依据

使用 S000 DELIVER 整理需求、实际依赖与续接；实施使用 S008，界面/前端设计继承已采用 S003-2/S005-4。已读取当前 PRD 决定、菜单计划、完整 FR-08/24/29、FR-27 暂停范围、共同 E01—E06、N02 原 HTML、页面配置内完整对象、原始提示词、实际 chat builder、design-v6.js、样式及 Token。通用状态 S00—S10 由交互规范继承；N02 的独立 states 数组为空，不据此删除状态要求。

检索开发索引、UI02、F01、FC01/02、T18消息与日历记录、公开 Page/Command 和原生会话。准确前置业务体验候选 d0e6326bcca49a2c8372c476c50808d454076127；F01原业务证据按未变依赖保留，当前设计返修及用户验收待确认。F01 制品、启动入口与10611/10612/20611保持；新 N02 不使用这些业务资料验证。

## 依赖与责任

| 依据 | 当前结论及消费者 |
|---|---|
| 需求/设计 | SATISFIED；当前完整26项工单、原 N02 区域与通用状态，不按原生组件当前功能缩减 |
| 身份/原生框架 | SATISFIED 输入基础；UI02 当前 ClientProvider、历史、新建/选择/搜索、原生输入/上传/流式/停止及 D06；当前完整采用仍需逐项核查 |
| 领域/消息/来源/版本 | 已接收附件6164aac至eb9a4fe、上下文9c47e22至66fc44d及任务引用8f2fa15至d5c9316；Conversation Schema1.2.0、实际上传、正式来源元信息及实际任务工具引用已采用 |
| Agent/Runtime | 已接收原生b1eb8ed至2260000、条件查询cd1a5b0至1b7a7fa、原请求历史a74e97a至9c3caf8、本轮引用3259f2a至490ba0b、取消与期限4836527至e31370e；六项读取和query_metrics共七项正式工具，同一实际AgentLoop及Registry |
| 公开接收/前端 | N3唯一维护实际注册、RoleChannel、App、Shell、组件/样式、独立制品与连续验证；采用准确已有接口，不编造新业务值 |
| 独立核查 | N4按原 PRD/设计建立26项独立矩阵；准确候选后只核查必要差距和受影响消费者 |
| 新框架/真实外部/新视觉 | NOT_APPLICABLE；沿用当前技术及设计；SIMULATED_FIRST，FR-27保持暂停 |

原 HTML 的会话列表/中部对话/任务与来源，与实际加载 chat 的当前会话/对话执行及持续进展共同映射。历史区域保持克制，当前任务/来源可打开，连续阅读及输入采用原生组件，区域顺序、宽度、间距和重排依据保存到当前设计说明。固定 Token、44px目标及键盘/200%要求继续有效；设计预览标识和静态示例不进入产品。

## 当前验证与续接

当前没有完整 N02产品或业务通过声明。26项必要断言引用完整工单；N1/N2已有正确接口直接接收，存在差距才增量实施。公共层需要核查自然输入、附件、当前事项、同一 Runtime、任务/来源/产物、消息授权、原编号恢复及独立共享路径，不能仅将旧原生会话改名后登记完成。

当前任务进入会话的版本绑定仍在实施：F06当前任务需要专门的正式上下文准备与绑定，固定本人选定任务、展示版本及来源引用；仅有工具读取产物与详情返回不构成该项完成。N1领域5fb1def3cfd17e895691ccd8c52d1effed441886及记录9bc80e2fad33e08d9944be76e388d1189eff7cbc已接收至5919fd3/4d7038d，Conversation Schema1.3.0。ConversationAPI(store).task_entry(actual_native_sessions)提供prepare/bind/read/receipt，当前14项任务入口检查通过、3.96秒，task-entry-receiver.xml。N2已续接marker=MENU-N02-N2-TASK-ENTRY-CONSUMER-20261025；N3公开/UI入口和Native消费者待完成。迟到文件编码等其余必要路径继续核查。

已实施当前草稿及普通缓存保护增量：ThreadComposer暴露仅在进程内的 ComposerDraftController，涵盖文字、实际附件、引用和排队输入；ThreadShell透传，App以当前会话注册，用于切换、浏览历史地址及离开业务路径。本人明确放弃时清除对应未发送内容，返回继续编辑保留内容；beforeunload覆盖仅附件/排队状态。本人会话明确设置 persistQueuedPrompts=false，继续使用原生内存队列，不读取或写入普通 localStorage队列正文。源码增量保存在 app/webui/nanobot-menu-n02.patch。

独立menu-n02-n3-dist完成TypeScript及Vite构建，当前manifest=0a1c260c9281c97b85a0a8b6e1e1a30cf9f5b1d69066a238be74ed05e3a66d6c，构建17.07秒，日志.work/menu-n02-build.log。`check-menu-n02-native-privacy.cjs`的证据native-privacy.json采用7fd1a426910b2f4efed10143e91f3fc76d9afe1502ce2234ef91107a31c016c5及未变的内存队列/附件控制器，独立10731/10732/20731及代理10733。实际产物Dialog/Escape/焦点、批准YAML仅附件离开保护、真实输出延迟下内存队列未发送/不缓存/明确放弃后不恢复均通过；不据该限定结果登记26项通过。

BossConversationWorkspace采用真实topicSessions、原生新建/选择/搜索、同一ThreadShell和D06；主列保留当前关联事项、资料版本、任务对象及对话/可观察执行，右列呈现实际进展、异常、来源与可展开附件。实际Runtime产物通过当前会话及原运行引用重读，关闭后返回原按钮；请求/身份/会话变化使迟到结果失效。N02为当前实际入口，原NATIVE本人地址保持兼容，维护Settings保持既有入口。F08仅开放本菜单所需的既有共享消息路径，完整消息授权/回复和一般会话采用继续核查。

N2模块提供ConversationContext/ConversationScope、六项正式读取适配、ConversationQueryTool、ConversationSimulatedProvider/ConversationRuntimeRecorder及NativeConversationAgent，记录输入/参数摘要与正式引用，不提供模型本人确认。当前公共ProductConversation采用同一AgentLoop、SessionManager、Registry及Runtime；query_metrics明确使用继承ConversationReadTool的ConversationQueryTool、同库Fc02Tool及本轮QueryBinding，执行前后检查当前范围与允许参数摘要；其他读取按当前可信范围适配。FeatureRecorder准备阶段使用当前RequestContext，配置必须实际启用七项工具及正式工作投影模式。当前组合61 passed、144.412秒，native-runtime-receiver.xml；正式读取、查询、普通文档、仅附件、命令、取消/超时和原编号历史分别保持限定范围。

公共runtime-records.schema.json为1.12.0：接收feature_id=N02、conversation_context中输入摘要/允许调用摘要/正式引用、原请求及媒体摘要、附件编号/摘要/状态和待补充数量；工具结果允许正式draft_id及parameters_sha256。不接收正文或原始参数。RUNTIME_RECORD只允许conversationRead，并禁止携带source_id、query_id、task_id、message_id、draft_id、authorization_id、source_refs或bi_query_context；SIMULATED业务结果继续采用原有规则。当前公开消费者形成的14条真实运行全部通过CurrentRuntimeRun严格验证，check_menu_n02_runtime.py及native.json保存实际结果。

RoleChannel在原生router之前核查当前本人、attach、token及期限，优先采用晨间绑定，一般会话通过NativeConversationAgent.admit接收。实际上传成功后内部record_media采用gateway返回路径；同一chat/turn内容重复只返回原回执，同键内容变化拒绝。boss.conversation.request按当前连接的chat_id/turn_id读取，HTTP原编号入口仅按client_request_id读取；均不产生业务变更或自动重放。SDK非Agent命令保留原路径。准备失败仅记录provider名称、时间及错误类别，不记录输入或原异常正文。

check-menu-n02-native.cjs已通过，准确制品manifest=0a1c260c9281c97b85a0a8b6e1e1a30cf9f5b1d69066a238be74ed05e3a66d6c，证据native.json。独立10761/10762/20761、生成的测试账号和SQLite通过实际WebSocket连续来源读取及追问，参数摘要随选择变化，每轮只有一个N02 Runtime；重复轮次没有额外执行，同键异内容拒绝，未知编号读取没有写入。真实JSON附件与仅附件提交分别保存元信息或等待用途；经营条件不足等待，补充后产生正式查询，改变产品及指标后产生关联父查询的新结果和新参数摘要。页面当前来源支持关系、原/当前版本、完整查询表格、Dialog关闭和焦点返回均按实际结果核对；问题不进入URL或普通存储。查询产物进入正式来源原文、任务产物进入交办详情后，返回同一会话、运行选择、原滚动位置和原产物按钮焦点均已验证。

同一公开连续检查从N02进入共享F08，使用正式联系人及实际财务资料保存草稿；未保存编辑由D06保护，草稿保存零发送，当前本人明确确认后只产生一条SIMULATED发件，维护输入明确SIMULATED回复后reply_to仍指原消息，delivery_state保持NOT_VERIFIED。返回同一会话的运行选择、滚动和焦点保持，Native实际读取原消息后可以重读同一业务对象。共享F06缺少条件和取消决定均零任务，明确创建后新增OPEN任务且没有自动发送；Native读取形成同一task_id/version的实际产物，运行结束没有结束任务。共享路径不登记F08/F06整套菜单完成。

实际完成且finished_at已保存的WAITING_INPUT不计在途运行，运行配置可以正常继续维护；QUEUED/RUNNING及尚无结束时间的等待记录继续限制启用。公开检查通过真实维护配置暂时缺少必要工具产生准备失败，原client_request_id保持FAILED且run_id=null；恢复配置后新请求正常。boss.conversation.requests严格接收chat_id，当前本人/attach/有效身份和资料范围均核查；维护、未订阅、注入归属或错误字段拒绝。关闭本检查自己的服务并同库重启后，14个run_id、15个原请求、附件和原回执保持，没有额外执行。

N1领域与既有消息消费者在当前PRODUCT共19 passed、10.81秒，原始证据evidence/menu-delivery/N02/received-domain.xml。PublicConversation已接入RoleChannel的四项只读webui_request：boss.conversation.read/artifact/messages/attachments。身份和会话归属由当前认证连接及已订阅chat核查，session_id从原生映射产生，客户端不能提供owner/namespace/session_id。消息历史明确为OWNER_MESSAGE_HISTORY。`check-menu-n02-conversation-read.cjs`通过，结果public-read.json；采用独立10741/10742/20741及实际SDK晨间运行依赖，证明准确运行/产物读取、重复读取不变及维护/未订阅/注入字段/无关产物拒绝。该检查不证明一般会话规划、完整附件处理或完整N02菜单。

实际原生上传成功后，由RoleChannel当前请求内的可信上下文将accepted_media/accepted_paths交给PublicConversation内部record_upload；模型和客户端没有文件路径命令。Schema1.1.0公开区分当前/上传时大小与摘要、可空原生位置及STORED/MISSING/CHANGED/REFERENCE_UNAVAILABLE，不公开内部文件引用。实际WebSocket上传批准morning-coverage.json并完成SDK保存后，public-read.json核对原名/MIME/大小/摘要、无路径输出与原运行；附件领域/SDK保存/既有消息消费者23 passed、8.05秒，证据native-file-receiver.xml。文件保存不授予业务来源资格。当前文件变化状态及一般会话实际采用仍需对应消费者。

N1上下文9c47e229e3ee6e67d853076b6b98089e7067e966已接收至66fc44d；上下文和附件接收13 passed、8.61秒，context-reference-receiver.xml。任务引用8f2fa156e739b1d0a16640988bb5e75da31e2eb7及记录2f7c48ea0a17e5b114583067cfa7f35b28b6a04d分别接收至d5c9316/6611eef；task-reference-receiver.xml为6 passed、6.45秒。当前页面直接呈现正式context_references中的原/当前版本、作者、时间、范围、采用状态与上下文/工具支持关系，不根据模型正文推断来源。公开连续检查已验证实际task_id/version及TOOL_RESULT支持关系。

N2原请求只读历史a74e97abb4d8a93a027cc6287e6e941a5d0917cb已接收至9c3caf8，公开Schema为conversation-requests.schema.json，包含尚无Runtime的准备失败或取消记录。本轮必要引用3259f2a4ff74420b8b8b6b941bef37e96ff35472接收至490ba0b，独立新问题仅采用当前必要引用，明确追问继续核查原来源版本。取消与实际期限4836527f3de19383d5eed8bb608c4fc891215104接收至e31370e；当前组合native-runtime-receiver.xml为61 passed、144.412秒。实际SDK取消只终止对应轮次，另一会话继续；当前配置120秒期限实际经过120.424秒后终止，已保存查询与原意图可读。公开注册由N3负责，同一请求不得重复生成Runtime。

原设计实际加载检查已运行：18组DOM/计算样式/尺寸见reference-dom.json，含三种窗口100%/200%及阈值相邻样本。当前独立10751/10752/20751记录framework-current.json，manifest=7fd1a426910b2f4efed10143e91f3fc76d9afe1502ce2234ef91107a31c016c5；18组默认区域、18组历史展开及18组提交按钮五种状态均完成测量。当前输入框横向位置、宽度及88px高度与原稿18组相同；主操作提交需求为84×44、14/690/24，实际label及添加附件入口采用原稿文字，悬停保持原背景。每组历史均为本实例12个实际请求生成的会话，原运行编号可核查；展开宽度>1250为213px，其他宽度按原阈值单列，实际滚动可达。记录SVG节点/属性、子Panel、图像、输入祖先和滚动祖先；伪元素仅记录计算样式，不作为独立边界测量。完整设计、全部状态及交互仍需复核，记录见design-gaps.md。F01冻结manifest e3b36c80baac9bbba869d5012b53d38c43b2a05d1869ec9ce10a0c365bafd62c及index 11a935970330ddfa87e50faeb5f266cd27163f11750945e01797be25d3396b1f保持独立保护。

新应用实例通过官方set_config_path及runtime-scope.json绑定自身配置目录；新实例初始历史为空，随后仅使用自身生成的会话。原有无实例声明的用户体验保持其既有运行目录，不自动迁移或重启。当前native及unknown均验证新实例范围，native同库重开仍读取原14条运行与15条请求。

check-menu-n02-unknown.cjs及unknown.json采用当前同一manifest、独立10771/10772/20771及10773代理。代理仅在实际保存或发送成功后中断真实连接；客户端刷新和重连没有重新提交，普通地址仅保留原操作编号/类型及返回标识，不包含正文、附件或凭据。按原编号只读核查后分别得到既有草稿及唯一SIMULATED发件，delivery_state仍为NOT_VERIFIED；可继续返回原N02共享入口。消息未知状态阻止新的保存/发送，确定未保存的输入仍由D06保护。

check-menu-n02-input.cjs及input.json采用当前同一manifest、独立10781/10782/20781。实际Chromium IME候选期间Enter零提交，提交候选文字后值正确；Shift+Enter保留换行，空白不可提交。实际BossDesktop.tsx正文74486 bytes超过bootstrap发布的65536 bytes限制时就地提示、保留输入且零提交。708份实际应用及已安装Runtime源码形成8523725 bytes的真实JSON导出，超过6291456 bytes单文件限制时拒绝，原输入保持，没有填充或重复资料。实际文件读取权限拒绝后，原文字与既有文件保留、错误附件不能提交。四份Schema文件选择、取消、数量拒绝、不支持的真实脚本文件均保留原文字与附件；真实Schema内容以192 bytes长文件名选择成功。文字与四附件的D06继续编辑/明确放弃通过。语音入口禁用且显示暂停，原生Control+Shift+D零转写请求；本项不代表FR-27完成。

当前native-privacy.json包含实际后续输出期间的历史阅读：本人点击并使用滚轮阅读历史后，真实响应由代理继续传递，内容高度789→1312px、clientHeight181px，scrollTop保持0，没有强制到底部。framework-current.json同时包含实际搜索12项会话、键盘选择与对应历史恢复，再进入新空会话测量18组状态。

N2可观察事件与失败结果d6196221f92d5e9b325a6e3011b217d782a1225b接收至ba1fbde；生产签名及字段未变。observable-failure-receiver.xml为4 passed、3.88秒：真实关闭输出管道后失败、正式查询拒绝均保留已保存结果，终态FAILED/error；当前Provider、SDK事件、原生进度及历史未发现内部推理载荷。轮次不足为准备阶段拒绝、run_id=null；不声明已经进入SDK max_iterations耗尽路径。

N4对b3de8ea3788629f977f02f182e74a18ea430dc85及7fd1制品的指定增量结论为APPROVED/TARGETED_CLOSED，记录位于其N02/qa.md，SHA256=30db6b3981e5df7bdf84046b391da4f1b09636d4f2e9594f482ebe6f83babeca。范围为SVG、子Panel、标签/输入/附件及提交操作、五种按钮状态、历史展开和两条产物详情返回；该范围未发现未处理必要缺陷。完整26项及其他未验证状态继续保留。

scripts/run_menu_n02.command与prepare_menu_n02.py已在独立menu-n02-launcher-check-*资料目录、10791/10792/20791从实际新建初始化至重用启动通过，见launcher.json，采用当前0a1c制品。默认新入口为10711/10712/20711及menu-n02-experience，尚未作为完整菜单交付；初始化只读取本次新生成的测试账号，已有目录启动不读取账号内容或重写资料。启用七项会话工具及既有晨间/采购工具、WORKSPACE_PROJECTIONS模式。受控主窗口分别填入BOSS/MAINTAINER既有账号，填充后零自动登录，明确提交登录后角色正确、单窗口；密码不在普通地址或存储中，账号文件元数据及业务资料保持。F01冻结制品摘要已再次核对一致。

实际窗口关闭和app.quit由当前页面现有D06处理，用户继续编辑时不终止业务服务；明确放弃后才关闭窗口并结束服务。关闭IPC只接收当前主窗口的当前主Frame，且需要实际关闭请求；业务/账号能力继续核查应用业务来源和既有认证。close.json采用当前0a1c制品、独立10801/10802/20801：没有关闭请求的确认被拒绝；三种桌面尺寸及200%缩放六组D06按钮至少44×44、全部在视口内、Tab/Shift+Tab焦点正确；窗口关闭、app.quit取消均保留文字/实际文件和后端，F08编辑采用既有D06；明确放弃后实际应用exit_code=0。

已发送当前四窗口的角色续接，marker=MENU-N02-START-20261024；每次发送前复查 idle。N1 turn=01a16df8-d1c1-79f3-87d2-3b362d5c889e，N2 turn=01a16df8-e6aa-7ac3-8a7b-a0abfc791fc0，N4 turn=01a16df8-f3bc-7ad1-8f73-d95ab5c77283；工具分别返回对应既有 threadId。运行中仅只读，角色准确自然交付后接收必要增量，禁止重复接续。

主记录随准确接口、设计选择、实际修改和原始结果更新；保持全体未完成项、当前范围与必要阻塞。正常完成当前26项后登记开发交付待用户验收，并处理进入 N03前必要的 F01设计返修，始终只实施一个菜单。暂停语音独立保留，不计完成。现有四窗口仅在 idle 复查后一次具体续接，marker=MENU-N02-START-20261024，运行中只读。

## 固定任务入口与当前消费

N1任务入口5fb1def3cfd17e895691ccd8c52d1effed441886及记录分别接收至5919fd3/4d7038dc7e5accb2e0123a3f3a28392e2a8c2385。task-entry-receiver.xml为14 passed、3.96秒；既有消费者接收4 passed、3.86秒。N2消费者e2d76dceb354d50781fd13f0100d2979a74f3c7a接收至6d620bb，task-bound-consumer-receiver.xml为16 passed、10.68秒。Runtime Schema 1.13.0生产者b5e2fbe6a6571d90f5f3c2d5c0ae407e3817980c接收至b131d96；task-bound-schema-receiver.xml为4 passed、4.32秒，包含58项受限输入拒绝。Schema基线采用固定def38c666c6b653aa939062540e692ba2dbd0e5a的1.12.0原文，当前运行字段完整参与验证。生产者完整85项SDK回归为160.79秒，包含实际120秒deadline。

PublicConversation公开注册prepare/bind/read/receipt四项任务入口动作；服务端确定会话标识及本人范围。客户端使用实际useSessions.createChat与原生new_chat，绑定前由官方gateway.workspaces.persist_scope保存真实空会话及已有工作空间范围。固定任务与来源在保存空会话之前重新核查，绑定不提交问题、不创建业务任务、不模拟发送。重连不会重放prepare或bind；按原client_request_id只读查询，不将历史回执视作当前有效性证明。

F06选择已经保存的实际任务后，可建立固定版本的任务会话。准备、绑定和最终打开分别检查当前身份与选择；离开前新增编辑仍由D06处理。N02直接读取当前绑定，显示原任务与来源版本及返回入口；当前连接建立并订阅原会话后才读取，换会话清除原关联，业务详情返回保留原按钮与焦点。

check-menu-n02-task-entry.cjs及task-entry-ui.json在独立10811/10812/20811和10813真实代理通过，manifest=957cbd051c48adad90831a7753381f7db75beecdea54e1530c143045733fe823。实际准备与绑定成功响应分别中断，每项仅提交一次，刷新按原记录恢复；打开期间零问题、零Runtime。本人提交“查看当前任务”后，实际conversationRead仅采用选定task_id/version，Runtime完整task_entry通过1.13.0。来源和任务详情返回、同会话刷新保持；真实延迟准备响应不改变新选择，绑定期间新增编辑保留并再次经过D06。新会话不继承任务；本人正式取消任务后，后续输入在Runtime建立前FAILED、run_id=null，原运行和历史准备记录保留。本项不代表完整26项、视觉或用户验收完成。

N4对def38c666c6b653aa939062540e692ba2dbd0e5a的关闭和文件指定增量结论为APPROVED/TARGETED_CLOSED，qa.md摘要79adf404cef54765f43ac94aa4ca9501dadf54f709d4d7ec1504aef45b3dfd07；完整菜单证据继续保持未完成。

## 资料与运行

保护原 UI02/MVP 及当前已交付 F01 的制品、账号、SQLite、会话、端口与用户窗口。新候选使用独立目录、制品和端口，不自动退出、重启、覆盖或热替换已有体验。受控账号注入仅填写当前角色表单，手动登录仍经正常认证。全部外部 SIMULATED_FIRST，无新增真实外部请求；STT/F27/FC28暂停。禁止主动视觉、截图、图像、/tmp、Git恢复和程序化修改源码。
